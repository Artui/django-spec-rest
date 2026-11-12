from __future__ import annotations

import dataclasses
import operator
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.datastructures import MultiValueDict
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from rest_framework import serializers
from rest_framework.fields import get_error_detail
from rest_framework_dataclasses.serializers import DataclassSerializer

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.utils import (
    author_keys,
    bind_serializer,
    bound_instance,
    describe_serializer,
    input_parameters,
    input_view_layers,
    provider_owned,
    serializer_context,
    server_values,
    validator_input,
)
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

# What this Validator binds into the call's pool: the bound serializer. A field
# of that name is the serializer's alone, never a parameter, and a validated key
# of that name is handed on in ``data`` alone.
BOUND: frozenset[str] = frozenset({"serializer"})


class SerializerValidator(Validator):
    """A Validator whose declaration is a DRF serializer, or a dataclass read through one.

    It takes a ``Serializer`` subclass, ``ModelSerializer`` and
    ``DataclassSerializer`` included, or a dataclass, which is validated
    through a ``DataclassSerializer`` built for it. Anything else is refused
    with ``ImproperlyConfigured`` when the Validator is built.

    ``parameters()`` walks the serializer's fields, in order, as the field walk
    in ``service_specs/utils.py`` reads them: a nested serializer is an object
    with Parameters of its own, ``many=True`` and a ``ListField`` an array, a
    file field a ``file``, choices with their labels; a ``HiddenField`` and a
    read-only field are no parameter. It is read on each call rather than
    when the Validator is built, because specs are built at import time, when
    a ``ModelSerializer`` cannot yet read its model, and so that ``help`` is
    rendered in the language active when it is asked for. It never queries.

    ``validate()`` builds the serializer as a DRF view would:

    - **over the body the call was sent**, where a DRF edge call names this
      Validator (``validator_input``): the caller's own data, a ``QueryDict``
      kept one, with what the edge put over it, as a DRF view's serializer was
      always handed ``request.data``. Anywhere else, the kernel's checked
      arguments.

    - **with the target as** ``instance``, so an update's uniqueness checks
      exclude the row being updated. The queryset a collection selector
      resolves is no row, so a call over one binds as a create; the target is handed over as
      it is, since a
      serializer, unlike a ``ModelForm``, writes nothing onto its instance
      while it validates.
    - **partial as the call is**, the context's ``partial``, so a partial call
      may leave out a required field and returns only what was sent.
    - **under the serializer context DRF builds on HTTP**, ``request``,
      ``format`` and ``view``. The ``request`` and ``view`` the call
      registered as pool seeds are the serializer's own, read from
      ``ValidationContext.ambient`` as the kernel resolved them, and where a
      seed is absent or ``None``, the entry of that name in
      ``ValidationContext.call_context``. A call that carries
      neither gets an offline request whose ``user`` is the
      principal and whose ``data`` is the arguments, built by
      [`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context],
      so a ``CurrentUserDefault`` reads the principal and a field or a
      ``validate()`` reading ``self.context["request"]`` finds a request
      rather than a ``KeyError``. What a registered request's ``user`` is, is
      the transport's to make the principal; the Validator never writes to a
      call's own objects. Over that, the input half of the view hooks a DRF
      edge carries for the call (``input_view_layers``), then this Validator's
      own ``serializer_context``, each winning on a key it shares with what
      it layers over (see
      ``serializer_context`` in ``service_specs/utils.py``).
      The callable declares what it reads from the call's pool:
      ``request``, ``view``, ``user``, ``call_context``, a registered seed, or
      an argument. It is
      asked once per call, a ``many`` call's included, except where the call
      builds the serializer twice, for a body the server puts a value into or
      a row a target lookup resolves, and what the callable is handed differs
      between the two.

    A refusal is one
    [`DRFInvalidArguments`][django_spec_rest.service_specs.drf_invalid_arguments.DRFInvalidArguments],
    the kernel's refusal that is DRF's ``ValidationError`` as well, carrying
    the serializer's ``errors`` unchanged: DRF's ``ErrorDetail`` leaves, each
    with its code, cross-field messages under ``non_field_errors``, and a
    nested list's errors in whichever shape the installed DRF writes them.

    ``validated()`` hands the service ``data``, the serializer's
    ``validated_data`` - the validated mapping, or the dataclass instance a
    ``DataclassSerializer`` builds - and the bound serializer is bound for the
    call as ``serializer``, its ``save()`` the DRF one. ``values`` follow what
    ``validated_data`` is: a
    mapping's entries, keyed as DRF keys them, by each field's ``source``; a dataclass
    instance's ``__init__`` fields, whether a dataclass was declared or a
    ``DataclassSerializer`` subclass was; and nothing for any other object a
    serializer's ``validate()`` returns, which reaches the service only as
    ``data``. **A key named like a seed of the call is a value only in**
    ``data``: DRF's ``HiddenField(default=CurrentUserDefault())`` named
    ``user``, or a key a ``validate()`` adds named ``result``, stays in
    ``validated_data`` as the serializer built it, and the service's ``user``
    is the call's principal (see ``_unseeded``).
    **So is a key named in** ``server_owned``, the names the caller declares
    the server's: the client's value is the service's in ``data`` alone, unless the edge put
    the server's
    value into the field it comes from (see ``_unowned``). **Where the edge did,
    that field's validation of the value the edge put is the key's value**,
    validated on its own once the serializer has accepted the body, never read
    back off the body (see ``_server_values``), whatever the field reads from
    the body, and whatever a later field of the same ``source``, a
    ``source="*"`` nested serializer, a ``validate()`` or a
    ``to_internal_value`` override did to the key: it is the parameter's, by
    the field's ``source`` or, where that is no single key, by the field's name,
    and by the key an author named it under (see ``_handed``), and it is laid
    back over the key in a
    mapping ``data`` (see ``_lay_back``). A dataclass instance is ``data`` as
    built, and a ``many`` call's rows are neither validated apart nor laid back.
    **A validated ``None`` for a file field is ``""``,** what the model field
    stores for no file, in ``data`` and the values, where the input is no form
    (see ``_cleared``). ``save()``, ``create`` and ``update`` take it as it is and
    the kernel's ``update_from_input`` reads it as a clear, so a ``null`` a
    field's ``allow_null`` lets through clears the file however a service
    writes it. The same holds for a field DRF fills with its ``None`` default on
    a whole call (test_a_put_leaving_out_a_file_defaulting_to_none_clears_it).

    **A partial call over a dataclass is refused**, a ``DataclassSerializer``
    subclass included: one builds its instance from every field, and a field
    a partial call left out fails as a ``TypeError`` from inside the library.
    ``supports_partial`` is therefore answered per instance, ``False`` for
    either declaration and ``True`` for any other serializer, so a spec
    declaring ``partial=True`` over a dataclass is refused when it is built.
    A partial call made on the Validator directly is refused with
    ``ImproperlyConfigured`` as well.

    ``validated_many()`` validates a ``many`` spec's rows as DRF's own list
    serializer does, once: the serializer's child class under
    ``many=True`` (so a ``Meta.list_serializer_class`` and its list-level
    ``validate()`` run), with the call's context and partial flag. The one
    list serializer is bound for the call as ``serializer``, ``data`` is the
    list of each row's ``validated_data`` and the values are the rows' values
    under ``many_argument``. A refusal is an ``DRFInvalidArguments`` whose detail
    keys each failing row by the index the caller's list gave it, whichever of
    DRF's two shapes the installed version reports item errors in, and whose
    list-level message sits under ``non_field_errors``. Over HTTP as off it,
    the list bound is the rows the kernel passed: where it refused a row, the
    list's own checks judge the rows left, and their refusal sits beside the
    refused row's (test_bulk_rows_over_http's
    test_a_lists_own_checks_judge_the_rows_the_kernel_passed).
    """

    def __init__(
        self,
        serializer: type[Any],
        *,
        serializer_context: Callable[..., Mapping[str, Any]] | None = None,
        lenient: bool = False,
        excluded: frozenset[str] = frozenset(),
        server_owned: frozenset[str] = frozenset(),
        json_schema_registry: JsonSchemaRegistry | None = None,
    ) -> None:
        # Each operand is held by its own test (test_parameters_are_the_walked_fields, et al.).
        if not (
            isinstance(serializer, type)
            and (
                issubclass(serializer, serializers.Serializer)
                or dataclasses.is_dataclass(serializer)
            )
        ):
            raise ImproperlyConfigured(
                "SerializerValidator takes a Serializer subclass or a dataclass; "
                f"got {serializer!r}."
            )
        self.serializer = serializer
        self.serializer_context = serializer_context
        self.lenient = lenient
        self.excluded = excluded
        self.server_owned = server_owned
        self.json_schema_registry = json_schema_registry
        self.supports_partial = not (
            dataclasses.is_dataclass(serializer) or issubclass(serializer, DataclassSerializer)
        )

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        """The serializer's input fields, as Parameters.

        Read off ``describe_serializer``: inside an edge call, the serializer
        the call builds once and validates with, so a serializer that queries
        as it is built queries once in the call
        (test_its_queries_run_once); outside one, a serializer built
        afresh for each read, as a schema or a registration reads it.
        ``call_context`` is the dict of the call asking, which the kernel hands
        a Validator declaring the keyword on every ask inside a call and none
        outside one; only the edge's own call is described as the edge's
        (``describe_serializer``), so the same declaration dispatched by a
        service for another principal is described unbound
        (test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_is_never_described_under_the_view_s_request).

        A field named like a seed of the call is no parameter: one of the
        dispatcher's own names (``RESERVED_POOL_SEEDS``, the ``user`` case of
        test_a_writable_field_named_like_a_seed_validates_into_data) and the
        ``serializer`` this Validator binds (``BOUND``,
        test_an_input_field_named_serializer_validates_into_data) always, and each of
        ``excluded``, the names a caller's registered seeds take
        (test_a_field_the_validator_excludes_is_unsendable_when_required). The
        kernel refuses a parameter a seed occupies, where a serializer was
        always free to declare such a field: the client sent its value, the
        serializer validated it into ``data``, and the seed kept its own. So
        the field is the serializer's alone, read from the body the edge hands
        it (``validator_input``), and never meets the seed in the call's pool.

        ``lenient`` declares each field by name alone - any value, optional,
        nullable - so the kernel's shape check passes every value through and
        the serializer is the one to answer it, as a live DRF view's request
        always was answered. The edge dispatches a lenient copy of a spec's Validator
        (``recording_spec``) for a form body, and for a JSON body where the view's
        ``lenient_json_body`` says so.
        """
        seeded = self._seeded()
        walked = Parameters.of(
            *(param for param in self._walk(call_context) if param.name not in seeded)
        )
        if not self.lenient:
            return walked
        return Parameters.of(
            *(Parameter(param.name, "any", required=False, nullable=True) for param in walked)
        )

    @property
    def unsendable(self) -> frozenset[str]:
        """The required input fields no call on the kernel route can send.

        A field named like a seed (``RESERVED_POOL_SEEDS``, ``BOUND`` or
        ``excluded``) is no parameter (see ``parameters()``), so the kernel has
        nowhere to take its value from, while an HTTP body carries it
        by name. Where the serializer *requires* such a field, a call
        through the kernel's ``dispatch`` is refused for it however it is made.
        This names those fields, by the name ``parameters()`` would have
        declared them under, so a transport can refuse such a spec before a
        call reaches it::

            compiled.validator.unsendable

        - **Only what ``parameters()`` omits.** A field the Validator declares
          a parameter for is never named, even one a seed, a server argument or
          a call seed then fills: a field named like a *registered* seed is
          one unless the caller names it in ``excluded``. A required field called ``serializer``
          or ``user`` is named.
        - **Required only.** An optional field, one with a default, a
          ``read_only`` field and a ``HiddenField`` are no input to require
          (test_an_optional_field_is_not_unsendable,
          test_a_read_only_field_is_not_unsendable,
          test_a_hidden_field_is_not_unsendable), and a ``many`` spec's
          row fields are read through the row serializer this Validator holds,
          so a row's required ``user`` is named and a row's ``tenant`` is not
          (test_a_many_specs_row_fields_are_read_through_the_row_serializer).
        - **Not partial.** Whether a call may leave a required field out is
          the spec's ``partial``, not this attribute's question; it
          names the field whether or not the spec is partial
          (test_a_partial_spec_names_the_same_fields).
        - **Not ``lenient``.** The declaration relaxes what each parameter
          accepts and not which names are parameters
          (test_a_lenient_validator_names_the_same_fields).

        Computed on each read, from the serializer ``parameters()`` describes,
        for the reason ``parameters()`` is: a ``ModelSerializer`` cannot read
        its model when specs are built.
        """
        seeded = self._seeded()
        return frozenset(
            param.name for param in self._walk() if param.required and param.name in seeded
        )

    def _seeded(self) -> frozenset[str]:
        """The field names this Validator leaves out of ``parameters()``: the one list written."""
        return RESERVED_POOL_SEEDS | BOUND | self.excluded

    def _walk(self, call_context: dict[str, Any] | None = None) -> Parameters:
        """Every input field of the serializer as a Parameter, seed-named ones included."""
        return input_parameters(
            describe_serializer(self.serializer, self, call_context=call_context),
            registry=self.json_schema_registry,
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The validated values by source, or ``DRFInvalidArguments`` with DRF's detail."""
        return self._validated(arguments, context).values

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """The values, ``validated_data`` as the call's ``data``, and the bound ``serializer``."""
        return self._validated(arguments, context)

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        """The rows validated once as DRF's list serializer, the one serializer bound for the call.

        The rows are the ones the kernel's shape check passed, as it hands
        them: the edge holds no body for a ``many`` call (``validator_input``),
        so a row the kernel refused is not bound twice, and the list's own
        checks judge the rows left.
        """
        self._refuse_partial(context)
        indices = list(rows)
        serializer = self._serializer(
            context, data=list(rows.values()), many=True, partial=context.partial
        )
        if not serializer.is_valid():
            raise DRFInvalidArguments(_by_row(serializer.errors, indices))
        data: list[Any] = _cleared(serializer, list(serializer.validated_data))
        return Validated(
            values={many_argument: [_values(row) for row in data]},
            data=data,
            pool={"serializer": serializer},
        )

    def _validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        # Neither public method calls the other: a subclass may extend either without recursing.
        self._refuse_partial(context)
        serializer = self._bind(arguments, context)
        if not serializer.is_valid():
            raise DRFInvalidArguments(serializer.errors)
        data: Any = serializer.validated_data
        held = _server_values(serializer, server_values(self, context.principal))
        _lay_back(data, serializer, held)
        if not isinstance(serializer.initial_data, MultiValueDict):
            data = _cleared(serializer, data)
            held = {name: _cleared(serializer.fields[name], value) for name, value in held.items()}
        values = _values(data)
        handed = _handed(serializer, held, author_keys(self, context.principal))
        values.update(handed)
        values = _unseeded(values, context)
        return Validated(
            values=self._unowned(serializer, values, handed.keys(), context.principal),
            data=data,
            pool={"serializer": serializer},
        )

    def _unowned(
        self,
        serializer: serializers.Serializer,
        values: dict[str, Any],
        kept: Iterable[str],
        principal: Any,
    ) -> dict[str, Any]:
        """``values`` less each ``server_owned`` key the client's input became."""
        owned = self.server_owned | provider_owned(self, principal)
        owned = owned.union(*(_sources(serializer, name) for name in owned)).difference(kept)
        return {name: value for name, value in values.items() if name not in owned}

    def _refuse_partial(self, context: ValidationContext) -> None:
        # Each arm is held by a test (test_a_partial_call_over_a_dataclass_is_refused and kin).
        if context.partial and not self.supports_partial:
            raise ImproperlyConfigured(
                f"SerializerValidator({self.serializer.__qualname__}) cannot validate a partial "
                "call: a DataclassSerializer builds its instance from every field. Declare the "
                "input as a Serializer subclass to take a partial call."
            )

    def _bind(
        self, arguments: Mapping[str, Any], context: ValidationContext
    ) -> serializers.Serializer:
        """The serializer, bound to the call's input: the edge's body for it, else ``arguments``."""
        return self._serializer(
            context,
            data=validator_input(self, arguments, context.principal),
            instance=bound_instance(context.target),
            partial=context.partial,
        )

    def _serializer(self, context: ValidationContext, **kwargs: Any) -> serializers.Serializer:
        """The serializer bound as ``kwargs`` binds it, under the call's context."""
        return bind_serializer(
            self.serializer, context=self._context(context, kwargs["data"]), **kwargs
        )

    def _context(
        self, context: ValidationContext, arguments: Mapping[str, Any] | list[Any]
    ) -> dict[str, Any]:
        """The serializer context for this call: DRF's, the view's input hooks, then the spec's."""
        return serializer_context(
            context.principal,
            context.ambient,
            arguments,
            view_layers=input_view_layers(self, context.principal),
            provider=self.serializer_context,
            call_context=context.call_context,
        )


def _server_values(serializer: serializers.Serializer, put: Mapping[str, Any]) -> dict[str, Any]:
    """The server's value for each field of ``put``, validated as DRF's field loop does."""
    fields = serializer.fields
    held: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for name, field in fields.items():
        if name not in put or field.read_only:
            continue
        method = getattr(serializer, f"validate_{name}", None)
        try:
            value = field.run_validation(_server_primitive(field, put[name]))
            if method is not None:
                value = method(value)
        except serializers.ValidationError as exc:
            errors[name] = exc.detail
        except DjangoValidationError as exc:
            errors[name] = get_error_detail(exc)
        except serializers.SkipField:
            pass
        else:
            held[name] = value
    if errors:
        raise DRFInvalidArguments(errors)
    return held


def _server_primitive(field: serializers.Field, value: Any) -> Any:
    """The server's ``value`` as ``field`` takes it: as put, unless the field takes no input."""
    if isinstance(field, serializers.HiddenField):
        return serializers.empty
    return value


def _handed(
    serializer: serializers.Serializer, held: Mapping[str, Any], authored: Mapping[str, str]
) -> dict[str, Any]:
    """Each value of ``held``, by the names its field's value is handed to a parameter under."""
    handed: dict[str, Any] = {}
    for name, value in held.items():
        source = serializer.fields[name].source_attrs
        key = source[0] if len(source) == 1 else name
        handed[key] = value
        handed[authored.get(name, key)] = value
    return handed


def _sources(serializer: serializers.Serializer, name: str) -> tuple[str, ...]:
    """The key ``validated_data`` holds the value of the field named ``name`` under, if any."""
    field = serializer.fields.get(name)
    attrs = field.source_attrs if field is not None else []
    return tuple(attrs[:1])


def _lay_back(data: Any, serializer: serializers.Serializer, held: Mapping[str, Any]) -> None:
    """Each of ``held`` written back over its field's ``source`` key in ``data``."""
    for name, value in held.items():
        *path, last = serializer.fields[name].source_attrs or [None]
        target: Any = data
        for key in path:
            target = target.get(key) if isinstance(target, Mapping) else None
        if isinstance(target, MutableMapping) and last in target:
            target[last] = value


def _cleared(field: serializers.Field | None, value: Any) -> Any:
    """``value`` as ``field`` validated it, each file field's ``None`` the empty file ``""``."""
    if isinstance(field, serializers.FileField):
        return "" if value is None else value
    if isinstance(field, serializers.ListSerializer):
        if not isinstance(value, list):
            return value
        rows = [_cleared(field.child, row) for row in value]
        return value if all(map(operator.is_, rows, value)) else rows
    if isinstance(field, serializers.Serializer):
        for child in field.fields.values():
            attrs = child.source_attrs
            value = _cleared_at(value, attrs, child) if attrs else _cleared(child, value)
    return value


def _cleared_at(value: Any, attrs: list[str], field: serializers.Field) -> Any:
    """``value`` with what ``field`` validated at ``attrs`` cleared, or itself if unchanged."""
    if not isinstance(value, Mapping) or attrs[0] not in value:
        return value
    head, *rest = attrs
    held = value[head]
    cleared = _cleared_at(held, rest, field) if rest else _cleared(field, held)
    return value if cleared is held else {**value, head: cleared}


def _by_row(errors: Any, indices: list[int]) -> dict[Any, Any]:
    """A list serializer's errors, each failing row keyed by the caller's own index."""
    if isinstance(errors, list):
        errors = {position: row for position, row in enumerate(errors) if row}
    return {indices[key] if isinstance(key, int) else key: detail for key, detail in errors.items()}


def _unseeded(values: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
    """``values`` less every key a seed of the call, or the bound serializer, holds."""
    seeded = RESERVED_POOL_SEEDS | context.ambient.keys() | BOUND
    return {name: value for name, value in values.items() if name not in seeded}


def _values(data: Any) -> dict[str, Any]:
    """The values a call's ``validated_data`` spreads by name."""
    if isinstance(data, Mapping):
        return dict(data)
    if dataclasses.is_dataclass(data):
        return {f.name: getattr(data, f.name) for f in dataclasses.fields(data) if f.init}
    return {}
