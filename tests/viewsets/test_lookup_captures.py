"""A viewset's detail action is refused at ``as_view()`` where its row lookup does not read the capture.

A DRF router captures a detail route's lookup under ``lookup_url_kwarg``, else
``lookup_field``, and the edge hands a spec only the captures it declares as
parameters, so a retrieve selector, or a write's target selector, that does not
declare the capture would look its row up without its key at every request. The
viewset's ``as_view()`` refuses it instead, naming the viewset, the action and
the capture (``viewsets.utils._validate_lookup_captures``). Standalone views are
not asked: their captures are the URLconf's.
"""

from __future__ import annotations

from typing import Any

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
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


def _reads(name: str) -> Parameters:
    return Parameters.of(Parameter(name, "integer", required=True))


def _row(*, by: str | None = "pk", nested: bool = False) -> SelectorSpec:
    """A retrieve selector reading ``by``, or reading nothing where ``by`` is ``None``.

    ``nested`` for a write's target, which declares no permissions of its own.
    """
    permissions = None if nested else _OPEN
    if by is None:
        return SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=lambda: None, permissions=permissions
        )

    def lookup(**kwargs: Any) -> Any:
        return Author.objects.filter(pk=kwargs[by]).first()

    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=lookup, reads=_reads(by), permissions=permissions
    )


def _service(*, instance: Any) -> None: ...


def _write(*, by: str | None = "pk", **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        instance_selector_spec=_row(by=by, nested=True),
        **fields,
    )


def _viewset(base: type = ServiceViewSet, **attrs: Any) -> type:
    return type("_Notes", (base,), {"queryset": Author.objects.all(), **attrs})


def _refusal(viewset: type, actions: dict[str, str]) -> str:
    with pytest.raises(ImproperlyConfigured) as raised:
        viewset.as_view(actions)
    return str(raised.value)


class TestARowLookupMissingTheCaptureIsRefused:
    def test_a_retrieve_selector(self) -> None:
        viewset = _viewset(SelectorViewSet, action_specs={"retrieve": _row(by=None)})
        message = _refusal(viewset, {"get": "retrieve"})
        assert message.startswith("_Notes.retrieve: the router captures the lookup as 'pk'")
        assert 'reads=Parameters.of(Parameter("pk", ..., required=True))' in message

    @pytest.mark.parametrize("action", ["update", "partial_update", "destroy"])
    def test_a_write_s_target_selector(self, action: str) -> None:
        viewset = _viewset(action_specs={action: _write(by="other")})
        assert _refusal(viewset, {"put": action}).startswith(
            f"_Notes.{action}: the router captures the lookup as 'pk'"
        )

    def test_a_detail_service_action(self) -> None:
        @service_action(_write(by=None), detail=True, methods=["post"])
        def archive(self: Any, request: Any, pk: Any = None) -> None: ...

        viewset = _viewset(archive=archive)
        assert _refusal(viewset, {"post": "archive"}).startswith(
            "_Notes.archive: the router captures the lookup as 'pk'"
        )

    def test_a_detail_selector_action(self) -> None:
        @selector_action(_row(by=None))
        def peek(self: Any, request: Any, pk: Any = None) -> None: ...

        viewset = _viewset(SelectorViewSet, peek=peek)
        assert _refusal(viewset, {"get": "peek"}).startswith(
            "_Notes.peek: the router captures the lookup as 'pk'"
        )

    def test_a_capture_only_the_write_itself_reads(self) -> None:
        """The kernel hands the target selector its own reads alone, so the
        write's ``reads`` declaring the capture does not bring it to the row."""
        viewset = _viewset(action_specs={"update": _write(by="other", reads=_reads("pk"))})
        assert _refusal(viewset, {"put": "update"}).startswith("_Notes.update:")


class TestTheCaptureName:
    def test_lookup_url_kwarg_is_the_capture(self) -> None:
        viewset = _viewset(lookup_url_kwarg="note_id", action_specs={"update": _write()})
        assert "captures the lookup as 'note_id'" in _refusal(viewset, {"put": "update"})
        _viewset(lookup_url_kwarg="note_id", action_specs={"update": _write(by="note_id")}).as_view(
            {"put": "update"}
        )

    def test_lookup_field_is_the_capture_with_no_url_kwarg(self) -> None:
        viewset = _viewset(lookup_field="slug", action_specs={"destroy": _write()})
        assert "captures the lookup as 'slug'" in _refusal(viewset, {"delete": "destroy"})
        _viewset(lookup_field="slug", action_specs={"destroy": _write(by="slug")}).as_view(
            {"delete": "destroy"}
        )


class TestWhatIsNotAsked:
    def test_a_target_selector_reading_the_capture_mounts(self) -> None:
        _viewset(
            action_specs={"update": _write(), "destroy": _write(), "retrieve": _row()}
        ).as_view({"put": "update"})

    def test_a_list_or_collection_action(self) -> None:
        """Each of these finds a row or a set by something other than the
        lookup capture, which the collection route does not carry: the
        ``list`` key and ``detail=False`` are what keep them unasked."""

        @service_action(_write(by="other"), methods=["post"])
        def touch(self: Any, request: Any) -> None: ...

        @selector_action(
            SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], permissions=_OPEN)
        )
        def recent(self: Any, request: Any) -> None: ...

        listing = SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], permissions=_OPEN)
        _viewset(action_specs={"list": listing}, touch=touch, recent=recent).as_view(
            {"get": "list"}
        )

    def test_a_write_over_a_set_or_a_list_body_looks_up_no_row(self) -> None:
        over_a_set = ServiceSpec(
            service=lambda *, collection: None,
            permissions=_OPEN,
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda: Author.objects.all()
            ),
        )
        rows = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_NameIn),
            many=True,
        )
        _viewset(action_specs={"update": over_a_set, "destroy": rows}).as_view({"put": "update"})

    def test_a_standalone_view(self) -> None:
        """Its capture is the URLconf's, which ``as_view()`` cannot see."""
        type("_View", (SelectorRetrieveView,), {"spec": _row(by=None)}).as_view()
