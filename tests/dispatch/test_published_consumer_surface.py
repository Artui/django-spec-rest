"""What the published transports import from this package and pass to ``dispatch_spec``.

The published djangorestframework-mcp-server 0.52.0 and
djangorestframework-pydantic-ai 0.35.0 floor this package unbounded, so they
resolve onto this release as they are. Every name either imports is listed here,
read off their import statements at those tags, the two private ones in
``dispatch.utils`` included, and every ``dispatch_spec`` keyword either passes is
passed. A name or a keyword leaving fails here before it fails in a transport.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from django.db.models import QuerySet
from rest_framework import serializers

from django_spec_rest import (
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    build_offline_context,
    dispatch_spec,
    enforce_permissions,
)
from django_spec_rest.dispatch.utils import (
    declared_input_keys,
    resolve_unknown_arguments,
)
from django_spec_rest.types.argument_binding import ArgumentBinding
from django_spec_rest.types.pool_seeds import DEFAULT_POOL_SEEDS
from django_spec_rest.types.unknown_arguments import UnknownArguments
from django_spec_rest.types.url_kwarg import UrlKwarg
from tests.testapp.models import Author, Post

# ``(module, name)`` for each ``from <module> import <name>`` at the two tags.
PUBLISHED_IMPORTS: list[tuple[str, str]] = [
    ("django_spec_rest", "ActionUnavailable"),
    ("django_spec_rest", "AdditionalInputRequired"),
    ("django_spec_rest", "Affordance"),
    ("django_spec_rest", "ArgumentBinding"),
    ("django_spec_rest", "AudienceProjection"),
    ("django_spec_rest", "DEFAULT_JSON_SCHEMA_REGISTRY"),
    ("django_spec_rest", "DEFAULT_PAGE_SIZE"),
    ("django_spec_rest", "DEFAULT_POOL_SEEDS"),
    ("django_spec_rest", "DispatchResult"),
    ("django_spec_rest", "FieldAudience"),
    ("django_spec_rest", "FieldMarking"),
    ("django_spec_rest", "JsonSchemaRegistry"),
    ("django_spec_rest", "OfflineContext"),
    ("django_spec_rest", "OfflineContract"),
    ("django_spec_rest", "OfflineServiceView"),
    ("django_spec_rest", "OutputPage"),
    ("django_spec_rest", "PoolSeeds"),
    ("django_spec_rest", "SelectorKind"),
    ("django_spec_rest", "SelectorSpec"),
    ("django_spec_rest", "ServiceError"),
    ("django_spec_rest", "ServiceSpec"),
    ("django_spec_rest", "ServiceValidationError"),
    ("django_spec_rest", "SpecRegistry"),
    ("django_spec_rest", "UNSET"),
    ("django_spec_rest", "UnknownArguments"),
    ("django_spec_rest", "UnsetType"),
    ("django_spec_rest", "adispatch_spec"),
    ("django_spec_rest", "arun_selector"),
    ("django_spec_rest", "audience_projection_for_spec"),
    ("django_spec_rest", "base_pool"),
    ("django_spec_rest", "base_serializer_context"),
    ("django_spec_rest", "build_audience_projection"),
    ("django_spec_rest", "build_offline_context"),
    ("django_spec_rest", "can_present_nothing"),
    ("django_spec_rest", "dispatch_spec"),
    ("django_spec_rest", "enforce_affordances"),
    ("django_spec_rest", "enforce_permissions"),
    ("django_spec_rest", "is_async"),
    ("django_spec_rest", "is_queryset"),
    ("django_spec_rest", "materialize_retrieve"),
    ("django_spec_rest", "operation_affordances"),
    ("django_spec_rest", "output_to_json_schema"),
    ("django_spec_rest", "paginate_output"),
    ("django_spec_rest", "provider_keys"),
    ("django_spec_rest", "render_for_audience"),
    ("django_spec_rest", "renderable_serializer_class"),
    ("django_spec_rest", "resolve_callable_kwargs"),
    ("django_spec_rest", "run_selector"),
    ("django_spec_rest", "run_service"),
    ("django_spec_rest", "serializer_to_json_schema"),
    ("django_spec_rest", "server_owned_keys"),
    ("django_spec_rest", "spec_to_json_schema"),
    ("django_spec_rest", "unmet_operation_affordance"),
    ("django_spec_rest.dispatch.unguarded_specs", "unguarded_specs"),
    ("django_spec_rest.dispatch.utils", "declared_input_keys"),
    ("django_spec_rest.dispatch.utils", "resolve_unknown_arguments"),
    ("django_spec_rest.exceptions.action_unavailable", "ActionUnavailable"),
    ("django_spec_rest.exceptions.additional_input_required", "AdditionalInputRequired"),
    ("django_spec_rest.exceptions.service_error", "ServiceError"),
    ("django_spec_rest.exceptions.service_validation_error", "ServiceValidationError"),
    ("django_spec_rest.registry.spec_registry", "SpecRegistry"),
    ("django_spec_rest.types.affordance", "Affordance"),
    ("django_spec_rest.types.audience_projection", "AudienceProjection"),
    ("django_spec_rest.types.dispatch_result", "DispatchResult"),
    ("django_spec_rest.types.field_audience", "FieldAudience"),
    ("django_spec_rest.types.offline_context", "OfflineContext"),
    ("django_spec_rest.types.pool_seeds", "DEFAULT_POOL_SEEDS"),
    ("django_spec_rest.types.pool_seeds", "PoolSeeds"),
    ("django_spec_rest.types.progress_reporter", "ProgressReporter"),
    ("django_spec_rest.types.query_param", "QueryParam"),
    ("django_spec_rest.types.reserved_pool_seeds", "RESERVED_POOL_SEEDS"),
    ("django_spec_rest.types.selector_kind", "SelectorKind"),
    ("django_spec_rest.types.selector_spec", "SelectorSpec"),
    ("django_spec_rest.types.service_spec", "ServiceSpec"),
    ("django_spec_rest.types.url_kwarg", "UrlKwarg"),
    ("django_spec_rest.types.validate_channel_names", "validate_channel_names"),
]


@pytest.mark.parametrize(("module", "name"), PUBLISHED_IMPORTS)
def test_every_published_import_resolves(module: str, name: str) -> None:
    assert hasattr(importlib.import_module(module), name)


def test_passthrough_stays_a_member_a_transport_compares_by_identity() -> None:
    # drf-mcp 0.52.0's own unknown-argument handling, configured with IGNORE.
    unknown_arguments = UnknownArguments.IGNORE
    assert (unknown_arguments is UnknownArguments.PASSTHROUGH) is False


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


def _posts_by(*, author_pk: int) -> QuerySet[Post]:
    return Post.objects.filter(author_id=author_pk).order_by("pk")


def _create(*, data: Any) -> Post:
    return Post.objects.create(**data)


@pytest.mark.django_db
class TestTheKeywordsTheTransportsPass:
    def test_drf_mcp_hands_a_declared_url_kwarg_on_the_offline_view(self) -> None:
        author = Author.objects.create(name="a")
        Post.objects.create(title="a", author=author)
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_posts_by,
            reads=[UrlKwarg("author_pk", type="integer", required=True)],
            permission_classes=[],
        )
        # drf-mcp splits the declared UrlKwarg off the arguments, onto the view.
        offline = build_offline_context(None, kwargs={"author_pk": author.pk})
        enforce_permissions(spec, offline)
        result = dispatch_spec(
            spec,
            user=None,
            params={},
            request=offline.request,
            view=offline.view,
            argument_binding=ArgumentBinding.AUTO,
            unknown_arguments=UnknownArguments.REJECT,
            on_target_resolved=enforce_permissions,
            progress=None,
            pool_seeds=DEFAULT_POOL_SEEDS,
            many_as_argument=True,
        )
        assert [post.title for post in result.value] == ["a"]

    def test_pai_passes_filter_data_and_many_as_argument(self) -> None:
        spec = ServiceSpec(service=_create, input_serializer=_TitleIn, permission_classes=[])
        offline = build_offline_context(None, {"title": "b"})
        enforce_permissions(spec, offline)
        result = dispatch_spec(
            spec,
            user=None,
            params={"title": "b"},
            request=offline.request,
            view=offline.view,
            unknown_arguments=UnknownArguments.IGNORE,
            argument_binding=ArgumentBinding.AUTO,
            on_target_resolved=enforce_permissions,
            progress=None,
            filter_data=None,
            many_as_argument=True,
        )
        assert result.value.title == "b"

    def test_the_two_private_names_answer_as_drf_mcp_calls_them(self) -> None:
        spec = ServiceSpec(service=_create, input_serializer=_TitleIn, permission_classes=[])
        declared_input_keys(spec, serializer=None, argument_binding=ArgumentBinding.AUTO)
        resolve_unknown_arguments(
            spec,
            {},
            unknown_arguments=UnknownArguments.REJECT,
            serializer=None,
            argument_binding=ArgumentBinding.AUTO,
        )


class TestRetiredModesAreRefused:
    def test_passthrough(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_posts_by, permission_classes=[])
        with pytest.raises(ValueError, match="PASSTHROUGH"):
            dispatch_spec(
                spec, user=None, params={}, unknown_arguments=UnknownArguments.PASSTHROUGH
            )

    def test_spread_caller_wins(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_posts_by, permission_classes=[])
        with pytest.raises(ValueError, match="SPREAD_CALLER_WINS"):
            dispatch_spec(
                spec,
                user=None,
                params={},
                argument_binding=ArgumentBinding.SPREAD_CALLER_WINS,
            )
