"""A view's own checks of a kernel spec, and the checks the kernel holds instead.

``as_view()`` asks a kernel spec what only the view can know (the ``filter_set``
guard here, the kind and the seeds in ``test_spec_validation_e2e``). Every other
check of a spec's fields is the kernel's when the spec is built:
those are asserted below in the kernel's words, so a spec refused there never
reaches a view.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework import serializers

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.views.spec_validation import (
    _uses_django_filter_backend,
    is_overridden,
    validate_filter_set_no_backend_conflict,
)
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)


class DjangoFilterBackend:
    """A no-op stand-in for django-filter's backend.

    The guard detects the real backend by class name (django-filter is an
    optional dependency this package never imports), so a same-named stub is
    all the tests need.
    """

    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset


class _SubclassedFilterBackend(DjangoFilterBackend):
    """A project subclass of the backend; the MRO name-walk must catch it."""


class _UnrelatedBackend:
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset


class _ByName(django_filters.FilterSet):
    """A real ``FilterSet``: the kernel refuses an object only shaped like one."""

    class Meta:
        model = Author
        fields = ["name"]


def _rows(**_: Any) -> Any:
    return Author.objects.all()


def _spec(kind: SelectorKind = SelectorKind.LIST, **fields: Any) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=_rows, permissions=_OPEN, **fields)


class TestIsOverridden:
    def test_returns_false_when_method_is_inherited(self) -> None:
        class Base:
            def hook(self) -> int:
                return 0

        class Sub(Base): ...

        assert is_overridden(Sub, Base, "hook") is False

    def test_returns_true_when_subclass_overrides(self) -> None:
        class Base:
            def hook(self) -> int:
                return 0

        class Sub(Base):
            def hook(self) -> int:
                return 1

        assert is_overridden(Sub, Base, "hook") is True

    def test_missing_on_base_falls_back_to_hasattr(self) -> None:
        class Base: ...

        class WithHook(Base):
            def hook(self) -> int:
                return 1

        class WithoutHook(Base): ...

        assert is_overridden(WithHook, Base, "hook") is True
        assert is_overridden(WithoutHook, Base, "hook") is False


class TestUsesDjangoFilterBackend:
    @pytest.mark.parametrize(
        ("attrs", "expected"),
        [
            ({}, False),
            ({"filter_backends": []}, False),
            ({"filter_backends": [DjangoFilterBackend]}, True),
            ({"filter_backends": [_SubclassedFilterBackend]}, True),
            ({"filter_backends": [_UnrelatedBackend]}, False),
        ],
        ids=["no-backends", "empty", "the-backend", "a-subclass", "unrelated"],
    )
    def test_it_matches_the_backend_by_name(self, attrs: dict[str, Any], expected: bool) -> None:
        assert _uses_django_filter_backend(type("V", (), attrs)) is expected


class TestValidateFilterSetNoBackendConflict:
    def test_silent_when_no_filter_set(self) -> None:
        view = type("V", (), {"filter_backends": [DjangoFilterBackend]})
        validate_filter_set_no_backend_conflict(view, _spec(), label="X")

    def test_silent_when_no_backend(self) -> None:
        view = type("V", (), {"filter_backends": []})
        validate_filter_set_no_backend_conflict(view, _spec(filter_set=_ByName), label="X")

    def test_raises_on_conflict(self) -> None:
        view = type("V", (), {"filter_backends": [DjangoFilterBackend]})
        with pytest.raises(ImproperlyConfigured, match="X: spec.filter_set is set"):
            validate_filter_set_no_backend_conflict(view, _spec(filter_set=_ByName), label="X")


class TestTheFilterSetGuardAtAsView:
    def test_a_list_view_refuses_the_conflict(self) -> None:
        view = type(
            "_View",
            (SelectorListView,),
            {"filter_backends": [DjangoFilterBackend], "spec": _spec(filter_set=_ByName)},
        )

        with pytest.raises(ImproperlyConfigured, match="_View.spec: spec.filter_set is set"):
            view.as_view()

    @pytest.mark.parametrize(
        "attrs",
        [
            {"filter_backends": [], "spec": _spec(filter_set=_ByName)},
            {"filter_backends": [DjangoFilterBackend], "spec": _spec()},
        ],
        ids=["no-backend", "no-filter-set"],
    )
    def test_a_list_view_passes_either_alone(self, attrs: dict[str, Any]) -> None:
        assert callable(type("_View", (SelectorListView,), attrs).as_view())

    def test_a_retrieve_view_is_not_asked(self) -> None:
        """A retrieve overrides ``get_object()`` and never calls
        ``filter_queryset``, so the two never both apply there."""
        attrs = {
            "filter_backends": [DjangoFilterBackend],
            "spec": _spec(SelectorKind.RETRIEVE, filter_set=_ByName),
        }

        assert callable(type("_View", (SelectorRetrieveView,), attrs).as_view())


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


def _nested(kind: SelectorKind = SelectorKind.RETRIEVE, **fields: Any) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=_rows, **fields)


class TestTheKernelRefusesWhenTheSpecIsBuilt:
    """A kernel spec is refused when it is built, so no view is ever handed one."""

    @pytest.mark.parametrize("role", ["instance", "output"])
    def test_a_nested_selector_s_preconditions(self, role: str) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=rf"ServiceSpec\.{role}_selector_spec declares preconditions, which are "
            "never run on a nested selector",
        ):
            ServiceSpec(
                service=_rows,
                permissions=_OPEN,
                **{f"{role}_selector_spec": _nested(preconditions=[lambda: None])},
            )

    def test_a_collection_selector_s_preconditions(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=r"ServiceSpec\.collection_selector_spec declares preconditions",
        ):
            ServiceSpec(
                service=_rows,
                permissions=_OPEN,
                collection_selector_spec=_nested(SelectorKind.LIST, preconditions=[lambda: None]),
            )

    def test_an_instance_selector_of_the_list_kind(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=r"ServiceSpec\.instance_selector_spec is a LIST; it must be a RETRIEVE",
        ):
            ServiceSpec(
                service=_rows,
                permissions=_OPEN,
                instance_selector_spec=_nested(SelectorKind.LIST),
            )

    def test_a_selector_spec_with_no_selector(self) -> None:
        """A kernel spec is an operation, and an operation has a callable."""
        with pytest.raises(
            ImproperlyConfigured, match=r"SelectorSpec\.selector must be callable; got NoneType"
        ):
            SelectorSpec(kind=SelectorKind.LIST, selector=None, permissions=_OPEN)

    @pytest.mark.parametrize(
        ("preconditions", "message"),
        [
            (lambda: None, r"takes a sequence of callables; got function\. Wrap a single one"),
            ("nope", r"takes a sequence of callables; got str"),
        ],
        ids=["a-bare-callable", "a-string"],
    )
    def test_preconditions_that_are_no_sequence_of_callables(
        self, preconditions: Any, message: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match=rf"ServiceSpec\.preconditions {message}"):
            ServiceSpec(service=_rows, permissions=_OPEN, preconditions=preconditions)

    def test_a_serializer_class_where_a_validator_goes(self) -> None:
        """The kernel takes a Validator instance, and a DRF serializer is wrapped in
        ``SerializerValidator``."""
        with pytest.raises(
            ImproperlyConfigured,
            match=r"ServiceSpec\.validator is the class _TitleIn, which is not a Validator "
            "instance",
        ):
            ServiceSpec(service=_rows, permissions=_OPEN, validator=_TitleIn)
