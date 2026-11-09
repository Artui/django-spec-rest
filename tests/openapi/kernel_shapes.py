"""Views carrying every shape the kernel writes that OpenAPI 3.0 spells otherwise.

The kernel's schemas are JSON Schema: a nullable field is ``{"type": [t,
"null"]}``, a labelled parameter choice an ``anyOf`` of ``{"const", "title"}``
(with ``{"type": "null"}`` for a null), and a labelled output choice a ``oneOf``
of the same (with ``{"const": None}``). The test app of ``test_service_auto_schema``
declares none of them, so these routes put each one in the document, in a
request body, a response body, a route capture, a ``FilterSet``'s query
parameter and a ``DiscriminatedAction``'s registered request component, for
``test_the_document_validates``. ``test_labelled_parameters`` builds its own.
"""

from __future__ import annotations

from typing import Any

import django_filters
from django.db import models
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
from rest_framework.pagination import PageNumberPagination

from django_spec_rest import (
    DiscriminatedAction,
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceViewSet,
)
from tests.testapp.models import Post

_OPEN = (Unrestricted(),)
LABELS = {"a": "A", "b": "B"}
LABELLED = {"choices": ["a", "b"], "choice_labels": LABELS}
DISPLAYED = (("a", "A"), ("b", "B"))
RESTATED = (("x", "x"), ("y", "y"))


class Closed(models.TextChoices):
    """A choice with an empty member, on a field that is not nullable."""

    A = "a", "A"
    B = "b", "B"
    __empty__ = "Nothing"


class Notes(Presenter):
    """A presenter that is no serializer: its response is the kernel's ``output_schema``."""

    def output(self) -> Output:
        return Output(
            (
                OutputField("maybe", "string", nullable=True),
                OutputField("kind", "string", choices=DISPLAYED),
                OutputField("maybe_kind", "string", choices=DISPLAYED, nullable=True),
                # A null choice on a field that is not nullable: the kernel's
                # ``oneOf`` lists a ``{"const": None}`` beside a ``type`` that refuses it.
                OutputField("closed", "string", choices=Closed.choices),
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
            Parameter(
                "closed", "string", choices=Closed.values, choice_labels=dict(Closed.choices)
            ),
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
    """Real filters, read by the kernel's ``filter_set_parameters``.

    The kernel at this package's floor writes a ``ChoiceFilter``'s choices
    without their labels, so these are an ``enum`` under 3.0 whatever the
    lowering does; ``test_labelled_parameters`` feeds the labelled shape.
    """

    kind = django_filters.ChoiceFilter(choices=DISPLAYED)
    several = django_filters.MultipleChoiceFilter(choices=DISPLAYED)
    o = django_filters.OrderingFilter(fields=("title", "id"))

    class Meta:
        model = Post
        fields: list[str] = []


def _noop(**fields: Any) -> Any: ...


def _notes() -> Any:
    return []


def _one_note(**fields: Any) -> Any:
    return None


class Picks(Validator):
    """A body of one labelled field that admits null."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("kind", "string", nullable=True, **LABELLED))

    def validate(self, arguments: Any, context: Any) -> dict[str, Any]:
        return dict(arguments)


class Remarks(Validator):
    """A body of another field, so the two variants' bodies differ."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("note", "string"))

    def validate(self, arguments: Any, context: Any) -> dict[str, Any]:
        return dict(arguments)


def _pick(**fields: Any) -> str:
    return "picks"


class Chosen(ServiceViewSet):
    """A ``create`` choosing between two specs, one taking a labelled, nullable field.

    The request is the registered component ``Chosen_create_Request``, where
    drf-spectacular's enum hook reads a field it finds in it.
    """

    action_specs = {
        "create": DiscriminatedAction(
            _pick,
            {
                "picks": ServiceSpec(
                    service=_noop, permissions=_OPEN, validator=Picks(), presenter=Notes()
                ),
                "notes": ServiceSpec(
                    service=_noop, permissions=_OPEN, validator=Remarks(), presenter=Notes()
                ),
            },
        )
    }


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
        "shapes/paged/",
        _view(
            SelectorListView,
            SelectorSpec(
                kind=SelectorKind.LIST, selector=_notes, permissions=_OPEN, presenter=Notes()
            ),
            pagination_class=PageNumberPagination,
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
    path("shapes/chosen/", Chosen.as_view({"post": "create"})),
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
