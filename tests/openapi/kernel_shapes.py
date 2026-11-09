"""Views carrying every shape the kernel writes that OpenAPI 3.0 spells otherwise.

The kernel's schemas are JSON Schema: a nullable field is ``{"type": [t,
"null"]}``, a labelled parameter choice an ``anyOf`` of ``{"const", "title"}``
(with ``{"type": "null"}`` for a null), and a labelled output choice a ``oneOf``
of the same (with ``{"const": None}``). The test app of ``test_service_auto_schema``
declares none of them, so these routes put each one in the document, in a
request body, a response body and a route capture, for ``test_the_document_validates``
and ``test_lowered_for_the_document``.
"""

from __future__ import annotations

from typing import Any

import django_filters
from django.urls import path
from django_service_specs import (
    Output,
    OutputField,
    Parameter,
    Parameters,
    Presenter,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    Validator,
)

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from tests.testapp.models import Post

_OPEN = (Unrestricted(),)
LABELS = {"a": "A", "b": "B"}
LABELLED = {"choices": ["a", "b"], "choice_labels": LABELS}
DISPLAYED = (("a", "A"), ("b", "B"))
RESTATED = (("x", "x"), ("y", "y"))


class Notes(Presenter):
    """A presenter that is no serializer: its response is the kernel's ``output_schema``."""

    def output(self) -> Output:
        return Output(
            (
                OutputField("maybe", "string", nullable=True),
                OutputField("kind", "string", choices=DISPLAYED),
                OutputField("maybe_kind", "string", choices=DISPLAYED, nullable=True),
                OutputField("plain", "string", choices=RESTATED, nullable=True),
                OutputField(
                    "tags", "array", items="string", choices=DISPLAYED, items_nullable=True
                ),
                OutputField("scores", "array", items="integer", nullable=True),
                OutputField(
                    "nested",
                    "object",
                    fields=Output(
                        (
                            OutputField("maybe", "string", nullable=True),
                            OutputField("kind", "string", choices=DISPLAYED),
                        )
                    ),
                    nullable=True,
                ),
            )
        )

    def present(self, value: Any) -> Any:
        return value


class Filters(Validator):
    """A Validator that is no serializer: its request body is the kernel's caller schema."""

    def parameters(self) -> Parameters:
        return Parameters.of(
            Parameter("maybe", "string", nullable=True),
            Parameter("kind", "string", **LABELLED),
            Parameter("maybe_kind", "string", nullable=True, **LABELLED),
            Parameter("plain", "string", choices=["x", "y"], nullable=True),
            Parameter("tags", "array", items="string", items_nullable=True, **LABELLED),
            Parameter(
                "rows",
                "array",
                items=Parameters.of(
                    Parameter("maybe", "string", nullable=True),
                    Parameter("kind", "string", **LABELLED),
                ),
            ),
            Parameter(
                "nested",
                "object",
                fields=Parameters.of(Parameter("maybe_kind", "string", nullable=True, **LABELLED)),
            ),
        )

    def validate(self, arguments: Any, context: Any) -> dict[str, Any]:
        return dict(arguments)


class PostFilter(django_filters.FilterSet):
    class Meta:
        model = Post
        fields: list[str] = []


# What a FilterSet's parameters read as once the kernel labels a choice filter and
# a filter allows null; the kernel's floor states neither, so the document test
# feeds ``filter_set_parameters`` these.
FILTER_PARAMETERS = Parameters.of(
    Parameter("maybe", "string", nullable=True),
    Parameter("kind", "string", **LABELLED),
    Parameter("maybe_kind", "string", nullable=True, **LABELLED),
    Parameter("o", "array", items="string", **LABELLED),
)


def _noop(**fields: Any) -> Any: ...


def _notes() -> Any:
    return []


def _one_note(**fields: Any) -> Any:
    return None


def _view(base: type, spec: Any, **attrs: Any) -> Any:
    return type("_View", (base,), {"spec": spec, **attrs})


_CAPTURED = Parameters.of(
    Parameter("kind", "string", required=True, nullable=True, **LABELLED),
)

urlpatterns = [
    path(
        "shapes/write/",
        _view(
            ServiceCreateView,
            ServiceSpec(service=_noop, permissions=_OPEN, validator=Filters(), presenter=Notes()),
        ).as_view(),
    ),
    path(
        "shapes/write-many/",
        _view(
            ServiceCreateView,
            ServiceSpec(
                service=_noop,
                permissions=_OPEN,
                validator=Filters(),
                presenter=Notes(),
                many=True,
            ),
        ).as_view(),
    ),
    path(
        "shapes/read/",
        _view(
            SelectorListView,
            SelectorSpec(
                kind=SelectorKind.LIST, selector=_notes, permissions=_OPEN, presenter=Notes()
            ),
        ).as_view(),
    ),
    path(
        "shapes/filtered/",
        _view(
            SelectorListView,
            SelectorSpec(
                kind=SelectorKind.LIST,
                selector=_notes,
                permissions=_OPEN,
                presenter=Notes(),
                filter_set=PostFilter,
            ),
            queryset=Post.objects.all(),
        ).as_view(),
    ),
    path(
        "shapes/by/<kind>/",
        _view(
            SelectorRetrieveView,
            SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=_one_note,
                reads=_CAPTURED,
                permissions=_OPEN,
                presenter=Notes(),
            ),
        ).as_view(),
    ),
]
