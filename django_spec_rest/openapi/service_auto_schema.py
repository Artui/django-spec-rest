"""``ServiceAutoSchema`` — drf-spectacular ``AutoSchema`` aware of kernel specs.

Importing this module pulls in ``drf-spectacular``, so the package's top-level
``__init__.py`` does not load it; users opt in via
[`django_spec_rest.openapi.enable_openapi`][django_spec_rest.openapi.enable_openapi.enable_openapi].
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Presenter,
    SelectorKind,
    filter_set_parameters,
    output_schema,
    parameters_schema,
    provider_keys,
    spec_caller_input_schema,
)
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.can_present_nothing import can_present_nothing
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import (
    ResolvedComponent,
    build_array_type,
    build_parameter_type,
)
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiRequest,
    OpenApiResponse,
)
from rest_framework.serializers import Serializer

from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS
from django_spec_rest.openapi._caller_serializer_class import caller_serializer_class
from django_spec_rest.openapi._resolve import (
    resolve_selector_spec,
    resolve_service_spec,
)
from django_spec_rest.openapi.service_error_serializer import (
    ServiceErrorSerializer,
)
from django_spec_rest.openapi.utils import default_status
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.mutation.utils import status_for_a_body
from django_spec_rest.views.utils import view_pool_seeds


class ServiceAutoSchema(AutoSchema):
    """``AutoSchema`` that derives its request / response from a kernel spec.

    A kernel ``ServiceSpec`` or ``SelectorSpec`` is read off its seats, as the
    route serves it, on every surface: the standalone ``Service*View`` and
    ``Selector*View`` classes, the ``ServiceViewSet`` and ``SelectorViewSet``
    action mixins, and ``@service_action`` / ``@selector_action``:

    - **The request body** is a ``SerializerValidator``'s serializer, built
      partial exactly where the route dispatches the spec's partial variant
      (``kernel_spec_variant``): a ``PATCH``, unless the Validator cannot take a
      partial call, and a spec declaring ``partial``. Its component is
      drf-spectacular's name for the author's class, except where the spec's
      ``input_data`` reaches a field: then a subclass less the fields it fills,
      with those it may fill not required, under a name of its own
      (``caller_serializer_class``). A ``many`` spec takes a list of those
      rows. Any other Validator is the kernel's
      ``spec_caller_input_schema`` less what the body does not carry
      (``_parameters_body``): what the server fills is not asked for, and a
      key a provider may fill is not required.
    - **The response body** is a ``SerializerPresenter``'s serializer, or any
      other presenter's ``output_schema``, a list of rows where the spec
      presents rows (``_presents_rows``). A spec with no presenter documents
      the no-content response, and a selector spec with none keeps the base's
      reading of the view's ``serializer_class``, which renders it.
    - **The status** is the view's ``success_status`` where it is an ``int``,
      since a kernel spec declares none, over the action's default; a body is
      documented as the ``200`` it is served as where that is ``204``, and the
      ``204`` beside it where ``can_present_nothing``.
    - **A** ``400`` is documented wherever the spec declares a Validator: its
      refusal is DRF's field errors, whichever seat refused, so the body is the
      ``ValidationErrors`` component. Beside it, any of what else the edge
      sends as a 400: a ``detail`` sentence (the body is no object), and the
      bare list of messages a service's ``ServiceValidationError`` over a
      sentence or a list answers with.
    - **A** ``422`` is documented on every service spec, since the service, a
      precondition or a provider can raise a plain ``ServiceError``, which the
      edge answers 422 with or without a Validator; and on every selector spec,
      whose selector, preconditions and providers can raise one too. A selector
      spec taking a parameter (a read, a shape or a filter) documents the
      ``400`` its refusal is, with the same body.
    - **A FilterSet's query parameters** are the kernel's
      ``filter_set_parameters``, on a list operation only.

    User-supplied ``@extend_schema`` annotations always win, and
    ``@extend_schema(parameters=...)`` merges over the filter parameters exactly
    as it does for a view-level FilterSet.
    """

    def get_request_serializer(self) -> Any:
        spec = resolve_service_spec(self.view)
        if spec is not None:
            return self._kernel_request_body(spec)
        return super().get_request_serializer()

    def _kernel_request_body(self, spec: KernelServiceSpec) -> Any:
        """What a kernel ``spec``'s request body is documented by, or ``None`` for no body.

        Read off the variant the route dispatches for this method, so the
        documented body is the one validated: a ``PATCH`` asks for the partial
        variant, which is the spec itself where its Validator cannot take a
        partial call. A ``SerializerValidator`` is its serializer, built
        partial as the variant is and over a list for a ``many`` spec
        (test_a_patch_is_documented_partial,
        test_a_patch_a_dataclass_validates_whole_is_documented_whole,
        test_a_many_spec_takes_an_array_of_rows). Where the variant's
        ``input_data`` reaches one of its fields, it is the subclass
        ``caller_serializer_class`` derives, less what ``input_data`` fills
        and with what it may fill not required, as OPTIONS describes the
        route (test_the_body_agrees_with_options); the same reading of each
        row on a ``many`` spec, since ``input_data`` is merged over every
        row. Named from the component drf-spectacular gives the author's
        class, read without the ``Patched`` and ``Request`` it adds itself.
        A spec reaching nothing keeps the author's component
        (test_a_spec_reaching_nothing_keeps_the_author_s_component). Any other Validator, or
        none, is ``_parameters_body`` (test_another_validator_is_its_parameters_schema).
        """
        variant = _partial_variant(spec) if self.method == "PATCH" else spec
        validator = variant.validator
        if isinstance(validator, SerializerValidator):
            # A ``SerializerValidator`` takes a ``Serializer`` subclass or a
            # dataclass, which renders through a ``DataclassSerializer``.
            serializer = cast(
                "type[Serializer[Any]]", renderable_serializer_class(validator.serializer)
            )
            owned, reached = _input_data_reach(variant.input_data, validator.parameters())
            # Only where ``input_data`` reaches a field: a second class under
            # the author's name would collide with the author's own
            # (test_a_spec_reaching_nothing_is_documented_by_the_author_s_class).
            if reached:
                serializer = caller_serializer_class(
                    serializer,
                    self._get_serializer_name(serializer(), "response"),
                    owned=owned,
                    relaxed=reached - owned,
                )
            return serializer(many=variant.many, partial=variant.partial)
        return self._parameters_body(variant)

    def _parameters_body(self, spec: KernelServiceSpec) -> Any:
        """The kernel's caller schema of ``spec``, less what the body does not choose, or ``None``.

        ``spec_caller_input_schema``: ``spec.parameters()`` relaxed as dispatch
        relaxes a partial call (test_another_validator_s_patch_requires_nothing),
        less the names the server fills, ``server_owned_keys`` under the view's
        ``pool_seeds`` (test_a_route_capture_and_a_provider_s_key_are_no_body_key,
        test_a_read_named_for_a_seed_the_view_registers_is_no_body_key), with a key
        a provider may fill offered and not required
        (test_a_read_a_provider_may_decline_is_offered_and_not_required), and
        on a ``many`` spec the same read of each row by what ``input_data``
        reaches there
        (test_a_many_row_withholds_what_input_data_fills_and_relaxes_what_it_may).
        Then less what stays this transport's: the target lookup's reads,
        which name the row and never come from the body
        (test_the_target_s_reads_are_no_body_key), and the route's captures,
        which outrank the body's value. Built under the edge's
        unknown-argument policy, so the body is closed exactly where dispatch
        closes it. A ``many`` spec's body is the list itself, which the edge
        reads under its ``many_argument``
        (test_a_many_spec_over_another_validator_takes_an_array_of_its_rows).

        Handed to drf-spectacular as an ``OpenApiRequest``, which it renders as
        the schema given: a bare ``dict`` would be read as a mapping of media
        types.
        """
        target = spec.target_selector_spec()
        schema = _without(
            spec_caller_input_schema(
                spec, pool_seeds=view_pool_seeds(self.view), unknown_arguments=UNKNOWN_ARGUMENTS
            ),
            (target.parameters().names() if target is not None else frozenset())
            | frozenset(self._route_captures()),
        )
        if not schema["properties"]:
            return None
        if spec.many:
            schema = schema["properties"][spec.many_argument]
        return OpenApiRequest(schema)

    def _route_captures(self) -> list[str]:
        """The names the inspected route captures, as the view's ``kwargs`` carry them.

        Read off the route's own pattern rather than the documented path,
        where drf-spectacular may have renamed a ``pk`` to ``id``: a
        ``path()`` converter's ``<slug:tenant>`` or a regex's ``(?P<pk>...)``.
        """
        return [converter or group for converter, group in _ROUTE_CAPTURE.findall(self.path_regex)]

    def _get_request_body(self, direction: str = "request") -> Any:
        spec = resolve_service_spec(self.view)
        if spec is None:
            return super()._get_request_body(direction)
        if self.method == "DELETE":
            # drf-spectacular documents no body on a ``DELETE``, and a
            # kernel spec's is whatever ``_kernel_request_body`` reads, none
            # included, so the call is presented as a ``POST``, which no
            # body depends on (test_a_delete_with_a_validator_documents_its_body,
            # test_a_spec_taking_nothing_documents_no_body).
            return self._as_method("POST", direction)
        if self.method == "PATCH" and not _partial_variant(spec).partial:
            # drf-spectacular re-stamps a ``PATCH``'s serializer partial,
            # where the route validates this one whole: its Validator cannot
            # take a partial call. Presented as the ``PUT`` it is validated
            # as (test_a_patch_a_dataclass_validates_whole_is_documented_whole);
            # every other ``PATCH`` keeps the stamp, so an
            # ``@extend_schema(request=...)`` serializer is documented
            # partial as it is on any view
            # (test_an_extend_schema_request_is_documented_partial_on_a_patch).
            return self._as_method("PUT", direction)
        return super()._get_request_body(direction)

    def _as_method(self, method: str, direction: str) -> Any:
        """The base's request body, asked as if the operation were ``method``."""
        saved = self.method
        self.method = method
        try:
            return super()._get_request_body(direction)
        finally:
            self.method = saved

    def get_response_serializers(self) -> Any:
        spec = resolve_service_spec(self.view)
        if spec is not None:
            return self._kernel_responses(spec)
        selector = resolve_selector_spec(self.view)
        if selector is not None:
            return self._kernel_selector_responses(selector)
        return super().get_response_serializers()

    def _kernel_selector_responses(self, spec: KernelSelectorSpec) -> dict[Any, Any]:
        """A kernel selector spec's responses: its body, then the refusals the edge sends.

        The body is the presenter's; a spec with no presenter is rendered by the
        view's ``serializer_class``, which the base reads
        (test_no_presenter_is_the_view_s_serializer_class). A ``400`` is documented
        where the spec takes any parameter (its reads, shapes and filters),
        which the edge refuses with the field errors a Validator's refusal sends
        (test_the_documented_400_describes_the_body_the_edge_sends). A route
        capture is one too: only its converter guarantees its type, and a
        router's default lookup regex or a ``str`` converter guarantees none
        (test_a_route_capture_is_refused_under_its_name). A ``422`` is documented on every selector spec, since the selector, a
        precondition or a provider can raise a plain ``ServiceError``
        (test_it_is_documented_whatever_the_selector_reads).
        """
        body = (
            self._kernel_rows(spec, spec.presenter)
            if spec.presenter is not None
            else super().get_response_serializers()
        )
        # Always the ``200`` the base gives a read: it answers ``201`` only for
        # a ``POST`` create operation, which no selector is.
        responses: dict[Any, Any] = {200: body}
        if spec.parameters():
            responses[400] = self._validation_errors_response()
        responses[422] = ServiceErrorSerializer
        return responses

    def _kernel_responses(self, spec: KernelServiceSpec) -> dict[Any, Any]:
        """A kernel service spec's responses.

        The status is the view's own ``success_status``, the hook the kernel
        route answers with (``MutationFlowMixin``), where it is an ``int``; a
        callable keys on the result, so the action's default stands
        (test_the_view_s_status_is_documented,
        test_a_callable_status_documents_the_action_s_default). The body is
        the presenter the kernel's ``present`` renders with,
        ``presenter_for_output()``. The ``204`` beside a body is where the spec
        may present nothing; its operands are held here by
        test_no_presenter_documents_no_content_at_the_status (the body) and
        test_a_create_answers_201_with_its_presenter_s_serializer (the
        question), and the branch by
        test_a_spec_that_may_present_nothing_documents_its_204.
        """
        declared = getattr(self.view, "success_status", None)
        status = declared if isinstance(declared, int) else default_status(self.view)
        presenter = spec.presenter_for_output()
        rows = _presents_rows(spec)
        # drf-spectacular never reads a write as a list operation, so a raw
        # schema of rows is wrapped here.
        body = None if presenter is None else _presented(presenter, rows=rows, wrap=rows)
        responses: dict[Any, Any] = (
            {status_for_a_body(status): body}
            if body is not None
            else {status: OpenApiResponse(description="")}
        )
        if body is not None and can_present_nothing(spec):
            responses[204] = OpenApiResponse(description="")
        # A Validator's refusal is a 400 of DRF's field errors, whichever kind
        # of Validator refused
        # (test_the_documented_400_describes_the_body_the_edge_sends); a plain
        # ``ServiceError`` from the service, a precondition or a provider is a
        # 422 whether or not the spec has a Validator
        # (test_it_is_documented_on_a_spec_with_a_service_whether_or_not_it_has_a_validator,
        # test_a_spec_with_no_validator_documents_no_400).
        if spec.validator is not None:
            responses[400] = self._validation_errors_response()
        responses[422] = ServiceErrorSerializer
        return responses

    def _validation_errors_response(self) -> OpenApiResponse:
        """The ``400`` the edge sends over a Validator: the ``ValidationErrors`` tree, a ``detail`` or a list.

        ``ValidationErrors`` is registered once as a component of its own: a
        serializer cannot describe it, being a tree of any depth. A ``detail``
        sentence is the ``ServiceError`` shape, which the edge sends for a body
        that is no object (test_a_body_that_is_no_object_is_a_detail_the_400_also_describes).
        A bare list of messages is what DRF's ``ValidationError`` answers for a
        service's ``ServiceValidationError`` over a sentence or a list
        (test_a_service_s_validation_error_is_documented_in_the_shape_it_is_sent).
        The alternatives are ``anyOf``: a ``{"detail": "..."}`` is both the
        ``ServiceError`` and a ``ValidationErrors`` with a string leaf, which a
        ``oneOf`` would refuse.

        A component of this name that another object holds is refused rather
        than shared, since a ``$ref`` to the wrong schema documents a body the
        edge never sends (test_validation_errors_component_name's
        test_is_refused_whichever_comes_first). Only where this package's schema
        sees both: a view on drf-spectacular's own ``AutoSchema`` resolving the
        serializer after the 400 gets drf-spectacular's warning alone.
        """
        component = ResolvedComponent(
            name=_VALIDATION_ERRORS,
            type=ResolvedComponent.SCHEMA,
            object=_ValidationErrors,
            schema=_VALIDATION_ERRORS_SCHEMA,
        )
        try:
            holder = self.registry[component].object
        except KeyError:
            self.registry.register_on_missing(component)
        else:
            if holder is not _ValidationErrors:
                raise _name_taken(holder)
        detail = self.resolve_serializer(ServiceErrorSerializer, "response")
        return OpenApiResponse(
            response={"anyOf": [component.ref, detail.ref, _MESSAGES]},
        )

    def resolve_serializer(self, serializer: Any, *args: Any, **kwargs: Any) -> Any:
        # Passed through whole: the base's later parameters differ by version
        # (``bypass_extensions`` is not in every release the floor admits).
        resolved = super().resolve_serializer(serializer, *args, **kwargs)
        # No serializer is ``ValidationErrors``: the registry answered one for
        # the name it was given, which this schema registered first.
        if resolved.object is _ValidationErrors:
            raise _name_taken(serializer)
        return resolved

    def _kernel_rows(self, spec: KernelSelectorSpec, presenter: Presenter) -> Any:
        """A kernel selector spec's body: one row, or every row for a ``LIST``.

        drf-spectacular wraps a list operation's body in an array itself, and
        pages it, so a raw schema is wrapped here only where it would not: on a
        ``@selector_action``, whose operation it does not read as a list. A
        serializer goes in as a ``ListSerializer``, which it unwraps and wraps
        once on either (test_a_selector_action_listing_rows_is_an_array,
        test_a_list_is_an_array_of_its_presenter_s_serializer, and for a raw
        schema test_another_presenter_is_its_output_schema).
        """
        rows = spec.kind is SelectorKind.LIST
        # A bare single-row serializer, so the heuristic asks the view's action
        # and method rather than calling back into this method for its answer.
        wrap = rows and not self._is_list_view(Serializer())
        return _presented(presenter, rows=rows, wrap=wrap)

    def _get_filter_parameters(self) -> list[Any]:
        # A spec-level FilterSet must drop ``DjangoFilterBackend`` (the
        # ``as_view()`` guard forbids running both), so it is invisible to the
        # base's backend-driven path and its parameters would silently vanish.
        parameters = super()._get_filter_parameters()
        # Mirror the base's list-only gate: ``get_filter_backends()`` returns
        # nothing for a detail operation, so a view-level FilterSet documents no
        # parameters there either. Parity stays exact for RETRIEVE specs even
        # though the runtime still shapes and filters the retrieve queryset
        # before ``.first()``.
        if not self._is_list_view():
            return parameters
        spec = resolve_selector_spec(self.view)
        if spec is None or spec.filter_set is None:
            return parameters
        return parameters + _kernel_filter_parameters(spec.filter_set)


def _partial_variant(spec: KernelServiceSpec) -> KernelServiceSpec:
    """The variant the route dispatches ``spec`` as for a ``PATCH``: partial where it can be.

    ``kernel_spec_variant``'s, held per spec, so the schema reads the very
    spec a ``PATCH`` runs. It is ``spec`` itself where no partial call is
    possible: a Validator that cannot take one, or none at all.
    """
    # The variant of a service spec is a service spec; the function is
    # annotated for both kinds it compiles.
    return cast("KernelServiceSpec", kernel_spec_variant(spec, partial=True))


def _input_data_reach(
    provider: Callable[..., Any] | None, parameters: Parameters
) -> tuple[frozenset[str], frozenset[str]]:
    """The fields in ``parameters`` that ``provider`` is annotated to fill, and those it fills or may fill.

    The kernel's own reading, ``reach`` in its ``dispatch/utils.py``, by which
    ``spec_caller_input_schema`` withholds and relaxes a Validator's fields;
    that module exports nothing, so the few lines are repeated here over the
    public ``provider_keys``. A typed provider reaches its ``filled`` and its
    ``declinable`` keys; one whose return says nothing about its keys may fill
    every field and is annotated to fill none
    (test_an_untyped_input_data_requires_no_field); no provider reaches
    nothing (test_a_spec_reaching_nothing_keeps_the_author_s_component).
    """
    keys = provider_keys(provider)
    names = parameters.names()
    if keys is None:
        return frozenset(), names
    return names & keys.filled, names & (keys.filled | keys.declinable)


def _without(schema: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """``schema`` with ``names`` neither offered nor required, an empty ``required`` dropped.

    The same few lines as ``spec_options``' own: the two transports share no
    module both may import, and ``openapi/`` is opt-in, so ``views/`` never
    imports it.
    """
    dropped = frozenset(names)
    kept = {key: value for key, value in schema.items() if key != "required"}
    kept["properties"] = {
        name: fragment for name, fragment in schema["properties"].items() if name not in dropped
    }
    required = [name for name in schema.get("required", ()) if name not in dropped]
    if required:
        kept["required"] = required
    return kept


_VALIDATION_ERRORS = "ValidationErrors"


def _name_taken(holder: Any) -> ImproperlyConfigured:
    """The refusal for a serializer that components under the name this schema reserves.

    drf-spectacular only warns of two components of one name and then keeps one
    for both, so the serializer's own response, or this schema's ``400``, would
    be documented by the other's body.
    """
    owner = holder if isinstance(holder, type) else type(holder)
    return ImproperlyConfigured(
        f"{owner.__module__}.{owner.__qualname__} is documented as the component "
        f"{_VALIDATION_ERRORS!r}, the name django_spec_rest gives the body of a "
        "Validator's refusal. Name the serializer's component another way, with "
        "@extend_schema_serializer(component_name=...)."
    )


class _ValidationErrors:
    """The ``ValidationErrors`` component's identity in drf-spectacular's registry.

    The registry tells components apart by the class handed as their
    ``object``. ``ComponentIdentity`` would say this too, but it is new in
    drf-spectacular 0.28 and the floor is 0.27.
    """


_MESSAGES: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
"""A list of messages: a field's errors, and a bare ``400`` over a sentence or a list."""

_VALIDATION_ERRORS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "A refused call's errors by name, as DRF sends them: a field's list of "
        "messages, an object for a nested field, and for a list its rows' "
        "errors keyed by the row's index. A many spec's rows sit under its "
        "many argument. Messages the whole call earned are under "
        "`non_field_errors`. A service's `ServiceValidationError` over a "
        "mapping of sentences gives a sentence where a field's list would be."
    ),
    "additionalProperties": {
        "oneOf": [
            _MESSAGES,
            {"type": "string"},
            {"$ref": f"#/components/schemas/{_VALIDATION_ERRORS}"},
        ]
    },
}
"""The ``400`` body of a Validator's refusal; recursive, so no serializer can state it."""

_ROUTE_CAPTURE = re.compile(r"<(?:[^<>:]+:)?([^<>:]+)>|\(\?P<([^<>]+)>")
"""A route's captured name: a ``path()`` converter's, or a regex's named group."""


def _presents_rows(spec: KernelServiceSpec) -> bool:
    """Whether a kernel service spec presents a list of rows rather than one value.

    A re-read presents what its kind reads (a ``LIST``'s rows by
    test_a_list_re_read_presents_an_array); with none, the service's own
    return, which is rows on a ``many`` or a ``returns_many`` spec. The two
    flags are one arc to coverage, so each is named: ``many`` by
    test_a_many_spec_presents_an_array, ``returns_many`` by
    test_a_returns_many_spec_presents_an_array.
    """
    reread = spec.output_selector_spec
    if reread is not None:
        return reread.kind is SelectorKind.LIST
    return spec.many or spec.returns_many


def _presented(presenter: Presenter, *, rows: bool, wrap: bool) -> Any:
    """What ``presenter``'s body is documented by: its serializer, or its ``output_schema``.

    A ``SerializerPresenter`` is its serializer class, over a list where it
    presents ``rows``. Any other presenter is the kernel's ``output_schema`` of
    one row, an array of them where ``wrap`` asks, inside an
    ``OpenApiResponse``: a bare ``dict`` would be read as a mapping of statuses.
    """
    if isinstance(presenter, SerializerPresenter):
        return presenter.serializer_class(many=True) if rows else presenter.serializer_class
    item = output_schema(presenter.output())
    return OpenApiResponse(response=build_array_type(item) if wrap else item)


def _kernel_filter_parameters(filter_set: Any) -> list[Any]:
    """A FilterSet's OpenAPI query parameters, as the kernel reads its filters.

    One per ``filter_set_parameters`` entry, a range filter's two bounds
    included, each with the schema ``parameters_schema`` gives it under the
    edge's unknown-argument policy and its ``help`` as the parameter's
    description. An array parameter keeps OpenAPI's default ``form`` style,
    a repeated key, which the kernel's flat reader takes as it takes a comma
    list.
    """
    parameters = filter_set_parameters(filter_set)
    properties = parameters_schema(parameters, unknown_arguments=UNKNOWN_ARGUMENTS)["properties"]
    documented: list[Any] = []
    for parameter in parameters:
        schema = dict(properties[parameter.name])
        description = schema.pop("description", None)
        documented.append(
            build_parameter_type(
                name=parameter.name,
                schema=schema,
                location=OpenApiParameter.QUERY,
                required=parameter.required,
                description=description,
            )
        )
    return documented
