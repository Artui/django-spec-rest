"""``PermissionDeniedSerializer`` and ``NotAuthenticatedSerializer``: the package's 403 and 401 bodies, for a project to declare.

The reserved-components hook refuses a ``$ref`` to ``PermissionDenied`` or
``NotAuthenticated`` the package did not write. A project's view declaring the
package's own body writes no such ``$ref`` itself: drf-spectacular resolves it
from the class, on drf-spectacular's own ``AutoSchema`` as on the package's,
so it is documented beside the package's views in either order. A project's
serializer of the same name stays refused, and so does a raw ``$ref`` (both
``test_reserved_names_on_any_view`` and ``test_reserved_components_hook``).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, path
from django_service_specs import SelectorKind, SelectorSpec
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.settings import patched_settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest import SelectorListView
from django_spec_rest.openapi import (
    NotAuthenticatedSerializer,
    PermissionDeniedSerializer,
    enable_openapi,
)
from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.openapi.reserved_names import (
    NotAuthenticatedSerializer as TheirNotAuthenticated,
)
from tests.openapi.reserved_names import (
    PermissionDeniedSerializer as TheirPermissionDenied,
)
from tests.openapi.reserved_names import _Deny, ours, ours_refusing_nothing, theirs
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

_BODIES = {403: PermissionDeniedSerializer, 401: NotAuthenticatedSerializer}
_COMPONENTS = {403: "PermissionDenied", 401: "NotAuthenticated"}


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


def _declaring(prefix: str, responses: Any, request: Any = None) -> URLPattern:
    """A project's own view on drf-spectacular's ``AutoSchema``, declaring ``responses``.

    Declared on the class, so ``extend_schema`` subclasses the view's own
    ``AutoSchema``; on the method it would subclass ``DEFAULT_SCHEMA_CLASS``,
    which is the package's in this suite.
    """

    class _Declaring(GenericAPIView):
        schema = AutoSchema()
        permission_classes = []
        authentication_classes = []

        def post(self, request: Request) -> Response: ...

    view = extend_schema(request=request, responses=responses)(_Declaring)
    assert not isinstance(view.schema, ServiceAutoSchema)
    return path(f"{prefix}/", view.as_view())


def _checked_list(prefix: str) -> URLPattern:
    """A paginated list whose spec carries a DRF check, so it documents the package's 403."""
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.all(),
        permissions=(DRFPermissionCheck([_Deny]),),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    attrs = {
        "queryset": Author.objects.all(),
        "spec": spec,
        "pagination_class": PageNumberPagination,
        "permission_classes": [],
        "authentication_classes": [],
    }
    return path(f"{prefix}/", type("_Listing", (SelectorListView,), attrs).as_view())


def _paginated_listing_a_refusal(prefix: str) -> URLPattern:
    """A project's paginated list view whose 2xx body is the package's 403 body."""

    class _Listing(ListAPIView):
        schema = AutoSchema()
        queryset = Author.objects.all()
        serializer_class = PermissionDeniedSerializer
        pagination_class = PageNumberPagination
        permission_classes = []
        authentication_classes = []

    return path(f"{prefix}/", _Listing.as_view())


def _refusals(schema: dict[str, Any], route: str) -> dict[int, Any]:
    responses = schema["paths"][route]["post"]["responses"]
    return {code: responses[str(code)]["content"]["application/json"]["schema"] for code in _BODIES}


class TestTheExportedBodies:
    @pytest.mark.parametrize(
        "order", ["package first", "project first"], ids=lambda order: order.replace(" ", "-")
    )
    def test_are_documented_on_drf_spectacular_s_schema_beside_a_package_view(
        self, order: str
    ) -> None:
        """Generates, and the project's 403 and 401 are the package's components.

        Fails without the body classes' placement: the hook refuses the
        project's ``$ref`` as a name the package reserves.
        """
        package, project = ours("ours"), _declaring("declaring", _BODIES)
        schema = _generate(
            *((package, project) if order == "package first" else (project, package))
        )
        refs = {
            code: {"$ref": f"#/components/schemas/{name}"} for code, name in _COMPONENTS.items()
        }
        assert _refusals(schema, "/declaring/") == refs
        assert _refusals(schema, "/ours/") == refs
        for name in _COMPONENTS.values():
            assert schema["components"]["schemas"][name]["properties"] == {
                "detail": {"type": "string"}
            }

    def test_are_documented_where_no_package_view_documents_them(self) -> None:
        schema = _generate(ours_refusing_nothing("ours"), _declaring("declaring", _BODIES))
        assert set(_COMPONENTS.values()) <= set(schema["components"]["schemas"])

    def test_are_documented_nested_in_a_project_s_serializer(self) -> None:
        """A field of the package's body passes too, through drf-spectacular's copy of its ``$ref``."""

        class RefusalHolderSerializer(serializers.Serializer):
            refusal = PermissionDeniedSerializer(read_only=True)

        schema = _generate(ours("a-ours"), theirs("b-theirs", RefusalHolderSerializer))
        field = schema["components"]["schemas"]["RefusalHolder"]["properties"]["refusal"]
        assert "#/components/schemas/PermissionDenied" in str(field)

    @pytest.mark.parametrize(
        ("split", "name"), [(False, "PermissionDenied"), (True, "PermissionDeniedRequest")]
    )
    def test_is_documented_as_a_request_body(self, split: bool, name: str) -> None:
        """As the request too, and under drf-spectacular's own request twin where it splits them.

        ``PermissionDeniedRequest`` is no name the package keeps, so the
        package registers nothing under its reserved name where the body is
        only a request: fails if the request twin registers ``PermissionDenied``.
        """
        with patched_settings({"COMPONENT_SPLIT_REQUEST": split}):
            schema = _generate(
                ours_refusing_nothing("a-ours"),
                _declaring("b-declaring", {204: None}, request=PermissionDeniedSerializer),
            )
        body = schema["paths"]["/b-declaring/"]["post"]["requestBody"]["content"]
        assert body["application/json"]["schema"] == {"$ref": f"#/components/schemas/{name}"}
        reserved = {"PermissionDenied", "PermissionDeniedRequest"}
        assert reserved & set(schema["components"]["schemas"]) == {name}

    @pytest.mark.parametrize(
        ("code", "their"), [(403, TheirPermissionDenied), (401, TheirNotAuthenticated)]
    )
    def test_a_project_s_serializer_of_the_name_first_is_refused(
        self, code: int, their: type[serializers.Serializer]
    ) -> None:
        """The registry holds the project's class when the package's body is resolved, on any schema.

        Fails if the package's body is answered the project's component: the
        hook asks nothing of a name the package holds nothing under.
        """
        named = f"{their.__module__}.{their.__qualname__}"
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(theirs("a-theirs", their), _declaring("b-declaring", {code: _BODIES[code]}))
        assert str(raised.value).startswith(
            f"{named} is documented as the component {_COMPONENTS[code]!r}"
        )

    def test_a_project_s_serializer_of_the_name_after_is_refused(self) -> None:
        """The package's body first, on a project's view, then a project's class of its name.

        Fails if every ``$ref`` the package's component hands out is taken for
        the package's, rather than only those resolved from its class.
        """
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(
                _declaring("a-declaring", {403: PermissionDeniedSerializer}),
                theirs("b-theirs", TheirPermissionDenied),
            )
        assert str(raised.value).startswith(
            "The operation POST /b-theirs/ is documented as the component 'PermissionDenied'"
        )

    def test_are_documented_under_split_request_components(self) -> None:
        """The package's own view documents its 403 as the one component where requests split.

        Fails if the extension steps aside for every direction under
        ``COMPONENT_SPLIT_REQUEST``, not only the request one: the 403, a
        response, would then be named by drf-spectacular's own serializer
        reading, not the reserved component.
        """
        with patched_settings({"COMPONENT_SPLIT_REQUEST": True}):
            schema = _generate(ours("a-ours"))
        assert _refusals(schema, "/a-ours/")[403] == {
            "$ref": "#/components/schemas/PermissionDenied"
        }

    def test_are_documented_as_a_project_s_response_under_split_request_components(self) -> None:
        """A project's view declaring the body as its 403 gets the one component too.

        Fails for the same mutant as the package's own view, on a schema that
        is drf-spectacular's own.
        """
        with patched_settings({"COMPONENT_SPLIT_REQUEST": True}):
            schema = _generate(_declaring("a-declaring", {403: PermissionDeniedSerializer}))
        responses = schema["paths"]["/a-declaring/"]["post"]["responses"]
        assert responses["403"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/PermissionDenied"
        }

    def test_a_project_s_serializer_of_the_name_after_a_paginated_list_of_it_is_refused(
        self,
    ) -> None:
        """The body as the 2xx of a paginated list view, then a project's class of its name.

        Fails without the body declaring it is never a list: the pagination
        naming asks the extension for the name and leaves the component armed,
        so the project's class, resolved next, is taken for the package's.
        """
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(
                _paginated_listing_a_refusal("a-listing"),
                _declaring("b-declaring", {200: TheirPermissionDenied}),
            )
        assert str(raised.value).startswith(
            "The operation POST /b-declaring/ is documented as the component 'PermissionDenied'"
        )


class TestUnderListMechanicsOnARefusal:
    """``ENABLE_LIST_MECHANICS_ON_NON_2XX`` wraps a list view's non-2xx bodies as lists and pages them."""

    def _generate(self, *patterns: URLPattern) -> dict[str, Any]:
        with patched_settings({"ENABLE_LIST_MECHANICS_ON_NON_2XX": True}):
            return _generate(*patterns)

    def test_the_403_of_a_checked_list_is_the_one_refusal(self) -> None:
        """Fails without the bodies declaring they are never a list: the 403 is
        ``PaginatedPermissionDeniedList``, an array of them."""
        schema = self._generate(_checked_list("a-list"))
        body = schema["paths"]["/a-list/"]["get"]["responses"]["403"]["content"]
        assert body["application/json"]["schema"] == {
            "$ref": "#/components/schemas/PermissionDenied"
        }

    def test_a_project_s_serializer_of_the_name_after_is_refused(self) -> None:
        """Fails if paging the body arms the component for the next ``$ref`` taken.

        The pagination naming asks the extension for the name and takes no
        ``$ref`` of it, so the project's class of the name, resolved next,
        would be taken for the package's.
        """
        with pytest.raises(ImproperlyConfigured) as raised:
            self._generate(
                _checked_list("a-list"), _declaring("b-declaring", {200: TheirPermissionDenied})
            )
        assert str(raised.value).startswith(
            "The operation POST /b-declaring/ is documented as the component 'PermissionDenied'"
        )
