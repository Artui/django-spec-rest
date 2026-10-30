"""Helpers shared by the kernel edge and the views that sit on it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from asgiref.sync import sync_to_async
from django.utils.module_loading import import_string
from django_service_specs.services.service_validation_error import ServiceValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.settings import api_settings

# What the Validator binds for the call. An author's value of that name stays in
# ``extra_kwargs``, the tier beneath it, so the bound serializer is what a
# service declaring ``serializer`` receives, as it always was
# (test_the_bound_serializer_outranks_an_authors_value_of_its_name).
VALIDATOR_BOUND: frozenset[str] = frozenset({"serializer"})


def fill_call_context(
    call_context: dict[str, Any] | None, *, request: Any, view: Any
) -> dict[str, Any]:
    """The call's context, its four standard entries filled where it has none.

    The edge fills the dict it is handed with this, and a live view builds the
    one dict of its request with it, so the two never disagree on what the
    standard entries are.
    """
    # The caller's dict itself, tested ``is None`` rather than for truth, so an
    # empty one passed is still theirs
    # (test_an_empty_dict_passed_is_the_one_every_stage_is_handed). The four
    # standard entries are set where the caller put none, so the caller's win
    # (test_a_caller_s_own_entries_win), and each one's ``setdefault`` is held by
    # test_the_edge_fills_the_standard_entries_for_a_kwargs_provider. ``format``
    # is ``None``: the edge is handed none, as ``base_serializer_context`` says.
    # ``action`` is the operation's name where the view handed in carries one,
    # an empty one being none (test_the_action_is_the_view_s_where_it_has_one).
    context: dict[str, Any] = {} if call_context is None else call_context
    context.setdefault("request", request)
    context.setdefault("view", view)
    context.setdefault("format", None)
    context.setdefault("action", getattr(view, "action", None) or None)
    return context


def unauthenticated_user() -> Any:
    """DRF's unauthenticated user, as a request with no credentials carries it.

    Read from ``api_settings`` at call time, which imports the class lazily:
    ``django.contrib.auth.models`` cannot be imported while the app registry is
    still loading, and this package is imported then. Where a project sets
    ``UNAUTHENTICATED_USER`` to ``None``, DRF's own ``Request`` carries ``None``,
    which the kernel takes as no principal at all (``adispatch`` refuses it with
    ``TypeError``), so the edge acts as Django's ``AnonymousUser`` there, imported
    by name at call time for the same reason
    (test_a_project_with_no_unauthenticated_user_still_acts_as_anonymous).
    """
    # A class, or ``None``; DRF's settings object is untyped. The project's class
    # rather than Django's is held by
    # test_no_user_acts_as_the_projects_unauthenticated_user.
    factory: Any = api_settings.UNAUTHENTICATED_USER
    if factory is None:
        factory = import_string("django.contrib.auth.models.AnonymousUser")
    return factory()


async def arun_off_loop(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync callable in Django's thread-sensitive executor and await it.

    For the async render twins, whose serializer and context providers are sync
    and query: called from the event loop, one raises ``SynchronousOnlyOperation``
    the moment it touches the ORM. ``thread_sensitive=True`` puts it in the same
    executor as the kernel's ``adispatch`` runs sync callables in, so they share
    one connection and see the same transaction state as on the sync path.
    """
    return await sync_to_async(fn, thread_sensitive=True)(*args, **kwargs)


# --- naming a refusal what the request called it -------------------------
#
# A service raises about the model: ``{"title": [...]}``, because the model is
# what it was handed. The request may have said something else -- a serializer
# field declares ``source=`` precisely to let the two diverge -- and by the time
# the service runs, that name is gone. DRF resolves ``source=`` while building
# ``validated_data``, at every depth, so the wire name reaches neither the
# service nor the mutation helpers nor a relation spec. The serializer is the
# one thing still holding both vocabularies, and it holds them for free.


def _wire_names(serializer: Any) -> dict[str, tuple[str, Any]]:
    """``{source: (wire_name, nested)}`` for one serializer's writable fields.

    ``nested`` is the same mapping for a field that is itself a serializer, so
    the result describes the whole input tree rather than its top level.
    ``many=True`` is that same tree one indirection away, on ``child``.

    Read-only fields are skipped: their ``source`` cannot appear in an error
    about input, and including them would let one shadow the writable field
    that can. Two writable fields sharing a ``source`` is not a shape DRF can
    save, so the first is taken rather than guessed between. A dotted
    ``source="author.name"`` and ``source="*"`` are skipped -- neither is a key
    of ``validated_data``, so neither can be a key of an error about it.
    """
    child: Any = getattr(serializer, "child", None)
    fields: Any = getattr(child if child is not None else serializer, "fields", None)
    if fields is None:
        return {}
    names: dict[str, tuple[str, Any]] = {}
    for wire_name, field in fields.items():
        source: str = field.source
        if field.read_only or "." in source or source == "*" or source in names:
            continue
        names[source] = (wire_name, _wire_names(field) or None)
    return names


def _wire_named_detail(detail: Any, names: dict[str, tuple[str, Any]]) -> Any:
    """``detail`` with every key the serializer knows a wire name for renamed.

    A key with no entry passes through untouched, which is what keeps
    ``non_field_errors`` and anything else a service invented intact -- the
    walk renames what it can name and never guesses. A collection's error is
    walked without descending a level, in either of the shapes DRF gives one:
    a list with an entry per incoming row, or a mapping keyed by the failing
    rows' indexes. Each row is keyed like the row. An ``int`` key is how the
    second is told apart, and it is unambiguous: a field name is a string.
    """
    if isinstance(detail, dict):
        renamed: dict[Any, Any] = {}
        for key, value in detail.items():
            if isinstance(key, int):
                renamed[key] = _wire_named_detail(value, names)
                continue
            wire_name, nested = names.get(key, (key, None))
            renamed[wire_name] = _wire_named_detail(value, nested) if nested else value
        return renamed
    if isinstance(detail, list):
        return [_wire_named_detail(item, names) for item in detail]
    return detail


def wire_named_error(
    exc: ServiceValidationError | ValidationError,
    serializer: Any,
) -> ServiceValidationError | ValidationError:
    """The same refusal, keyed by the names the request actually used.

    The class is preserved for the reason the row writers preserve it: a
    service that reached for DRF's error chose its status mapping with it.
    """
    detail: Any = _wire_named_detail(exc.detail, _wire_names(serializer))
    if isinstance(exc, ServiceValidationError):
        return ServiceValidationError(detail)
    return ValidationError(detail)
