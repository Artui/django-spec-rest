"""Shared value types — used as inputs and outputs across the library.

These are intentionally framework-agnostic data carriers. They live outside
``mutations/`` so callers (current and future) that consume them as typed
inputs/outputs are not coupled to the mutation helpers themselves.
"""

from django_spec_rest.types.affordance import Affordance
from django_spec_rest.types.argument_binding import ArgumentBinding
from django_spec_rest.types.audience_projection import AudienceProjection
from django_spec_rest.types.change_result import ChangeResult
from django_spec_rest.types.child_collection_change import ChildCollectionChange
from django_spec_rest.types.child_spec import ChildSpec
from django_spec_rest.types.dispatch_result import DispatchResult
from django_spec_rest.types.field_audience import FieldAudience
from django_spec_rest.types.field_change import FieldChange
from django_spec_rest.types.field_marking import MARKING, FieldMarking
from django_spec_rest.types.forward_relation_spec import ForwardRelationSpec
from django_spec_rest.types.generic_relation_spec import GenericRelationSpec
from django_spec_rest.types.http_extras import HttpExtras
from django_spec_rest.types.input_description import InputDescription
from django_spec_rest.types.input_required import InputRequired, InputRequiredType
from django_spec_rest.types.json_schema_registry import (
    DEFAULT_JSON_SCHEMA_REGISTRY,
    JsonSchemaRegistry,
)
from django_spec_rest.types.many_to_many_spec import ManyToManySpec
from django_spec_rest.types.no_input import NoInput
from django_spec_rest.types.not_client_input import NotClientInput, NotClientInputType
from django_spec_rest.types.offline_context import OfflineContext
from django_spec_rest.types.offline_contract import OfflineContract
from django_spec_rest.types.offline_http_request import OfflineHttpRequest
from django_spec_rest.types.offline_service_view import OfflineServiceView
from django_spec_rest.types.output_page import OutputPage
from django_spec_rest.types.polymorphic_service_spec import PolymorphicServiceSpec
from django_spec_rest.types.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_spec_rest.types.progress_reporter import ProgressReporter
from django_spec_rest.types.provider_keys import ProviderKeys
from django_spec_rest.types.query_param import QueryParam
from django_spec_rest.types.read_input_description import read_input_description
from django_spec_rest.types.read_schema_markers import read_schema_markers
from django_spec_rest.types.registered_spec import RegisteredSpec
from django_spec_rest.types.related_object_change import RelatedObjectChange
from django_spec_rest.types.relation_mode import RelationMode
from django_spec_rest.types.relation_orphan import RelationOrphan
from django_spec_rest.types.relation_outcome import RelationOutcome
from django_spec_rest.types.relation_phase import RelationPhase
from django_spec_rest.types.relation_spec import RelationSpec
from django_spec_rest.types.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_spec_rest.types.reverse_one_to_one_spec import ReverseOneToOneSpec
from django_spec_rest.types.selector_kind import SelectorKind
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.types.service_spec import ServiceSpec
from django_spec_rest.types.service_view import ServiceView
from django_spec_rest.types.target_guard import TargetGuard
from django_spec_rest.types.unknown_arguments import UnknownArguments
from django_spec_rest.types.unset import UNSET, UnsetType
from django_spec_rest.types.url_kwarg import UrlKwarg
from django_spec_rest.types.validate_channel_names import validate_channel_names
from django_spec_rest.types.value_formatter import ValueFormatter
from django_spec_rest.types.view_hooks import ViewHooks

__all__ = [
    "MARKING",
    "FieldMarking",
    "OutputPage",
    "AudienceProjection",
    "DEFAULT_JSON_SCHEMA_REGISTRY",
    "DEFAULT_POOL_SEEDS",
    "PoolSeeds",
    "RESERVED_POOL_SEEDS",
    "UNSET",
    "Affordance",
    "ArgumentBinding",
    "ChangeResult",
    "ChildCollectionChange",
    "ChildSpec",
    "DispatchResult",
    "FieldChange",
    "ForwardRelationSpec",
    "GenericRelationSpec",
    "HttpExtras",
    "InputDescription",
    "InputRequired",
    "InputRequiredType",
    "JsonSchemaRegistry",
    "ManyToManySpec",
    "NoInput",
    "NotClientInput",
    "NotClientInputType",
    "OfflineContext",
    "OfflineHttpRequest",
    "OfflineServiceView",
    "PolymorphicServiceSpec",
    "ProgressReporter",
    "ProviderKeys",
    "QueryParam",
    "OfflineContract",
    "RegisteredSpec",
    "RelatedObjectChange",
    "RelationMode",
    "RelationOrphan",
    "RelationOutcome",
    "RelationPhase",
    "RelationSpec",
    "ReverseOneToOneSpec",
    "FieldAudience",
    "SelectorKind",
    "SelectorSpec",
    "ServiceSpec",
    "ServiceView",
    "TargetGuard",
    "ViewHooks",
    "UnknownArguments",
    "ViewHooks",
    "UnsetType",
    "UrlKwarg",
    "read_input_description",
    "ValueFormatter",
    "read_schema_markers",
    "validate_channel_names",
]
