from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Presenter,
    SelectorKind,
    Unrestricted,
    filter_set_parameters,
    output_schema,
    parameters_schema,
    provider_keys,
    spec_caller_input_schema,
)
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.can_present_nothing import can_present_nothing
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.build_call_context import build_call_context
from drf_spectacular.drainage import warn
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import (
    ResolvedComponent,
    build_array_type,
    build_parameter_type,
    force_instance,
    get_view_model,
    resolve_django_path_parameter,
    resolve_regex_path_parameter,
)
from drf_spectacular.settings import spectacular_settings
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiRequest,
    OpenApiResponse,
)
from rest_framework.serializers import Serializer
from rest_framework.settings import api_settings
from rest_framework.status import HTTP_204_NO_CONTENT

from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS
from django_spec_rest.openapi._caller_serializer_class import caller_serializer_class
from django_spec_rest.openapi._lowered_for_the_document import lowered_for_the_document
from django_spec_rest.openapi._resolve import (
    resolve_discriminated_action,
    resolve_selector_spec,
    resolve_service_spec,
)
from django_spec_rest.openapi.not_authenticated_serializer import NotAuthenticatedSerializer
from django_spec_rest.openapi.permission_denied_serializer import PermissionDeniedSerializer
from django_spec_rest.openapi.service_error_metadata_key import SERVICE_ERROR_METADATA_KEY
from django_spec_rest.openapi.service_error_serializer import (
    ServiceErrorSerializer,
)
from django_spec_rest.openapi.service_validation_error_serializer import (
    ServiceValidationErrorSerializer,
)
from django_spec_rest.openapi.utils import (
    RESERVED_COMPONENTS,
    VALIDATION_ERRORS,
    ValidationErrorsIdentity,
    default_status,
    is_a,
    name_taken,
    place,
    serializer_named,
)
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.types.rest_transport import REST_TRANSPORT
from django_spec_rest.views.mutation.utils import status_for_a_body
from django_spec_rest.views.utils import action_answer, view_pool_seeds


class ServiceAutoSchema(AutoSchema):
    """``AutoSchema`` that derives its request / response from a kernel spec."""

    def is_excluded(self) -> bool:
        """Whether this method is left out, as ``Allow`` or drf-spectacular leaves it out."""
        refuses = getattr(self.view, "_refuses_without_a_spec", None)
        if refuses is not None and refuses(self.method):
            return True
        return super().is_excluded()

    def get_request_serializer(self) -> Any:
        spec = resolve_service_spec(self.view)
        if spec is not None:
            return self._kernel_request_body(spec)
        action = resolve_discriminated_action(self.view)
        if action is not None:
            return self._discriminated_request_body(action)
        return super().get_request_serializer()

    def _kernel_request_body(self, spec: KernelServiceSpec) -> Any:
        """What a kernel ``spec``'s request body is documented by, or ``None`` for no body."""
        variant = self._dispatched(spec)
        validator = variant.validator
        if isinstance(validator, SerializerValidator):
            serializer = cast(
                "type[Serializer[Any]]", renderable_serializer_class(validator.serializer)
            )
            owned, reached = _input_data_reach(variant.input_data, validator.parameters())
            if reached:
                serializer = caller_serializer_class(
                    serializer,
                    self._get_serializer_name(serializer(), "response"),
                    owned=owned,
                    relaxed=reached - owned,
                )
            return serializer(many=variant.many, partial=variant.partial)
        return self._parameters_body(variant)

    def _dispatched(self, spec: KernelServiceSpec) -> KernelServiceSpec:
        """The variant of ``spec`` this route dispatches for this method."""
        if self.method == "PATCH" and not _is_decorated_action(self.view):
            return _partial_variant(spec)
        return spec

    def _parameters_body(self, spec: KernelServiceSpec) -> Any:
        """The caller schema of ``spec`` less what the body does not choose, or ``None``."""
        schema = self._caller_schema(spec)
        if not schema["properties"]:
            return None
        demanded = bool(schema.get("required"))
        if spec.many:
            schema = schema["properties"][spec.many_argument]
        schema = lowered_for_the_document(schema)
        return OpenApiRequest(_DemandedBody(schema) if demanded else schema)

    def _caller_schema(self, spec: KernelServiceSpec) -> dict[str, Any]:
        """What a caller sends ``spec`` as an object: the kernel's, less this transport's."""
        target = spec.target_selector_spec()
        return _without(
            spec_caller_input_schema(
                spec,
                pool_seeds=view_pool_seeds(self.view),
                unknown_arguments=UNKNOWN_ARGUMENTS,
                call_context=build_call_context(
                    REST_TRANSPORT,
                    view=self.view,
                    action=getattr(self.view, "action", None),
                ),
            ),
            (target.parameters().names() if target is not None else frozenset())
            | frozenset(self._route_captures()),
        )

    def _discriminated_request_body(self, action: DiscriminatedAction) -> Any:
        """A ``DiscriminatedAction``'s request: an ``anyOf`` over its variants' bodies."""
        members: list[dict[str, Any]] = []
        for variant in action.specs.values():
            member = self._variant_body(variant)
            if member is not None and member not in members:
                members.append(member)
        if not members:
            return None
        demanded = all(
            self._caller_schema(self._dispatched(variant)).get("required")
            for variant in action.specs.values()
        )
        view_name, action_name = type(self.view).__name__, getattr(self.view, "action", None)
        name = f"{view_name}_{action_name}_Request"
        any_of = {"anyOf": members}
        component = ResolvedComponent(
            name=name,
            type=ResolvedComponent.SCHEMA,
            object=DiscriminatedAction,
            schema=any_of,
        )
        self.registry.register_on_missing(component)
        if self.registry[component].schema != component.schema:
            warn(
                f"{view_name}.{action_name} documents a different request than the component "
                f"{name!r} already holds, so its request is given inline. Name the views "
                "differently to give each its own component."
            )
            return OpenApiRequest(_DemandedBody(any_of) if demanded else any_of)
        return OpenApiRequest(_DemandedBody(component.ref) if demanded else component.ref)

    def _variant_body(self, spec: KernelServiceSpec) -> dict[str, Any] | None:
        """One variant's member of the request ``anyOf``, or ``None`` where it takes no body."""
        if not self._caller_schema(spec)["properties"]:
            return None
        body = self._kernel_request_body(spec)
        if isinstance(body, OpenApiRequest):
            return cast("dict[str, Any]", body.request)
        return cast("dict[str, Any]", self._unwrap_list_serializer(body, "request"))

    def _route_captures(self) -> list[str]:
        """The names the inspected route captures, as the view's ``kwargs`` carry them."""
        return [converter or group for converter, group in _ROUTE_CAPTURE.findall(self.path_regex)]

    def _get_request_body(self, direction: str = "request") -> Any:
        spec = resolve_service_spec(self.view)
        if spec is None and resolve_discriminated_action(self.view) is None:
            return super()._get_request_body(direction)
        if self.method == "DELETE":
            # drf-spectacular documents no body on a DELETE, so the call is shown as a POST.
            return self._as_method("POST", direction)
        if spec is not None and self.method == "PATCH" and not self._dispatched(spec).partial:
            return self._as_method("PUT", direction)
        return super()._get_request_body(direction)

    def _get_request_for_media_type(self, serializer: Any, direction: Any = "request") -> Any:
        """The base's schema of one media type, stating ``required`` where a body is demanded."""
        schema, required = super()._get_request_for_media_type(serializer, direction)
        return schema, required or isinstance(serializer, _DemandedBody)

    def _as_method(self, method: str, direction: str) -> Any:
        """The base's request body, asked as if the operation were ``method``."""
        saved = self.method
        self.method = method
        try:
            return super()._get_request_body(direction)
        finally:
            self.method = saved

    def _get_response_bodies(self, direction: Any = "response") -> Any:
        """The responses rendered, with ``@extend_schema(responses=...)`` added to the spec's."""
        beneath = _under_extend_schema(type(self))
        if beneath is None:
            return super()._get_response_bodies(direction)
        own = beneath.get_response_serializers(self)
        if not isinstance(own, dict):
            return super()._get_response_bodies(direction)
        declared = self.get_response_serializers()
        if not isinstance(declared, dict):
            lead = next((code for code in own if _success_with_a_body(code)), None)
            declared = {} if lead is None else {lead: declared}
        responses: dict[str, Any] = {}
        for code, serializer in _merged(own, declared).items():
            if isinstance(code, tuple):
                code, media_types = str(code[0]), code[1:]
            else:
                code, media_types = str(code), None
            rendered = self._get_response_for_code(serializer, code, media_types, direction)
            if code in responses:
                responses[code]["content"].update(rendered["content"])
            else:
                responses[code] = rendered
        return responses

    def get_response_serializers(self) -> Any:
        spec = resolve_service_spec(self.view)
        if spec is not None:
            return self._kernel_responses(spec)
        action = resolve_discriminated_action(self.view)
        if action is not None:
            return self._discriminated_responses(action)
        selector = resolve_selector_spec(self.view)
        if selector is not None:
            return self._kernel_selector_responses(selector)
        return super().get_response_serializers()

    def _kernel_selector_responses(self, spec: KernelSelectorSpec) -> dict[Any, Any]:
        """A kernel selector spec's responses: its body, then the refusals the edge sends."""
        body = (
            self._kernel_rows(spec, spec.presenter)
            if spec.presenter is not None
            else super().get_response_serializers()
        )
        responses: dict[Any, Any] = {200: body}
        if spec.parameters():
            responses[400] = self._validation_errors_response()
        responses.update(self._caller_refusals(spec))
        if self.documents_service_error(spec):
            responses[422] = ServiceErrorSerializer
        return responses

    def _kernel_responses(self, spec: KernelServiceSpec) -> dict[Any, Any]:
        """A kernel service spec's responses."""
        declared = action_answer(self.view, "success_status")
        status = declared if isinstance(declared, int) else default_status(self.view)
        presenter = spec.presenter_for_output()
        rows = _presents_rows(spec)
        body = None if presenter is None else _presented(presenter, rows=rows, wrap=rows)
        no_content = HTTP_204_NO_CONTENT if declared is None else status
        responses: dict[Any, Any] = (
            {status_for_a_body(status): body}
            if body is not None
            else {
                status: OpenApiResponse(description=""),
                no_content: OpenApiResponse(description=""),
            }
        )
        if body is not None and can_present_nothing(spec):
            responses.setdefault(no_content, OpenApiResponse(description=""))
        if spec.validator is not None:
            responses[400] = self._validation_errors_response()
        responses.update(self._caller_refusals(spec))
        if self.documents_service_error(spec):
            responses[422] = ServiceErrorSerializer
        return responses

    def _discriminated_responses(self, action: DiscriminatedAction) -> dict[Any, Any]:
        """A ``DiscriminatedAction``'s responses: each variant's, merged per status."""
        answers = [self._kernel_responses(variant) for variant in action.specs.values()]
        statuses = dict.fromkeys(status for answered in answers for status in answered)
        responses: dict[Any, Any] = {
            status: self._one_response(
                [answered[status] for answered in answers if status in answered]
            )
            for status in statuses
        }
        responses.setdefault(400, self._validation_errors_response())
        return responses

    def _one_response(self, answers: list[Any]) -> Any:
        """The documented response of one status that several variants answer."""
        bodies = [
            (answer, schema)
            for answer in answers
            if (schema := self._response_schema(answer)) is not None
        ]
        if not bodies:
            return answers[0]
        distinct: list[dict[str, Any]] = []
        for _, schema in bodies:
            if schema not in distinct:
                distinct.append(schema)
        if len(distinct) == 1:
            return bodies[0][0]
        return OpenApiResponse(response={"anyOf": distinct})

    def _response_schema(self, answer: Any) -> dict[str, Any] | None:
        """The schema a ``_kernel_responses`` entry documents, or ``None`` for no body."""
        body = answer.response if isinstance(answer, OpenApiResponse) else answer
        if body is None:
            return None
        if isinstance(body, dict):
            return body
        return cast(
            "dict[str, Any]", self._unwrap_list_serializer(force_instance(body), "response")
        )

    def documents_service_error(self, spec: KernelServiceSpec | KernelSelectorSpec) -> bool:
        """Whether this operation documents the ``422`` a plain ``ServiceError`` gets."""
        declared = (spec.metadata or {}).get(SERVICE_ERROR_METADATA_KEY, False)
        if not isinstance(declared, bool):
            raise ImproperlyConfigured(
                f"{type(self.view).__name__}'s spec metadata[{SERVICE_ERROR_METADATA_KEY!r}] "
                f"must be True or False; got {type(declared).__name__}."
            )
        return declared

    def _caller_refusals(self, spec: KernelServiceSpec | KernelSelectorSpec) -> dict[int, Any]:
        """The ``403`` a spec's checks refuse with, and the ``401`` DRF asks to sign in."""
        checks = spec.permissions or ()
        if all(isinstance(check, Unrestricted) for check in checks):
            return {}
        refusals: dict[int, Any] = {
            403: OpenApiResponse(
                response=PermissionDeniedSerializer,
                description="The caller may not run this operation.",
            )
        }
        if self.view.get_authenticate_header(self.view.request):
            refusals[401] = OpenApiResponse(
                response=NotAuthenticatedSerializer,
                description=(
                    "No caller was authenticated. The WWW-Authenticate header names "
                    "the scheme to authenticate with."
                ),
            )
        return refusals

    def _validation_errors_response(self) -> OpenApiResponse:
        """A Validator's ``400``: a ``ValidationErrors`` tree, a ``detail`` or a list."""
        component = ResolvedComponent(
            name=VALIDATION_ERRORS,
            type=ResolvedComponent.SCHEMA,
            object=ValidationErrorsIdentity,
            schema=_VALIDATION_ERRORS_SCHEMA,
        )
        try:
            holder = self.registry[component].object
        except KeyError:
            self.registry.register_on_missing(component)
        else:
            if holder is not ValidationErrorsIdentity:
                raise name_taken(serializer_named(holder), VALIDATION_ERRORS)
        detail = self.resolve_serializer(ServiceErrorSerializer, "response")
        return OpenApiResponse(
            response={"anyOf": [place(self.registry, component.ref), detail.ref, _MESSAGES]},
        )

    def resolve_serializer(self, serializer: Any, *args: Any, **kwargs: Any) -> Any:
        # Passed whole: ``bypass_extensions`` is absent from some releases the floor admits.
        resolved = super().resolve_serializer(serializer, *args, **kwargs)
        reserved = RESERVED_COMPONENTS.get(resolved.name)
        if reserved is not None:
            asked = is_a(serializer, reserved.owner)
            if asked != is_a(resolved.object, reserved.owner):
                raise name_taken(
                    serializer_named(resolved.object if asked else serializer), resolved.name
                )
        return resolved

    def _kernel_rows(self, spec: KernelSelectorSpec, presenter: Presenter) -> Any:
        """A kernel selector spec's body: one row, or every row for a ``LIST``."""
        rows = spec.kind is SelectorKind.LIST
        wrap = rows and not self._is_list_view(Serializer())
        return _presented(presenter, rows=rows, wrap=wrap)

    def _resolve_path_parameters(self, variables: list[str]) -> list[Any]:
        """Each path variable's parameter: drf-spectacular's, or the read a spec declares for it."""
        if get_view_model(self.view, emit_warnings=False) is not None:
            return super()._resolve_path_parameters(variables)
        reads = _route_reads(self.view)
        captures = self._route_captures()
        declared = {
            variable: reads[name]
            for variable in variables
            if (name := _capture_named(variable, captures)) in reads
            and not self._typed_by_the_path(variable)
        }
        theirs = super()._resolve_path_parameters([v for v in variables if v not in declared])
        by_name = {parameter["name"]: parameter for parameter in theirs}
        return [
            _declared_path_parameter(variable, declared[variable])
            if variable in declared
            else by_name[variable]
            for variable in variables
        ]

    def _typed_by_the_path(self, variable: str) -> bool:
        """Whether the route types ``variable`` itself: a ``path()`` converter or a regex's."""
        return bool(
            resolve_django_path_parameter(self.path_regex, variable, self.map_renderers("format"))
            or resolve_regex_path_parameter(self.path_regex, variable)
        )

    def _get_filter_parameters(self) -> list[Any]:
        # The spec's FilterSet drops ``DjangoFilterBackend``, else its parameters silently vanish.
        parameters = super()._get_filter_parameters()
        if not self._is_list_view():
            return parameters
        spec = resolve_selector_spec(self.view)
        if spec is None or spec.filter_set is None:
            return parameters
        return parameters + _kernel_filter_parameters(spec.filter_set)


def _route_reads(view: Any) -> dict[str, Parameter]:
    """The reads the operation's spec declares, by name: those a route capture may fill."""
    selector = resolve_selector_spec(view)
    if selector is not None:
        return {parameter.name: parameter for parameter in selector.parameters().items}
    service = resolve_service_spec(view)
    action = resolve_discriminated_action(view)
    served = (
        tuple(action.specs.values())
        if action is not None
        else (() if service is None else (service,))
    )
    reads: dict[str, Parameter] = {}
    for spec in served:
        target = spec.target_selector_spec()
        found = () if target is None else target.parameters().items
        for parameter in {p.name: p for p in (*found, *spec.reads.items)}.values():
            reads.setdefault(parameter.name, parameter)
    return reads


def _capture_named(variable: str, captures: list[str]) -> str | None:
    """The route capture a documented path ``variable`` stands for, or ``None``."""
    return {_documented_as(capture): capture for capture in captures}.get(variable)


def _documented_as(capture: str) -> str:
    """The name the documented path gives a route ``capture``."""
    if capture == "pk" and api_settings.SCHEMA_COERCE_PATH_PK:
        return "id"
    if capture.endswith("_pk") and spectacular_settings.SCHEMA_COERCE_PATH_PK_SUFFIX:
        return f"{capture[:-3]}_id"
    return capture


def _declared_path_parameter(variable: str, read: Parameter) -> Any:
    """``variable`` as a path parameter, typed by the ``read`` a spec declares for it."""
    schema = dict(
        parameters_schema(Parameters.of(read), unknown_arguments=UNKNOWN_ARGUMENTS)["properties"][
            read.name
        ]
    )
    description = schema.pop("description", None)
    schema = dict(lowered_for_the_document(schema))
    if "enum" in schema:
        present = [value for value in schema["enum"] if value is not None]
        if present:
            schema["enum"] = present
        else:
            del schema["enum"]
    return build_parameter_type(
        name=variable,
        schema=schema,
        location=OpenApiParameter.PATH,
        description=description,
    )


def _is_decorated_action(view: Any) -> bool:
    """Whether ``view`` serves this by a ``@service_action``, which takes no partial call."""
    action = getattr(view, "action", None)
    return isinstance(action, str) and hasattr(getattr(view, action, None), "_service_spec")


def _partial_variant(spec: KernelServiceSpec) -> KernelServiceSpec:
    """The variant the route dispatches ``spec`` as for a ``PATCH``: partial where it can be."""
    return cast("KernelServiceSpec", kernel_spec_variant(spec, partial=True))


def _input_data_reach(
    provider: Callable[..., Any] | None, parameters: Parameters
) -> tuple[frozenset[str], frozenset[str]]:
    """The ``parameters`` that ``provider`` is annotated to fill, or may fill."""
    keys = provider_keys(provider)
    names = parameters.names()
    if keys is None:
        return frozenset(), names
    return names & keys.filled, names & (keys.filled | keys.declinable)


def _without(schema: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """``schema`` with ``names`` neither offered nor required, an empty ``required`` dropped."""
    dropped = frozenset(names)
    kept = {key: value for key, value in schema.items() if key != "required"}
    kept["properties"] = {
        name: fragment for name, fragment in schema["properties"].items() if name not in dropped
    }
    required = [name for name in schema.get("required", ()) if name not in dropped]
    if required:
        kept["required"] = required
    return kept


class _DemandedBody(dict[str, Any]):
    """A request schema the wire refuses an empty body for: the document says ``required``."""


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
            {"$ref": f"#/components/schemas/{VALIDATION_ERRORS}"},
        ]
    },
}
"""The ``400`` body of a Validator's refusal; recursive, so no serializer can state it."""

_EXTEND_SCHEMA_MODULE = "drf_spectacular.utils"

_ROUTE_CAPTURE = re.compile(r"<(?:[^<>:]+:)?([^<>:]+)>|\(\?P<([^<>]+)>")
"""A route's captured name: a ``path()`` converter's, or a regex's named group."""


def _presents_rows(spec: KernelServiceSpec) -> bool:
    """Whether a kernel service spec presents a list of rows rather than one value."""
    reread = spec.output_selector_spec
    if reread is not None:
        return reread.kind is SelectorKind.LIST
    return spec.many or spec.returns_many


def _presented(presenter: Presenter, *, rows: bool, wrap: bool) -> Any:
    """What ``presenter``'s body is documented by: its serializer, or its ``output_schema``."""
    if isinstance(presenter, SerializerPresenter):
        return presenter.serializer_class(many=True) if rows else presenter.serializer_class
    item = lowered_for_the_document(output_schema(presenter.output()))
    return OpenApiResponse(response=build_array_type(item) if wrap else item)


def _kernel_filter_parameters(filter_set: Any) -> list[Any]:
    """A FilterSet's OpenAPI query parameters, as the kernel reads its filters."""
    parameters = filter_set_parameters(filter_set)
    properties = parameters_schema(parameters, unknown_arguments=UNKNOWN_ARGUMENTS)["properties"]
    documented: list[Any] = []
    for parameter in parameters:
        schema = dict(properties[parameter.name])
        description = schema.pop("description", None)
        documented.append(
            build_parameter_type(
                name=parameter.name,
                schema=lowered_for_the_document(schema),
                location=OpenApiParameter.QUERY,
                required=parameter.required,
                description=description,
            )
        )
    return documented


def _merged(own: dict[Any, Any], declared: dict[Any, Any]) -> dict[Any, Any]:
    """``declared`` over ``own``: a declared status replaces it; ``2xx`` is any success."""
    statuses = {_status(code) for code in declared}
    success = any(status.startswith("2") for status in statuses)
    kept = {
        code: response
        for code, response in own.items()
        if _status(code) not in statuses and not (success and _status(code).startswith("2"))
    }
    return {**kept, **declared}


def _is_extend_schema(schema_type: type) -> bool:
    """Whether ``schema_type`` is drf-spectacular's ``extend_schema`` subclass."""
    return (
        schema_type.__module__ == _EXTEND_SCHEMA_MODULE and schema_type.__name__ == "ExtendedSchema"
    )


def _under_extend_schema(schema_type: type) -> type[AutoSchema] | None:
    """The class whose ``get_response_serializers`` a schema's is laid over, or ``None``."""
    answering = [cls for cls in schema_type.__mro__ if "get_response_serializers" in vars(cls)]
    if not _is_extend_schema(answering[0]):
        return None
    return cast("type[AutoSchema]", next(cls for cls in answering if not _is_extend_schema(cls)))


def _success_with_a_body(code: Any) -> bool:
    """Whether a ``responses`` key is a success the edge sends a body with: never a ``204``."""
    status = _status(code)
    return status.startswith("2") and status != str(HTTP_204_NO_CONTENT)


def _status(code: Any) -> str:
    """The status a key of a ``responses`` mapping names, as drf-spectacular spells it."""
    return str(code[0] if isinstance(code, tuple) else code)


class _ServiceValidationErrorExtension(OpenApiSerializerExtension):
    """Renders ``ServiceValidationErrorSerializer`` as the body DRF sends for that error."""

    target_class = ServiceValidationErrorSerializer

    def get_name(self, auto_schema: Any, direction: Any) -> str:
        return _SERVICE_VALIDATION_ERROR

    def map_serializer(self, auto_schema: Any, direction: Any) -> dict[str, Any]:
        member = {
            "anyOf": [
                {"type": "string"},
                {"$ref": f"#/components/schemas/{_SERVICE_VALIDATION_ERROR}"},
            ]
        }
        return {
            "description": inspect.cleandoc(ServiceValidationErrorSerializer.__doc__ or ""),
            "anyOf": [
                {"type": "array", "items": member},
                {"type": "object", "additionalProperties": member},
            ],
        }


_SERVICE_VALIDATION_ERROR = "ServiceValidationError"
