"""A drfs spec's ``success_status`` and ``response_finalizer`` move to the views serving it.

A kernel spec declares no HTTP answer, so the codemod moves each onto the
views in the same module that serve the spec: the ``@service_action``
keyword, a ``get_<action>_<name>`` hook beside an ``action_specs`` entry (an
``update`` entry's ``partial_update`` too), or the view's own attribute. Each
placement is proven by a real request through the rewritten module.

The target selector reads ``pk`` as the kernel does, as a hand-finished
``reads=`` marker leaves it.
"""

from __future__ import annotations

import textwrap
import types
from pathlib import Path
from typing import Any

import pytest
from drfs_codemod.rewrite import rewrite_source
from rest_framework.test import APIRequestFactory

from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()

SOURCE = textwrap.dedent(
    """\
    from django_service_specs import Parameter, Parameters
    from rest_framework import status
    from rest_framework.permissions import AllowAny
    from rest_framework_services import (
        SelectorKind,
        SelectorSpec,
        ServiceCreateView,
        ServiceSpec,
        ServiceViewSet,
        service_action,
    )

    from tests.testapp.models import Author
    from tests.testapp.serializers import AuthorSerializer


    def stamp(*, response):
        response["X-Answer"] = "stamped"


    def accepted():
        return 203


    def create_author(*, data):
        return Author.objects.create(name=data["name"])


    def rename(*, instance, data):
        instance.name = data["name"]
        instance.save(update_fields=["name"])
        return instance


    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    )

    enrol = ServiceSpec(
        service=create_author,
        input_serializer=AuthorSerializer,
        output_serializer=AuthorSerializer,
        permission_classes=[AllowAny],
        success_status=status.HTTP_202_ACCEPTED,
        response_finalizer=stamp,
    )

    update = ServiceSpec(
        service=rename,
        input_serializer=AuthorSerializer,
        output_serializer=AuthorSerializer,
        instance_selector_spec=target,
        permission_classes=[AllowAny],
        success_status=accepted,
        response_finalizer=stamp,
    )

    signup = ServiceSpec(
        service=create_author,
        input_serializer=AuthorSerializer,
        output_serializer=AuthorSerializer,
        permission_classes=[AllowAny],
        success_status=accepted,
        response_finalizer=stamp,
    )


    class Authors(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {"update": update}

        @service_action(enrol, methods=["post"])
        def enrol(self, request):
            pass


    class SignUp(ServiceCreateView):
        spec = signup
    """
)


@pytest.fixture(scope="module")
def rewritten() -> tuple[str, types.ModuleType]:
    output, _ = rewrite_source(SOURCE, Path("app/views.py"))
    module = types.ModuleType("rewritten_views")
    exec(compile(output, "rewritten_views.py", "exec"), module.__dict__)
    return output, module


def _assert_answer(response: Any, status: int) -> None:
    assert response.status_code == status, response.data
    assert response["X-Answer"] == "stamped"


def test_the_spellings_written(rewritten: tuple[str, types.ModuleType]) -> None:
    output, _ = rewritten
    assert "success_status=status.HTTP_202_ACCEPTED, response_finalizer=stamp)" in output
    assert "get_update_success_status = staticmethod(accepted)" in output
    assert "get_partial_update_success_status = staticmethod(accepted)" in output
    assert "get_update_response_finalizer = staticmethod(stamp)" in output
    assert "get_partial_update_response_finalizer = staticmethod(stamp)" in output
    assert "    success_status = accepted\n    response_finalizer = stamp\n" in output


def test_the_decorator_answers_its_action(rewritten: tuple[str, types.ModuleType]) -> None:
    _, module = rewritten
    view = module.Authors.as_view({"post": "enrol"})
    _assert_answer(view(factory.post("/", {"name": "a"}, format="json")), 202)


@pytest.mark.parametrize("method, action", [("put", "update"), ("patch", "partial_update")])
def test_the_hook_answers_the_entry_and_its_partial_update(
    rewritten: tuple[str, types.ModuleType], method: str, action: str
) -> None:
    _, module = rewritten
    author = Author.objects.create(name="before")
    view = module.Authors.as_view({method: action})
    request = getattr(factory, method)("/", {"name": "after"}, format="json")
    _assert_answer(view(request, pk=author.pk), 203)
    author.refresh_from_db()
    assert author.name == "after"


def test_the_view_attribute_answers_the_view(rewritten: tuple[str, types.ModuleType]) -> None:
    _, module = rewritten
    view = module.SignUp.as_view()
    _assert_answer(view(factory.post("/", {"name": "a"}, format="json")), 203)


def test_a_view_in_this_module_is_named_in_the_report() -> None:
    _, findings = rewrite_source(SOURCE, Path("app/views.py"))
    # One line per keyword, in the order of the spec's line, then the reason.
    assert [finding.reason for finding in findings] == [
        "response_finalizer=stamp moved to @service_action(..., response_finalizer=...) on "
        "Authors.enrol; a view in another module serving enrol declares it itself",
        "success_status=status.HTTP_202_ACCEPTED moved to @service_action(..., "
        "success_status=...) on Authors.enrol; a view in another module serving enrol "
        "declares it itself",
        "response_finalizer=stamp moved to Authors.get_update_response_finalizer, "
        "Authors.get_partial_update_response_finalizer; a view in another module serving "
        "update declares it itself",
        "success_status=accepted moved to Authors.get_update_success_status, "
        "Authors.get_partial_update_success_status; a view in another module serving update "
        "declares it itself",
        "response_finalizer=stamp moved to SignUp.response_finalizer; a view in another module "
        "serving signup declares it itself",
        "success_status=accepted moved to SignUp.success_status; a view in another module "
        "serving signup declares it itself",
    ]


@pytest.mark.parametrize(
    "body, reason",
    [
        (
            "    def get_enrol_success_status(self):\n        return 201\n\n"
            '    @service_action(enrol, methods=["post"])\n    def enrol(self, request):\n'
            "        pass\n",
            "Authors.enrol declares get_enrol_success_status; a decorator value beside it is "
            "refused",
        ),
        (
            '    @service_action(enrol, methods=["post"], success_status=201)\n'
            "    def enrol(self, request):\n        pass\n",
            "Authors.enrol's decorator already declares success_status",
        ),
    ],
)
def test_an_action_already_answering_is_marked(body: str, reason: str) -> None:
    source = (
        textwrap.dedent(
            """\
        from rest_framework_services import ServiceSpec, ServiceViewSet, service_action

        enrol = ServiceSpec(service=print, success_status=202)


        class Authors(ServiceViewSet):
        """
        )
        + body
    )
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert reason in [finding.reason for finding in findings]
    again, findings_again = rewrite_source(output, Path("app/views.py"))
    assert again == output
    assert reason in [finding.reason for finding in findings_again]


@pytest.mark.parametrize(
    "body, reason",
    [
        ("    spec = signup\n    success_status = 200\n", "SignUp already declares success_status"),
        (
            '    action_specs = {"update": signup}\n\n    def get_update_success_status(self):\n'
            "        return 200\n",
            "SignUp already declares get_update_success_status",
        ),
    ],
)
def test_a_view_already_answering_is_marked(body: str, reason: str) -> None:
    source = (
        textwrap.dedent(
            """\
        from rest_framework_services import ServiceSpec, ServiceViewSet

        signup = ServiceSpec(service=print, success_status=202)


        class SignUp(ServiceViewSet):
        """
        )
        + body
    )
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert reason in [finding.reason for finding in findings]
    assert rewrite_source(output, Path("app/views.py"))[0] == output
