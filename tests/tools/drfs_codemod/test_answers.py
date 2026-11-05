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


_BOTH_ENTRIES = textwrap.dedent(
    """\
    from django_service_specs import Parameter, Parameters
    from rest_framework.permissions import AllowAny
    from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec, ServiceViewSet

    from tests.testapp.models import Author
    from tests.testapp.serializers import AuthorSerializer


    def rename(*, instance, data):
        instance.name = data["name"]
        instance.save(update_fields=["name"])
        return instance


    target = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    )

    replace = ServiceSpec(
        service=rename,
        input_serializer=AuthorSerializer,
        output_serializer=AuthorSerializer,
        instance_selector_spec=target,
        permission_classes=[AllowAny],
        success_status=203,
    )

    amend = ServiceSpec(
        service=rename,
        input_serializer=AuthorSerializer,
        output_serializer=AuthorSerializer,
        instance_selector_spec=target,
        permission_classes=[AllowAny],
        success_status=202,
    )


    class Authors(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {ENTRIES}
    """
)


@pytest.mark.parametrize(
    "entries",
    [
        '{"update": replace, "partial_update": amend}',
        '{"partial_update": amend, "update": replace}',
    ],
    ids=["update-first", "partial-update-first"],
)
@pytest.mark.parametrize(
    "method, action, status", [("put", "update", 203), ("patch", "partial_update", 202)]
)
def test_a_partial_update_entry_of_its_own_keeps_its_answer(
    entries: str, method: str, action: str, status: int
) -> None:
    # drfs reads the partial_update entry's spec for a PATCH when the view has
    # one, so the update entry's answer reaches only its own action.
    output, findings = rewrite_source(
        _BOTH_ENTRIES.replace("{ENTRIES}", entries), Path("app/views.py")
    )
    assert output.count("get_partial_update_success_status =") == 1
    assert not [finding for finding in findings if "already declares" in finding.reason]
    module = types.ModuleType("rewritten_both_entries")
    exec(compile(output, "rewritten_both_entries.py", "exec"), module.__dict__)
    author = Author.objects.create(name="before")
    view = module.Authors.as_view({method: action})
    response = getattr(factory, method)("/", {"name": "after"}, format="json")
    assert view(response, pk=author.pk).status_code == status


# --- shapes the analysis reads without serving ---------------------------------
#
# ``_Analysis`` finds the views serving a spec by shape: ``spec = name``, an
# ``action_specs`` dict literal, a ``@service_action(name)`` decorator, each
# at the depth of a top-level class. Anything else that merely resembles one is
# not a use site, and must neither crash the run nor take the answer.

_LOOKALIKE_HEAD = textwrap.dedent(
    """\
    from rest_framework_services import (
        SelectorSpec,
        ServiceCreateView,
        ServiceSpec,
        ServiceViewSet,
        service_action,
    )

    signup = ServiceSpec(service=print, success_status=202)


    """
)

_NOT_MOVED = [
    "success_status=202 is the view's or the action's: set success_status on the view, "
    "@service_action(..., success_status=...), or get_<action>_success_status on the viewset"
]

_NOT_MOVED_201 = _NOT_MOVED[0].replace("=202", "=201")

_LOOKALIKES = {
    # ``action_specs``: the dict literal, its keys and its values.
    "an-inline-spec-as-an-action-specs-value": (
        'class V(ServiceViewSet):\n    action_specs = {"update": ServiceSpec(service=print)}\n'
    ),
    "a-non-string-constant-key": "class V(ServiceViewSet):\n    action_specs = {1: signup}\n",
    "a-name-as-an-action-specs-key": (
        'UPDATE = "update"\n\n\nclass V(ServiceViewSet):\n    action_specs = {UPDATE: signup}\n'
    ),
    "dict-call-for-action-specs": (
        "class V(ServiceViewSet):\n    action_specs = dict(update=signup)\n"
    ),
    "a-dict-literal-under-another-name": (
        'class V(ServiceViewSet):\n    entries = {"update": signup}\n'
    ),
    # ``spec``: a name, under that name.
    "a-spec-that-is-built-in-place": "class V(ServiceCreateView):\n    spec = build()\n",
    "a-spec-name-under-another-attribute": "class V(ServiceCreateView):\n    other = signup\n",
    # ``@service_action(...)`` on a method of a top-level class.
    "a-decorator-with-no-arguments": (
        "class V(ServiceViewSet):\n    @x()\n    def act(self):\n        pass\n"
    ),
    "a-decorator-that-is-no-call": (
        "class V(ServiceViewSet):\n    @service_action\n    def act(self):\n        pass\n"
    ),
    "a-spec-given-by-keyword": (
        "class V(ServiceViewSet):\n    @service_action(spec=signup)\n    def act(self):\n"
        "        pass\n"
    ),
    "a-spec-built-in-the-decorator": (
        "class V(ServiceViewSet):\n    @service_action(build())\n    def act(self):\n        pass\n"
    ),
    "another-decorator-taking-the-name": (
        "class V(ServiceViewSet):\n    @cache(signup)\n    def act(self):\n        pass\n"
    ),
    "a-decorated-function-outside-any-class": "@service_action(signup)\ndef act():\n    pass\n",
    # Depth: only a top-level class serves a spec.
    "a-decorated-method-of-a-nested-class": (
        "class V(ServiceViewSet):\n    class Inner:\n        @service_action(signup)\n"
        "        def act(self):\n            pass\n"
    ),
    "a-chained-spec-assignment": "class V(ServiceCreateView):\n    spec = other = signup\n",
    "a-tuple-target-in-a-class": "class V(ServiceCreateView):\n    spec, other = signup, 1\n",
    "a-spec-attribute-of-a-nested-class": (
        "class V(ServiceViewSet):\n    class Inner:\n        spec = signup\n"
    ),
}


@pytest.mark.parametrize("body", _LOOKALIKES.values(), ids=_LOOKALIKES.keys())
def test_a_lookalike_serves_no_spec_and_takes_no_answer(body: str) -> None:
    source = _LOOKALIKE_HEAD + body
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert [finding.reason for finding in findings] == _NOT_MOVED
    assert "success_status =" not in output
    assert "get_update_success_status =" not in output
    assert body in output
    assert rewrite_source(output, Path("app/views.py"))[0] == output


def test_a_splat_beside_an_entry_leaves_the_entry_served() -> None:
    output, findings = rewrite_source(
        _LOOKALIKE_HEAD
        + 'class V(ServiceViewSet):\n    action_specs = {**base, "update": signup}\n',
        Path("app/views.py"),
    )
    assert "    get_update_success_status = 202\n" in output
    assert "    get_partial_update_success_status = 202\n" in output
    assert [finding.reason for finding in findings] == [
        "success_status=202 moved to V.get_update_success_status, "
        "V.get_partial_update_success_status; a view in another module serving signup "
        "declares it itself"
    ]


def test_a_call_that_is_no_spec_is_left_as_written() -> None:
    source = 'options = configure(input_serializer=Doc, reads=["q"], success_status=201)\n'
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert output == source
    assert findings == []


def test_a_selector_takes_no_answer() -> None:
    """``success_status`` is a service's: a selector served by a view does not carry it over."""
    source = (
        "from rest_framework_services import SelectorSpec, ServiceCreateView\n\n"
        "target = SelectorSpec(selector=lambda: None, success_status=201)\n\n\n"
        "class V(ServiceCreateView):\n    spec = target\n"
    )
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert [f.reason for f in findings if "success_status=201" in f.reason] == [_NOT_MOVED_201]
    assert "success_status =" not in output


def test_a_spec_built_inside_a_class_is_not_a_module_level_name() -> None:
    source = (
        _LOOKALIKE_HEAD
        + "class V(ServiceCreateView):\n    mine = ServiceSpec(service=print, success_status=201)\n"
        "    spec = mine\n"
    )
    output, findings = rewrite_source(source, Path("app/views.py"))
    assert [f.reason for f in findings if "success_status=201" in f.reason] == [_NOT_MOVED_201]
    assert "success_status =" not in output


@pytest.mark.parametrize(
    "value, written",
    [
        ("201", "get_update_success_status = 201\n"),
        ("status.HTTP_201_CREATED", "get_update_success_status = status.HTTP_201_CREATED\n"),
        ("created", "get_update_success_status = staticmethod(created)\n"),
        # The pattern is anchored: a status inside a longer expression or name is a callable.
        (
            "201 if flag else 202",
            "get_update_success_status = staticmethod(201 if flag else 202)\n",
        ),
        ("MY_HTTP_201", "get_update_success_status = staticmethod(MY_HTTP_201)\n"),
    ],
)
def test_a_hook_is_spelled_direct_for_a_status_and_wrapped_for_a_callable(
    value: str, written: str
) -> None:
    # A plain status reads back the same either way; the output is the
    # codemod's product, so the spelling a person reviews is pinned.
    source = (
        "from rest_framework import status\n"
        "from rest_framework_services import ServiceSpec, ServiceViewSet\n\n"
        f"signup = ServiceSpec(service=print, success_status={value})\n\n\n"
        'class V(ServiceViewSet):\n    action_specs = {"update": signup}\n'
    )
    output, _ = rewrite_source(source, Path("app/views.py"))
    assert f"    {written}" in output


def test_a_decorator_reached_through_a_module_takes_the_answer() -> None:
    source = (
        "import rest_framework_services as drfs\n"
        "from rest_framework_services import ServiceSpec, ServiceViewSet\n\n"
        "signup = ServiceSpec(service=print, success_status=202)\n\n\n"
        "class V(ServiceViewSet):\n    @drfs.service_action(signup)\n"
        "    def act(self):\n        pass\n"
    )
    output, _ = rewrite_source(source, Path("app/views.py"))
    assert "    @drfs.service_action(signup, success_status=202)\n" in output
