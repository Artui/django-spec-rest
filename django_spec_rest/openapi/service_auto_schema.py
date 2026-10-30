"""``ServiceAutoSchema`` — drf-spectacular ``AutoSchema`` aware of ``ServiceSpec``.

Importing this module pulls in ``drf-spectacular``, so the package's top-level
``__init__.py`` does not load it; users opt in via
[`django_spec_rest.openapi.enable_openapi`][django_spec_rest.openapi.enable_openapi.enable_openapi].
"""

from __future__ import annotations

import re
from typing import Any, cast

from django_service_specs import (
    Parameters,
    Presenter,
    SelectorKind,
    filter_set_parameters,
    output_schema,
    parameters_schema,
    relax_partial,
    server_owned_keys,
)
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from drf_spectacular.contrib.django_filters import DjangoFilterExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_array_type, build_parameter_type
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiRequest,
    OpenApiResponse,
    PolymorphicProxySerializer,
)
from rest_framework.serializers import Serializer

from django_spec_rest.can_present_nothing import can_present_nothing
from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS
from django_spec_rest.dispatch.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.openapi._resolve import (
    resolve_polymorphic_spec,
    resolve_selector_spec,
    resolve_service_spec,
)
from django_spec_rest.openapi._to_serializer import to_serializer_class
from django_spec_rest.openapi.service_error_serializer import (
    ServiceErrorSerializer,
)
from django_spec_rest.openapi.utils import default_status
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.mutation.utils import status_for_a_body


class ServiceAutoSchema(AutoSchema):
    """``AutoSchema`` that derives its request / response from a ``ServiceSpec``.

    On mutation surfaces (standalone ``Service*View`` classes, the
    ``ServiceViewSet`` action mixins, and ``@service_action``):

    - Request body from ``spec.input_serializer``, a bare dataclass being auto-wrapped
      in ``DataclassSerializer``, built with whatever partial flag ``spec.partial``
      resolves to so the documented body matches what actually validates.
    - Success response from ``spec.output_selector_spec.output_serializer``,
      under the status the runtime serves a body under, which is ``200`` where
      the status is ``204``; or, where no serializer is declared, a no-content
      response at the status itself.
    - A ``422`` documenting
      [`ServiceErrorSerializer`][django_spec_rest.openapi.service_error_serializer.ServiceErrorSerializer],
      as ``spec.document_service_error`` gates it.

    Read surfaces (``Selector*View`` and the read-side action mixins) lean on
    the base ``AutoSchema`` for their body: ``output_serializer`` is already
    wired through ``get_serializer_class()``, which is what drf-spectacular
    reads natively. The one addition is ``_get_filter_parameters``,
    contributing the query parameters for a ``SelectorSpec.filter_set``, so
    moving a FilterSet from a view-level ``filterset_class`` +
    ``DjangoFilterBackend`` onto ``spec.filter_set`` leaves the generated
    OpenAPI unchanged.

    A kernel ``ServiceSpec`` or ``SelectorSpec`` is read off its seats, as the
    kernel route serves it:

    - **The request body** is a ``SerializerValidator``'s serializer, so its
      component is drf-spectacular's name for the author's class, built partial
      exactly where the route dispatches the spec's partial variant
      (``kernel_spec_variant``): a ``PATCH``, unless the Validator cannot take a
      partial call, and a spec declaring ``partial``. A ``many`` spec takes a
      list of those rows. Any other Validator is the kernel's
      ``parameters_schema`` over what the body carries (``_parameters_body``).
    - **The response body** is a ``SerializerPresenter``'s serializer, or any
      other presenter's ``output_schema``, a list of rows where the spec
      presents rows (``_presents_rows``). A spec with no presenter documents
      the no-content response, and a selector spec with none keeps the base's
      reading of the view's ``serializer_class``, which renders it.
    - **The status** is the view's ``success_status`` where it is an ``int``,
      since a kernel spec declares none, over the action's default; a body is
      documented as the ``200`` it is served as where that is ``204``, and the
      ``204`` beside it where ``can_present_nothing``, as for a drfs spec.
    - **A** ``422`` is documented wherever the spec declares a Validator, the
      drfs default, since a kernel spec has no ``document_service_error``.
    - **A FilterSet's query parameters** are the kernel's
      ``filter_set_parameters``, on a list operation only, as above.

    User-supplied ``@extend_schema`` annotations always win, and
    ``@extend_schema(parameters=...)`` merges over the filter parameters exactly
    as it does for a view-level FilterSet.
    """

    def get_request_serializer(self) -> Any:
        spec = resolve_service_spec(self.view)
        if isinstance(spec, KernelServiceSpec):
            return self._kernel_request_body(spec)
        poly = resolve_polymorphic_spec(self.view)
        if poly is not None:
            proxy = self._polymorphic_request_serializer(poly)
            if proxy is not None:
                return proxy
        if spec is not None:
            cls = to_serializer_class(spec.input_serializer)
            if cls is not None:
                if spec.partial is not None:
                    partial = spec.partial
                else:
                    partial = getattr(self.view, "action", None) == "partial_update"
                return cls(partial=partial)
        return super().get_request_serializer()

    def _polymorphic_request_serializer(self, poly: Any) -> Any:
        """Render a polymorphic action's request body as the variant union.

        A ``PolymorphicProxySerializer`` over each variant's ``input_serializer``
        with ``resource_type_field_name=None`` — an ``anyOf``, since the
        framework discriminates on payload content rather than a type field.
        Variants without an ``input_serializer`` contribute nothing; with none
        at all, defer to the base body.
        """
        serializers = [
            cls()
            for cls in (to_serializer_class(v.input_serializer) for v in poly.specs.values())
            if cls is not None
        ]
        if not serializers:
            return None
        view_name = type(self.view).__name__
        action_name = getattr(self.view, "action", "") or ""
        return PolymorphicProxySerializer(
            component_name=f"{view_name}_{action_name}_Request",
            serializers=serializers,
            resource_type_field_name=None,
        )

    def _kernel_request_body(self, spec: KernelServiceSpec) -> Any:
        """What a kernel ``spec``'s request body is documented by, or ``None`` for no body.

        Read off the variant the route dispatches for this method, so the
        documented body is the one validated: a ``PATCH`` asks for the partial
        variant, which is the spec itself where its Validator cannot take a
        partial call. A ``SerializerValidator`` is its serializer, built
        partial as the variant is and over a list for a ``many`` spec
        (test_a_patch_is_documented_partial,
        test_a_patch_a_dataclass_validates_whole_is_documented_whole,
        test_a_many_spec_takes_an_array_of_rows). Any other Validator, or
        none, is ``_parameters_body`` (test_another_validator_is_its_parameters_schema).
        """
        # The variant of a service spec is a service spec; the function is
        # annotated for both kinds it compiles.
        variant = cast(
            "KernelServiceSpec",
            kernel_spec_variant(spec, partial=True if self.method == "PATCH" else None),
        )
        validator = variant.validator
        if isinstance(validator, SerializerValidator):
            serializer = renderable_serializer_class(validator.serializer)
            return serializer(many=variant.many, partial=variant.partial)
        return self._parameters_body(variant)

    def _parameters_body(self, spec: KernelServiceSpec) -> Any:
        """The kernel's ``parameters_schema`` over what ``spec``'s body carries, or ``None``.

        ``spec.parameters()`` relaxed as dispatch relaxes a partial call
        (test_another_validator_s_patch_requires_nothing), less every name the
        body does not choose: the target lookup's reads, which name the row
        and never come from the body (test_the_target_s_reads_are_no_body_key);
        the names the server fills, ``server_owned_keys``; and the route's
        captures, which outrank the body's value
        (test_a_route_capture_and_a_provider_s_key_are_no_body_key holds those
        two). Built under the edge's unknown-argument policy, so the body is
        closed exactly where dispatch closes it. A ``many`` spec's body is the
        list itself, which the edge reads under its ``many_argument``
        (test_a_many_spec_over_another_validator_takes_an_array_of_its_rows).

        Handed to drf-spectacular as an ``OpenApiRequest``, which it renders as
        the schema given: a bare ``dict`` would be read as a mapping of media
        types.
        """
        target = spec.target_selector_spec()
        dropped = (
            server_owned_keys(spec)
            | (target.parameters().names() if target is not None else frozenset())
            | frozenset(self._route_captures())
        )
        kept = Parameters.of(
            *(p for p in relax_partial(spec, spec.parameters()) if p.name not in dropped)
        )
        if not len(kept):
            return None
        schema = parameters_schema(kept, unknown_arguments=UNKNOWN_ARGUMENTS)
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

    def _get_request_for_media_type(self, serializer: Any, direction: str = "request") -> Any:
        if isinstance(resolve_service_spec(self.view), KernelServiceSpec):
            # The one method this step reads is ``PATCH``, whose serializer
            # drf-spectacular re-stamps partial, where the route validates one
            # whole when its Validator cannot take a partial call.
            # ``_kernel_request_body`` has already built the serializer as
            # partial as the route validates, under the real method, so this
            # step is presented as a ``POST`` for every method
            # (test_a_patch_a_dataclass_validates_whole_is_documented_whole).
            saved = self.method
            self.method = "POST"
            try:
                return super()._get_request_for_media_type(serializer, direction)
            finally:
                self.method = saved
        return super()._get_request_for_media_type(serializer, direction)

    def _get_request_body(self, direction: str = "request") -> Any:
        spec = resolve_service_spec(self.view)
        if isinstance(spec, KernelServiceSpec):
            if self.method != "DELETE":
                return super()._get_request_body(direction)
            # drf-spectacular documents no body on a ``DELETE``, and a kernel
            # spec's is whatever ``_kernel_request_body`` reads, none included,
            # so the call is presented as a ``POST``, which no body depends on
            # (test_a_delete_with_a_validator_documents_its_body,
            # test_a_spec_taking_nothing_documents_no_body). A ``PATCH`` is
            # ``_get_request_for_media_type``'s.
            return self._as_method("POST", direction)
        # drf-spectacular hard-codes the body verbs to PUT/PATCH/POST. RFC 7231
        # permits a body on DELETE and ``ServiceDeleteView`` /
        # ``ServiceDestroyMixin`` use it, so swap ``self.method`` for the
        # duration of the super call to coax the body out.
        if self.method == "DELETE" and spec is not None and spec.input_serializer is not None:
            return self._as_method("POST", direction)
        # spectacular unconditionally re-stamps ``partial=True`` on PATCH
        # request serializers, which would override a forced
        # ``spec.partial=False``; presenting the call as PUT keeps the
        # full-update schema.
        if (
            self.method == "PATCH"
            and spec is not None
            and spec.partial is False
            and spec.input_serializer is not None
        ):
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
        if isinstance(spec, KernelServiceSpec):
            return self._kernel_responses(spec)
        if spec is None:
            selector = resolve_selector_spec(self.view)
            # A kernel selector spec with no presenter is rendered by the
            # view's ``serializer_class``, which the base reads
            # (test_no_presenter_is_the_view_s_serializer_class).
            if isinstance(selector, KernelSelectorSpec) and selector.presenter is not None:
                return self._kernel_rows(selector, selector.presenter)
            return super().get_response_serializers()
        # A callable ``success_status`` keys on the per-request result, so it
        # can't be resolved statically; document the action default instead.
        status = (
            spec.success_status
            if isinstance(spec.success_status, int)
            else default_status(self.view)
        )
        output_serializer = (
            spec.output_selector_spec.output_serializer
            if spec.output_selector_spec is not None
            else None
        )
        out_cls = to_serializer_class(output_serializer)
        # spectacular accepts a Serializer subclass *or* an OpenApiResponse per
        # status entry; mix them by whether a response body is configured. A
        # declared serializer is a body, and the renderers answer a body under
        # ``status_for_a_body``, so the schema asks it the same question rather
        # than restating the answer: a destroy presenting a row, single-row or
        # bulk, is documented as the ``200`` it is served as. Held by
        # test_a_destroy_documents_the_response_it_serves.
        #
        # With no serializer declared there is no body the schema can describe,
        # and whether the runtime sends one is decided by what the service
        # returns, which nothing the schema reads declares. So the no-content
        # response is documented at the status itself, which is what a destroy
        # whose service returns ``None`` is answered with. A raw value returned
        # instead, a count say, is served as a body under ``status_for_a_body``
        # that the schema does not show. Held by
        # test_an_undeclared_body_is_documented_as_no_content.
        responses: dict[Any, Any] = (
            {status_for_a_body(status): out_cls}
            if out_cls is not None
            else {status: OpenApiResponse(description="")}
        )
        # A declared body is not always sent. Where dispatch may present nothing,
        # a re-read finding no row say, the renderers answer an empty ``204``
        # rather than a row of blank fields, so the schema documents that response
        # beside the body, asking ``can_present_nothing`` as every transport does.
        # The body is never documented under ``204`` itself (``status_for_a_body``),
        # so the two never collide. Without a serializer the empty response is
        # already the one documented, at its status. One arc to coverage, so each
        # operand names its test: the serializer,
        # test_an_undeclared_body_is_documented_at_its_status_alone, and the
        # question, test_a_create_that_cannot_present_nothing_documents_no_204.
        # test_a_create_that_may_present_nothing_documents_its_empty_204 holds
        # the branch.
        #
        # The rule is the spec's answer, and over-documents in three cases the
        # OpenAPI page states, because the renderers decide the empty answer from
        # more than the spec, inline rather than through a function this could
        # ask: an explicit ``success_status`` with nothing to re-read answers empty
        # at that status; an update that renders its target in place never answers
        # empty; and the bulk path answers empty at the action's status. Where that
        # status is the body's, one response per status could not tell the two
        # apart anyway. Each is held, the status served beside the statuses
        # documented, by
        # test_an_empty_answer_at_an_explicit_status_is_documented_as_204_too,
        # test_an_update_rendering_its_target_in_place_is_documented_with_a_204 and
        # test_a_bulk_spec_answers_empty_at_its_status_beside_a_documented_204.
        if out_cls is not None and can_present_nothing(spec):
            responses[204] = OpenApiResponse(description="")
        document_422 = (
            spec.document_service_error
            if spec.document_service_error is not None
            else spec.input_serializer is not None
        )
        if document_422:
            responses[422] = ServiceErrorSerializer
        return responses

    def _kernel_responses(self, spec: KernelServiceSpec) -> dict[Any, Any]:
        """A kernel service spec's responses, by the rules the drfs branch above states.

        The status is the view's own ``success_status``, the hook the kernel
        route answers with (``MutationFlowMixin``), where it is an ``int``; a
        callable keys on the result, so the action's default stands
        (test_the_view_s_status_is_documented,
        test_a_callable_status_documents_the_action_s_default). The body is
        the presenter the kernel's ``present`` renders with,
        ``presenter_for_output()``. The ``204`` beside a body is the drfs
        branch's arc, asked of the kernel spec; its operands are held here by
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
        # A kernel spec declares no ``document_service_error``, so the drfs
        # default is the rule: a Validator, whose refusal is a 422
        # (test_a_service_error_is_documented_where_there_is_a_validator).
        if spec.validator is not None:
            responses[422] = ServiceErrorSerializer
        return responses

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
        if isinstance(spec, KernelSelectorSpec):
            if spec.filter_set is None:
                return parameters
            return parameters + _kernel_filter_parameters(spec.filter_set)
        if spec is None or spec.selector is None or spec.filter_set is None:
            return parameters
        return parameters + _filter_set_parameters(self, spec.filter_set)


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


class _SpecFilterBackend:
    """Minimal stand-in exposing the one method ``DjangoFilterExtension`` calls.

    The extension resolves its FilterSet solely through
    ``self.target.get_filterset_class(view, queryset)``, so returning
    ``filter_set`` reproduces what a real ``DjangoFilterBackend`` with
    ``view.filterset_class`` would — without importing ``django-filter`` or
    mutating the inspected view.
    """

    def __init__(self, filter_set: Any) -> None:
        self._filter_set = filter_set

    def get_filterset_class(self, view: Any, queryset: Any = None) -> Any:
        return self._filter_set


def _filter_set_parameters(auto_schema: AutoSchema, filter_set: Any) -> list[Any]:
    """OpenAPI query parameters for a spec-level ``filter_set``.

    Reuses drf-spectacular's own ``DjangoFilterExtension``, so the output is
    byte-identical to a view-level ``filterset_class`` + ``DjangoFilterBackend``
    (same param names, types, enums, style / explode, required flags) and stays
    in lockstep across versions. The extension imports ``django-filter`` only
    lazily, inside its per-field resolution, so it is safe to import at module
    top with the rest of the drf-spectacular surface.

    ``SelectorSpec.filter_set`` is applied by the ``(data, queryset) -> .qs``
    contract and need not be a real ``FilterSet``, so anything without
    ``base_filters`` — a filter_set carried without the ``[filter]`` extra
    installed — degrades to no parameters rather than raising, the same posture
    ``filterset_to_json_schema`` takes.
    """
    if not hasattr(filter_set, "base_filters"):
        return []
    extension = DjangoFilterExtension(_SpecFilterBackend(filter_set))
    return list(extension.get_schema_operation_parameters(auto_schema))
