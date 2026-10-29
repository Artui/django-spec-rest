"""``ServiceUpdateView`` over a kernel spec.

A kernel spec's target is its own target selector's: the kernel refuses a
``target=`` handed to a spec declaring none, so the view never asks
``get_object()`` for one, and asks the view's object permissions of the row the
spec's lookup finds before the service runs, as ``get_object()`` would.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django_service_specs import (
    Affordance,
    DataclassValidator,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from django_spec_rest import ServiceDeleteView, ServiceUpdateView
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.mutation import utils
from django_spec_rest.views.mutation.utils import dispatch_mutation_for_spec
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _NameBio(serializers.Serializer):
    name = serializers.CharField()
    bio = serializers.CharField()


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    if "name" in data:
        instance.name = data["name"]
        instance.save(update_fields=["name"])
    return instance


lookups: list[int] = []


def _author(*, pk: int) -> Author | None:
    lookups.append(pk)
    return Author.objects.filter(pk=pk).first()


_AUTHOR = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_author,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
)
_PRESENTER = SerializerPresenter(AuthorSerializer)

_UPDATE = ServiceSpec(
    service=_rename,
    permissions=_OPEN,
    validator=SerializerValidator(_NameBio),
    instance_selector_spec=_AUTHOR,
    presenter=_PRESENTER,
)


class _UpdateView(ServiceUpdateView):
    spec = _UPDATE


def _view(spec: ServiceSpec, **attrs: Any) -> Any:
    return type("_View", (ServiceUpdateView,), {"spec": spec, **attrs}).as_view()


@pytest.fixture(autouse=True)
def _no_lookups() -> None:
    lookups.clear()


class TestServiceUpdateView:
    def test_put_full_update(self) -> None:
        author = Author.objects.create(name="orig")
        request = factory.put("/", {"name": "new", "bio": "b"}, format="json")
        response = _UpdateView.as_view()(request, pk=author.pk)
        author.refresh_from_db()
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "new"}
        assert author.name == "new"

    def test_a_put_validates_every_field(self) -> None:
        author = Author.objects.create(name="orig")
        response = _UpdateView.as_view()(
            factory.put("/", {"name": "new"}, format="json"), pk=author.pk
        )
        assert response.status_code == 400
        assert response.data["bio"][0].code == "required"

    def test_patch_partial_update(self) -> None:
        """A ``PATCH`` dispatches the spec's partial twin, so a field it leaves
        out is no refusal."""
        author = Author.objects.create(name="orig")
        response = _UpdateView.as_view()(
            factory.patch("/", {"name": "new"}, format="json"), pk=author.pk
        )
        author.refresh_from_db()
        assert response.status_code == 200
        assert author.name == "new"

    def test_a_partial_spec_takes_a_put_partially(self) -> None:
        """The kernel's ``partial`` is a plain flag: set, it holds for both verbs."""
        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=lambda *, instance, data: _rename(instance=instance, data=data) and None,
            permissions=_OPEN,
            validator=SerializerValidator(_NameBio),
            instance_selector_spec=_AUTHOR,
            partial=True,
        )
        response = _view(spec)(factory.put("/", {"name": "new"}, format="json"), pk=author.pk)
        assert response.status_code == 204
        author.refresh_from_db()
        assert author.name == "new"

    def test_a_patch_over_a_dataclass_validates_every_field(self) -> None:
        """A dataclass is built from every field, so it cannot take a partial
        call: a ``PATCH`` to it is validated as a ``PUT`` is, and a field it
        leaves out is the client's ``400`` rather than a server error."""

        @dataclass
        class _Name:
            name: str

        spec = ServiceSpec(
            service=lambda *, instance: instance,
            permissions=_OPEN,
            validator=DataclassValidator(_Name),
            instance_selector_spec=_AUTHOR,
        )
        author = Author.objects.create(name="orig")
        response = _view(spec)(factory.patch("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 400
        assert "name" in response.data

    def test_a_patch_with_no_validator_runs(self) -> None:
        spec = ServiceSpec(
            service=lambda *, instance: None, permissions=_OPEN, instance_selector_spec=_AUTHOR
        )
        author = Author.objects.create(name="orig")
        assert _view(spec)(factory.patch("/", {}, format="json"), pk=author.pk).status_code == 204

    def test_a_patch_dispatches_the_one_partial_variant_of_its_spec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every ``PATCH`` hands the kernel the spec's partial variant as
        ``kernel_spec_variant`` holds it, the one object a drfs spec's ``PATCH``
        compiles to as well, so there is one partial twin per spec, not two."""
        handed: list[Any] = []
        dispatched = utils.dispatch_kernel_spec

        def recording(spec: Any, **kwargs: Any) -> Any:
            handed.append(spec)
            return dispatched(spec, **kwargs)

        monkeypatch.setattr(utils, "dispatch_kernel_spec", recording)
        author = Author.objects.create(name="orig")
        view = _UpdateView.as_view()
        for _ in range(2):
            view(factory.patch("/", {"name": "new"}, format="json"), pk=author.pk)
        variant = kernel_spec_variant(_UPDATE, partial=True)
        assert variant is not _UPDATE
        # By identity: two equal twins would pass ``==``, a frozen dataclass
        # comparing by its fields.
        assert len(handed) == 2
        assert all(spec is variant for spec in handed)

    def test_404_when_instance_missing(self) -> None:
        response = _UpdateView.as_view()(
            factory.put("/", {"name": "n", "bio": "b"}, format="json"), pk=999
        )
        assert response.status_code == 404

    def test_service_error_maps_to_422(self) -> None:
        def boom(*, instance: Author) -> None:
            raise ServiceError("cannot")

        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=boom, permissions=_OPEN, instance_selector_spec=_AUTHOR, atomic=False
        )
        assert _view(spec)(factory.put("/", {}, format="json"), pk=author.pk).status_code == 422


class TestTheTarget:
    def test_a_put_s_own_row_is_asked_of_the_view_once(self) -> None:
        """The view's object permission is asked of the row the spec's lookup
        found, before the service runs, and the lookup runs once."""
        asked: list[Any] = []

        class _DenyObject(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                asked.append(obj)
                return False

        author = Author.objects.create(name="orig")
        response = _view(_UPDATE, permission_classes=[_DenyObject])(
            factory.put("/", {"name": "new", "bio": "b"}, format="json"), pk=author.pk
        )
        assert response.status_code == 403
        assert asked == [author]
        assert lookups == [author.pk]
        author.refresh_from_db()
        assert author.name == "orig"

    @pytest.mark.parametrize(("allowed", "status"), [(False, 403), (True, 409)])
    def test_the_view_s_object_permission_answers_before_an_affordance(
        self, allowed: bool, status: int
    ) -> None:
        """A caller the view denies the row is refused before an affordance
        answers for it, so it learns nothing of the row's state; one the view
        allows meets the affordance's ``409``."""

        class _Object(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return allowed

        spec = ServiceSpec(
            service=lambda *, instance: None,
            permissions=_OPEN,
            instance_selector_spec=_AUTHOR,
            affordances=(Affordance(code="locked", reason="Locked.", when=Q(name="open")),),
        )
        author = Author.objects.create(name="orig")
        response = _view(spec, permission_classes=[_Object])(
            factory.put("/", {}, format="json"), pk=author.pk
        )
        assert response.status_code == status

    def test_a_row_the_view_resolved_is_looked_up_once(self) -> None:
        """A caller handing the row it resolved is trusted with it: the spec's
        lookup does not run again."""
        author = Author.objects.create(name="orig")

        class _Update(APIView):
            def put(self, request: Any, **kwargs: Any) -> Response:
                return dispatch_mutation_for_spec(
                    self,
                    request,
                    _UPDATE,
                    instance=author,
                    default_status=200,
                    render_instance_on_none=True,
                )

        response = _Update.as_view()(
            factory.put("/", {"name": "new", "bio": "b"}, format="json"), pk=author.pk
        )
        assert response.status_code == 200
        assert lookups == []

    @pytest.mark.parametrize("base", [ServiceUpdateView, ServiceDeleteView])
    def test_a_detail_view_s_kernel_spec_with_no_target_selector_is_refused_at_as_view(
        self, base: type
    ) -> None:
        """Changed by design: a drfs update or delete scoped its call with the
        view's ``get_object()``, which a kernel spec never asks, so a spec
        naming no target would run on no row. It is refused when the view is
        built, before ``check_seeds`` answers anything of it."""

        class _View(base):
            queryset = Author.objects.all()
            spec = ServiceSpec(service=lambda: None, permissions=_OPEN)

        with pytest.raises(ImproperlyConfigured) as refused:
            _View.as_view()
        message = str(refused.value)
        assert message.startswith("_View.spec declares no target selector")
        assert "instance_selector_spec" in message
        assert "which nothing fills" not in message

    def test_a_kernel_spec_with_no_target_selector_is_handed_no_row(self) -> None:
        """Where nothing refused the spec when the view was built, the view's
        ``get_object()`` is still never asked: the kernel would refuse the row
        it found as a ``target=`` to a spec declaring no target selector."""

        class _View:
            def get_object(self) -> Any:
                raise AssertionError("get_object() is not asked for a kernel spec")

        spec = ServiceSpec(service=lambda: None, permissions=_OPEN)
        assert utils.resolve_mutation_instance(_View(), spec) is None


class TestWhatAnUpdatePresents:
    def test_a_service_s_own_row_outranks_its_target(self) -> None:
        author = Author.objects.create(name="orig")
        other = Author.objects.create(name="other")
        spec = ServiceSpec(
            service=lambda *, instance: other,
            permissions=_OPEN,
            instance_selector_spec=_AUTHOR,
            presenter=_PRESENTER,
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.data == {"id": other.pk, "name": "other"}

    def test_falls_back_to_the_target_when_the_service_returns_none(self) -> None:
        """An update in place presents its target, as DRF's ``UpdateAPIView``."""

        def touch(*, instance: Author) -> None:
            instance.name = "touched"
            instance.save(update_fields=["name"])

        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=touch, permissions=_OPEN, instance_selector_spec=_AUTHOR, presenter=_PRESENTER
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "touched"}

    def test_an_update_with_no_presenter_returning_nothing_answers_204(self) -> None:
        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=lambda *, instance: None, permissions=_OPEN, instance_selector_spec=_AUTHOR
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 204
        assert response.data is None

    def test_an_output_selector_s_none_is_its_own(self) -> None:
        """A re-read finding nothing is an answer of no content, never its target."""
        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=lambda *, instance: instance,
            permissions=_OPEN,
            instance_selector_spec=_AUTHOR,
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: None,
                permissions=_OPEN,
                allow_none=True,
                presenter=_PRESENTER,
            ),
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 204
        assert response.data is None

    def test_an_output_selector_s_none_is_its_own_beside_the_spec_s_presenter(self) -> None:
        """With the presenter on the service spec rather than the re-read, a
        re-read finding nothing is still no content: the target is presented
        in place of a ``None`` only where no re-read owns it."""
        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=lambda *, instance: None,
            permissions=_OPEN,
            instance_selector_spec=_AUTHOR,
            presenter=_PRESENTER,
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: None,
                permissions=_OPEN,
                allow_none=True,
            ),
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 204
        assert response.data is None

    def test_an_output_selector_s_re_read_is_presented(self) -> None:
        author = Author.objects.create(name="orig")
        spec = ServiceSpec(
            service=_rename,
            permissions=_OPEN,
            validator=SerializerValidator(_NameBio),
            instance_selector_spec=_AUTHOR,
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: Author.objects.get(pk=result.pk),
                permissions=_OPEN,
                presenter=_PRESENTER,
            ),
        )
        response = _view(spec)(factory.patch("/", {"name": "new"}, format="json"), pk=author.pk)
        assert response.data == {"id": author.pk, "name": "new"}

    def test_renders_fresh_related_data_after_the_service_mutates_a_relation(self) -> None:
        """A target resolved with ``posts`` prefetched, then a row added through
        the ``Post`` manager, which Django does not self-invalidate: presenting
        the target in place reads the relation as it now is."""
        author = Author.objects.create(name="Ada")
        Post.objects.create(title="old", author=author)

        class _AuthorPosts(serializers.ModelSerializer):
            post_titles = serializers.SerializerMethodField()

            class Meta:
                model = Author
                fields = ("id", "post_titles")

            def get_post_titles(self, obj: Author) -> list[str]:
                return sorted(p.title for p in obj.posts.all())

        spec = ServiceSpec(
            service=lambda *, instance: Post.objects.create(title="new", author=instance) and None,
            permissions=_OPEN,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Author.objects.filter(pk=pk),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                prefetch_related=("posts",),
                permissions=_OPEN,
            ),
            presenter=SerializerPresenter(_AuthorPosts),
            atomic=False,
        )
        response = _view(spec)(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 200
        assert response.data["post_titles"] == ["new", "old"]


def test_a_principal_reaches_the_lookup_s_permission_check() -> None:
    """The spec's own permissions are the kernel's, asked of the row its lookup
    found; a refusal there is DRF's 403."""

    class _OwnerOnly(PermissionCheck):
        def has_permission(self, principal: Any, spec: Any) -> bool:
            return True

        def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
            return target.name == principal.username

    user = User.objects.create(username="ada")
    author = Author.objects.create(name="grace")
    spec = ServiceSpec(
        service=lambda *, instance: None,
        permissions=(_OwnerOnly(),),
        instance_selector_spec=_AUTHOR,
    )
    request = factory.put("/", {}, format="json")
    force_authenticate(request, user=user)
    assert _view(spec)(request, pk=author.pk).status_code == 403
