"""``ServiceAutoSchema`` — drf-spectacular ``AutoSchema`` aware of kernel specs.

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
from django_service_specs.schema.can_present_nothing import can_present_nothing
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_array_type, build_parameter_type
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiRequest,
    OpenApiResponse,
)
from rest_framework.serializers import Serializer

from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS
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


class ServiceAutoSchema(AutoSchema):
    """``AutoSchema`` that derives its request / response from a kernel spec.

    A kernel ``ServiceSpec`` or ``SelectorSpec`` is read off its seats, as the
    route serves it, on every surface: the standalone ``Service*View`` and
    ``Selector*View`` classes, the ``ServiceViewSet`` and ``SelectorViewSet``
    action mixins, and ``@service_action`` / ``@selector_action``:

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
      ``204`` beside it where ``can_present_nothing``.
    - **A** ``422`` is documented wherever the spec declares a Validator.
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
        test_a_many_spec_takes_an_array_of_rows). Any other Validator, or
        none, is ``_parameters_body`` (test_another_validator_is_its_parameters_schema).
        """
        variant = _partial_variant(spec) if self.method == "PATCH" else spec
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
        # A selector spec with no presenter is rendered by the view's
        # ``serializer_class``, which the base reads
        # (test_no_presenter_is_the_view_s_serializer_class).
        if selector is not None and selector.presenter is not None:
            return self._kernel_rows(selector, selector.presenter)
        return super().get_response_serializers()

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
        # A Validator's refusal is a 422
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
