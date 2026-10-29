"""``build_offline_context``: the request and view a kernel spec's DRF seats use off HTTP."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest, QueryDict
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers

from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.types.offline_context import OfflineContext
from django_spec_rest.types.offline_service_view import OfflineServiceView
from tests.testapp.models import Post

_USER = object()


def test_defaults_create_a_fresh_post_request() -> None:
    ctx = build_offline_context(_USER)
    assert isinstance(ctx, OfflineContext)
    assert isinstance(ctx.view, OfflineServiceView)
    assert ctx.user is _USER
    assert ctx.request.user is _USER
    assert ctx.request.method == "POST"
    assert ctx.request.data == {}
    assert ctx.view.action is None
    assert ctx.view.kwargs == {}
    assert ctx.view.request is ctx.request


def test_mapping_params_populate_request_data() -> None:
    ctx = build_offline_context(_USER, {"name": "x", "count": 2})
    assert ctx.request.data == {"name": "x", "count": 2}


def test_list_params_populate_request_data() -> None:
    ctx = build_offline_context(_USER, [{"a": 1}, {"a": 2}])
    assert ctx.request.data == [{"a": 1}, {"a": 2}]


def test_action_and_kwargs_flow_onto_the_view() -> None:
    ctx = build_offline_context(_USER, action="orders.create", kwargs={"pk": 7})
    assert ctx.view.action == "orders.create"
    assert ctx.view.kwargs == {"pk": 7}


def test_supplied_http_request_is_wrapped_and_forced_to_post() -> None:
    base = HttpRequest()
    base.method = "GET"
    base.META["HTTP_X_CUSTOM"] = "kept"
    ctx = build_offline_context(_USER, {"a": 1}, http_request=base)
    # A copy of the passed request is wrapped, and only the copy is forced to POST.
    assert ctx.request._request is not base
    assert ctx.request._request.method == "POST"
    assert base.method == "GET"
    # Pre-existing META survives, so headers a real transport carries are visible.
    assert ctx.request.META["HTTP_X_CUSTOM"] == "kept"
    assert ctx.request.data == {"a": 1}


def test_wrapping_a_real_wsgi_request_keeps_the_attributes_pickling_drops() -> None:
    # ``HttpRequest.__getstate__`` deliberately omits ``non_picklable_attrs``, so a
    # copy taken through ``copy.copy`` / ``__reduce_ex__`` silently loses ``environ``
    # and ``_stream``. ``WSGIRequest._get_scheme`` reads ``environ``, so the loss only
    # surfaces when something builds an absolute URI -- what a serializer carrying a
    # ``FileField`` or ``HyperlinkedIdentityField`` does on a perfectly ordinary read.
    from django.test import RequestFactory

    base = RequestFactory().post("/hook/")
    carried = set(base.__dict__)
    wrapped = build_offline_context(_USER, http_request=base).request._request
    # Nothing the caller's request held may be missing from the copy. Asserting the
    # whole set rather than naming ``environ`` keeps this true across Django versions:
    # which attributes are deemed non-picklable has changed, and the invariant has not.
    assert carried - set(wrapped.__dict__) == set()
    assert wrapped.build_absolute_uri("/x/") == "http://testserver/x/"


def test_wrapping_shares_meta_session_and_body_with_the_caller() -> None:
    base = HttpRequest()
    base.session = {"cart": ["a"]}  # ty: ignore[invalid-assignment]
    base._body = b"{}"
    ctx = build_offline_context(_USER, http_request=base)
    wrapped = ctx.request._request
    # The copy is shallow on purpose: everything the dispatched code reads through
    # the request keeps working, and a session write reaches the real session.
    assert wrapped.META is base.META
    assert wrapped.session is base.session
    assert wrapped._body is base._body
    wrapped.session["cart"].append("b")
    assert base.session["cart"] == ["a", "b"]


def test_wrapped_request_keeps_its_own_user() -> None:
    base = HttpRequest()
    caller_user = object()
    base.user = caller_user  # ty: ignore[unresolved-attribute]
    ctx = build_offline_context(_USER, http_request=base)
    # DRF's ``Request.user`` setter writes through to the request it wraps, so
    # without the copy this would reassign the live request's principal.
    assert ctx.request.user is _USER
    assert base.user is caller_user  # ty: ignore[unresolved-attribute]


def test_dispatching_twice_does_not_leak_query_params_between_calls() -> None:
    base = HttpRequest()
    base.GET = QueryDict("owner=real")
    build_offline_context(_USER, http_request=base, query_params={"owner": "alice"})
    second = build_offline_context(_USER, http_request=base)
    # The second dispatch sees the request's real query string, not the first
    # dispatch's params, and the caller's own ``GET`` is untouched throughout.
    assert second.request.query_params["owner"] == "real"
    assert base.GET["owner"] == "real"


def test_query_params_default_to_empty() -> None:
    ctx = build_offline_context(_USER)
    assert list(ctx.request.query_params.keys()) == []


def test_query_params_seed_the_request_get_and_stringify_scalars() -> None:
    ctx = build_offline_context(_USER, query_params={"query": "{id,name}", "page": 2})
    assert ctx.request.query_params["query"] == "{id,name}"
    # Scalars are stringified, mirroring HTTP query strings.
    assert ctx.request.query_params["page"] == "2"


def test_list_query_params_become_multivalued() -> None:
    ctx = build_offline_context(_USER, query_params={"status": ["open", "closed"]})
    assert ctx.request.query_params.getlist("status") == ["open", "closed"]


def test_seeded_query_params_are_immutable_like_a_real_get() -> None:
    ctx = build_offline_context(_USER, query_params={"a": "1"})
    with pytest.raises(AttributeError):
        ctx.request.query_params["b"] = "2"


def test_query_params_replace_a_wrapped_requests_get() -> None:
    base = HttpRequest()
    base.GET = QueryDict("a=1")
    ctx = build_offline_context(_USER, http_request=base, query_params={"b": "2"})
    assert "a" not in ctx.request.query_params
    assert ctx.request.query_params["b"] == "2"
    # The replacement is scoped to the wrapped copy.
    assert base.GET["a"] == "1"
    assert "b" not in base.GET


# --- the request's auth -------------------------------------------------------


@pytest.mark.django_db
def test_auth_is_none_and_reading_it_keeps_the_user() -> None:
    # DRF authenticates on the first read of ``auth``; with no authenticator
    # that read would replace the user with ``AnonymousUser``.
    principal = User.objects.create(username="signed-in")
    ctx = build_offline_context(principal)

    assert ctx.request.auth is None
    assert ctx.request.user is principal


def test_a_wrapped_request_s_auth_is_set_on_the_copy_alone() -> None:
    base = HttpRequest()
    ctx = build_offline_context(_USER, http_request=base)

    assert ctx.request.auth is None
    assert ctx.request.user is _USER
    assert not hasattr(base, "auth")


# --- what the synthetic query string reaches ------------------------------------


class _FieldsFromTheQueryString(serializers.Serializer):
    """Field selection read off the request, as django-restql does."""

    title = serializers.CharField()
    published = serializers.BooleanField()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        wanted = self.context["request"].query_params.get("fields")
        rendered = super().to_representation(instance)
        return {key: value for key, value in rendered.items() if wanted is None or key == wanted}


@pytest.mark.django_db
def test_a_serializer_branching_on_query_params_reads_the_spec_s_shapes() -> None:
    # Off HTTP the offline request's query string is the call's read-shaping
    # arguments, so a serializer reading ``request.query_params`` finds the
    # ``fields`` the caller sent.
    post = Post.objects.create(title="shipped", published=True)
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda: post,
        permissions=(Unrestricted(),),
        shapes=Parameters.of(Parameter("fields", "string", required=False)),
        presenter=SerializerPresenter(_FieldsFromTheQueryString),
    )

    result = dispatch(spec, principal=AnonymousUser(), arguments={"fields": "title"})

    assert present(spec, result) == {"title": "shipped"}
