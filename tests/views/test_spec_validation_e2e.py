"""What ``as_view()`` refuses for a kernel spec set on a view's ``spec``.

A view builds no spec, so it refuses three things only it can know - a spec of
the kind of operation it does not serve, a selector spec of the other
``SelectorKind``, and (in ``test_spec_validation``) a ``filter_set`` beside
DRF's own filter backend - and hands the rest to the kernel's ``check_seeds``,
which refuses a declaration that cannot hold on a mount as written: a keyword
nothing fills, a positional-only parameter, an optional read over a keyword
that requires it, a parameter a seed occupies. The view dispatches with the
kernel's default seeds and no overlay of its own, so ``check_seeds`` sees every
keyword the call can fill. Every refusal here is asserted in the kernel's own
words, so a change of wording there is seen here.

Where drfs answered differently, by design, the test says so: the view's
``get_*_kwargs`` hooks never reach a kernel spec, only the spec's own providers
do, and the kernel hands every service ``data``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
)
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

_OPEN = (Unrestricted(),)

_NOTHING_FILLS = r"requires the keyword\(s\) \['{name}'\], which nothing fills"


def _nothing_fills(name: str, *, seat: str = "ServiceSpec.service") -> str:
    return rf"{seat} " + _NOTHING_FILLS.format(name=name)


def _build(base: type, spec: ServiceSpec | SelectorSpec) -> Any:
    return type("_View", (base,), {"spec": spec}).as_view()


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _FillsTenant(TypedDict):
    tenant: str


def _typed_tenant() -> _FillsTenant:
    return {"tenant": "acme"}


def _reads(*parameters: Parameter) -> Parameters:
    return Parameters(parameters)


def _row(**_: Any) -> None:
    return None


class TestAMutationView:
    def test_a_keyword_nothing_fills_is_refused(self) -> None:
        def service(*, tenant: str) -> None: ...

        spec = ServiceSpec(service=service, permissions=_OPEN)

        with pytest.raises(ImproperlyConfigured, match=_nothing_fills("tenant")):
            _build(ServiceCreateView, spec)

    def test_instance_on_a_create_is_refused(self) -> None:
        """A create has no target selector, so nothing hands the service a row."""

        def service(*, instance: Any) -> None: ...

        spec = ServiceSpec(service=service, permissions=_OPEN)

        with pytest.raises(ImproperlyConfigured, match=_nothing_fills("instance")):
            _build(ServiceCreateView, spec)

    def test_result_is_refused_too(self) -> None:
        """``result`` is an output selector's, never a service's."""

        def service(*, result: Any) -> None: ...

        with pytest.raises(ImproperlyConfigured, match=_nothing_fills("result")):
            _build(ServiceCreateView, ServiceSpec(service=service, permissions=_OPEN))

    @pytest.mark.parametrize("base", [ServiceUpdateView, ServiceDeleteView])
    def test_instance_beside_its_target_selector_passes(self, base: type) -> None:
        def service(*, instance: Any) -> None: ...

        spec = ServiceSpec(
            service=service,
            permissions=_OPEN,
            instance_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_row),
        )

        assert callable(_build(base, spec))

    def test_a_target_selector_s_keyword_nothing_fills_is_refused(self) -> None:
        def selector(*, tenant: str) -> None: ...

        def service(*, instance: Any) -> None: ...

        spec = ServiceSpec(
            service=service,
            permissions=_OPEN,
            instance_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector),
        )

        with pytest.raises(
            ImproperlyConfigured,
            match=_nothing_fills("tenant", seat=r"ServiceSpec\.instance_selector_spec\.selector"),
        ):
            _build(ServiceDeleteView, spec)

    def test_a_typed_provider_fills_the_keyword(self) -> None:
        def service(*, tenant: str) -> None: ...

        spec = ServiceSpec(service=service, permissions=_OPEN, kwargs=_typed_tenant)

        assert callable(_build(ServiceCreateView, spec))

    def test_an_untyped_provider_may_fill_any_keyword(self) -> None:
        """A provider whose return names no keys is left to dispatch."""

        def service(*, tenant: str) -> None: ...

        spec = ServiceSpec(service=service, permissions=_OPEN, kwargs=lambda: {"tenant": "x"})

        assert callable(_build(ServiceCreateView, spec))

    def test_a_view_hook_fills_nothing_for_a_kernel_spec(self) -> None:
        """Changed by design: drfs passed this, reading an overridden
        ``get_service_kwargs`` as a source of keys it could not see. A kernel
        spec's call is handed its own providers' values and never a view
        hook's, so the keyword is unfilled on every call and refused here."""

        def service(*, tenant: str) -> None: ...

        class _View(ServiceCreateView):
            spec = ServiceSpec(service=service, permissions=_OPEN)

            def get_service_kwargs(self) -> dict[str, Any]:
                return {"tenant": "acme"}

        with pytest.raises(ImproperlyConfigured, match=_nothing_fills("tenant")):
            _View.as_view()

    def test_a_service_beside_a_validator_is_left_to_dispatch(self) -> None:
        """A Validator may hand the service a value it does not declare."""

        def service(*, tenant: str, data: Any) -> None: ...

        spec = ServiceSpec(
            service=service, permissions=_OPEN, validator=SerializerValidator(_TitleIn)
        )

        assert callable(_build(ServiceCreateView, spec))

    def test_data_is_handed_to_every_service(self) -> None:
        """Changed by design: drfs refused ``data`` on a spec with no
        ``input_serializer``. The kernel hands every service ``data``, the
        caller's checked arguments, Validator or not."""

        def service(*, data: Any) -> None: ...

        assert callable(_build(ServiceCreateView, ServiceSpec(service=service, permissions=_OPEN)))

    def test_a_positional_only_parameter_is_refused(self) -> None:
        def service(tenant: str, /) -> None: ...

        with pytest.raises(
            ImproperlyConfigured,
            match=r"ServiceSpec\.service takes the positional-only parameter\(s\) \['tenant'\]",
        ):
            _build(ServiceCreateView, ServiceSpec(service=service, permissions=_OPEN))

    def test_an_optional_read_over_a_required_keyword_is_refused(self) -> None:
        def service(*, q: str) -> None: ...

        spec = ServiceSpec(
            service=service, permissions=_OPEN, reads=_reads(Parameter("q", "string"))
        )

        with pytest.raises(
            ImproperlyConfigured,
            match=r"ServiceSpec\.service requires the keyword\(s\) \['q'\], declared as "
            r"optional reads",
        ):
            _build(ServiceCreateView, spec)

    @pytest.mark.parametrize("base", [ServiceCreateView, ServiceUpdateView, ServiceDeleteView])
    def test_no_spec_does_not_raise(self, base: type) -> None:
        assert callable(base.as_view())


class TestASelectorView:
    def test_a_list_selector_requiring_data_is_refused(self) -> None:
        """The kernel seeds ``data`` for a service only."""

        def selector(*, data: Any) -> list[Any]:
            return []

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=_OPEN)

        with pytest.raises(
            ImproperlyConfigured, match=_nothing_fills("data", seat=r"SelectorSpec\.selector")
        ):
            _build(SelectorListView, spec)

    def test_a_retrieve_selector_requiring_instance_is_refused(self) -> None:
        def selector(*, instance: Any) -> None: ...

        spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, permissions=_OPEN)

        with pytest.raises(
            ImproperlyConfigured, match=_nothing_fills("instance", seat=r"SelectorSpec\.selector")
        ):
            _build(SelectorRetrieveView, spec)

    def test_a_route_capture_the_spec_does_not_declare_is_refused(self) -> None:
        """Changed by design: drfs let a retrieve selector require any
        keyword, because a route capture might fill it. The kernel route reads
        only a capture the spec declares, so an undeclared one fills nothing
        (``kernel_arguments``) and the selector is refused here."""

        def selector(*, pk: int) -> None: ...

        spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, permissions=_OPEN)

        with pytest.raises(
            ImproperlyConfigured, match=_nothing_fills("pk", seat=r"SelectorSpec\.selector")
        ):
            _build(SelectorRetrieveView, spec)

    def test_a_route_capture_declared_as_a_required_read_passes(self) -> None:
        def selector(*, pk: int) -> None: ...

        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=selector,
            permissions=_OPEN,
            reads=_reads(Parameter("pk", "integer", required=True)),
        )

        assert callable(_build(SelectorRetrieveView, spec))

    def test_a_read_named_like_a_call_seed_is_refused(self) -> None:
        """``request`` and ``view`` are the call's own, seeded off its context."""
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_row,
            permissions=_OPEN,
            reads=_reads(Parameter("request", "string")),
        )

        with pytest.raises(
            ImproperlyConfigured,
            match=r"SelectorSpec declares the parameter\(s\) \['request'\], which a registered "
            r"pool seed occupies",
        ):
            _build(SelectorListView, spec)

    def test_a_typed_provider_fills_the_keyword(self) -> None:
        def selector(*, tenant: str) -> list[Any]:
            return []

        spec = SelectorSpec(
            kind=SelectorKind.LIST, selector=selector, permissions=_OPEN, kwargs=_typed_tenant
        )

        assert callable(_build(SelectorListView, spec))

    @pytest.mark.parametrize(
        ("base", "kind"),
        [(SelectorListView, SelectorKind.RETRIEVE), (SelectorRetrieveView, SelectorKind.LIST)],
    )
    def test_a_kind_mismatch_at_the_mount_point_is_refused(
        self, base: type, kind: SelectorKind
    ) -> None:
        spec = SelectorSpec(kind=kind, selector=_row, permissions=_OPEN)

        with pytest.raises(ImproperlyConfigured, match=r"spec\.kind is"):
            _build(base, spec)

    def test_the_kind_is_refused_before_the_seeds_are_checked(self) -> None:
        """The view's own question first: a spec on the wrong mount is told so,
        not told about a keyword it would be handed on the right one."""

        def selector(*, tenant: str) -> list[Any]:
            return []

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=_OPEN)

        with pytest.raises(ImproperlyConfigured, match=r"spec\.kind is") as refused:
            _build(SelectorRetrieveView, spec)
        assert "nothing fills" not in str(refused.value)

    @pytest.mark.parametrize("base", [SelectorListView, SelectorRetrieveView])
    def test_no_spec_does_not_raise(self, base: type) -> None:
        assert callable(base.as_view())


class TestAnArrayReadWithNoItems:
    """An array read with no ``items`` over a keyword annotated with its element type.

    A kernel array ``Parameter`` with no ``items`` takes any element, so a
    selector annotated ``pks: list[int]`` behind one is handed the query
    string's strings. The kernel's ``check_seeds`` is to refuse it, naming
    ``items``; until it does, ``as_view()`` passes it.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "kernel item 14: check_seeds refuses an array read with no items over a "
            "keyword annotated as a parametrised sequence"
        ),
    )
    @pytest.mark.parametrize(
        "annotation",
        [list[int], Sequence[int], tuple[int, ...], list[int] | None],
        ids=["list", "Sequence", "tuple", "optional-list"],
    )
    def test_it_is_refused_at_as_view(self, annotation: Any) -> None:
        def selector(*, pks: Any) -> list[Any]:
            return []

        selector.__annotations__["pks"] = annotation
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=selector,
            permissions=_OPEN,
            reads=_reads(Parameter("pks", "array", required=True)),
        )

        with pytest.raises(ImproperlyConfigured, match=r"\['pks'\].*items"):
            _build(SelectorListView, spec)

    @pytest.mark.parametrize(
        ("annotation", "items"),
        [(list[Any], None), (list, None), (list[int], "integer")],
        ids=["list-of-any", "bare-list", "declared-items"],
    )
    def test_what_it_cannot_misread_passes(self, annotation: Any, items: str | None) -> None:
        def selector(*, pks: Any) -> list[Any]:
            return []

        selector.__annotations__["pks"] = annotation
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=selector,
            permissions=_OPEN,
            reads=_reads(Parameter("pks", "array", required=True, items=items)),
        )

        assert callable(_build(SelectorListView, spec))
