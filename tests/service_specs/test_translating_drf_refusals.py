"""``translating_drf_refusals`` changes what an author callable raises, and nothing a reader of it takes.

An author applies it to a callable of a kernel spec. The kernel binds the call
by the callable's signature, awaits it by its kind, and reads the keys a
``kwargs`` provider fills off its return ``TypedDict``, resolved in the
provider's own module. So every surface the kernel derives from a spec is
compared with the decorator left off: a wrapper that hid ``async``-ness, the
signature, the annotations or ``__wrapped__`` would change one of them.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

import pytest
from django.db.models import QuerySet
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.types.is_async import is_async
from typing_extensions import TypedDict, Unpack

from django_spec_rest.service_specs.translating_drf_refusals import (
    translating_drf_refusals,
)
from tests.testapp.models import Post

_OPEN = (Unrestricted(),)


class _Scope(TypedDict):
    tenant: str


class _Keys(TypedDict):
    title: str
    status: str


def _scope(**_: Any) -> _Scope:
    return {"tenant": "acme"}


def _create(*, title: str, status: str, tenant: str) -> None: ...


async def _acreate(*, title: str, status: str, tenant: str) -> None: ...


def _gate(*, status: str) -> None: ...


def _unpacked(**keys: Unpack[_Keys]) -> None: ...


def _rows(*, q: str = "") -> QuerySet[Post]:
    return Post.objects.all()


async def _arows(*, q: str = "") -> QuerySet[Post]:
    return Post.objects.all()


def _extend(queryset: Any) -> Any:
    return queryset


_SPECS: dict[str, Callable[[Callable[[Any], Any]], Any]] = {
    "sync-service": lambda wrap: ServiceSpec(
        permissions=_OPEN,
        service=wrap(_create),
        kwargs=wrap(_scope),
        preconditions=[wrap(_gate)],
    ),
    "async-service": lambda wrap: ServiceSpec(
        permissions=_OPEN, service=wrap(_acreate), kwargs=wrap(_scope)
    ),
    "unpacked-service": lambda wrap: ServiceSpec(permissions=_OPEN, service=wrap(_unpacked)),
    "list-selector": lambda wrap: SelectorSpec(
        permissions=_OPEN,
        kind=SelectorKind.LIST,
        selector=wrap(_rows),
        kwargs=wrap(_scope),
        extend_queryset=wrap(_extend),
    ),
    "async-selector": lambda wrap: SelectorSpec(
        permissions=_OPEN, kind=SelectorKind.LIST, selector=wrap(_arows)
    ),
}


def _surfaces(spec: Any) -> list[Any]:
    """Everything the kernel derives from a spec that a wrapper could change."""
    callables = [getattr(spec, "service", None) or spec.selector, *(spec.preconditions or ())]
    return [
        spec.parameters(),
        provider_keys(spec.kwargs),
        [is_async(fn) for fn in callables],
        [inspect.signature(fn) for fn in callables],
    ]


@pytest.mark.parametrize("build", list(_SPECS.values()), ids=list(_SPECS))
def test_a_spec_reads_the_same_with_and_without_it(build: Callable[..., Any]) -> None:
    assert _surfaces(build(translating_drf_refusals)) == _surfaces(build(lambda fn: fn))


def test_a_typed_provider_still_names_the_keys_it_fills() -> None:
    """Resolved in the provider's own module, where the ``TypedDict`` is."""
    assert provider_keys(translating_drf_refusals(_scope)) == provider_keys(_scope)
    assert provider_keys(translating_drf_refusals(_scope)).filled == {"tenant"}  # ty: ignore[unresolved-attribute]


class _Bound:
    def create(self, *, title: str, status: str, tenant: str) -> None: ...


@pytest.mark.parametrize(
    "fn", [_create, _acreate, _Bound().create], ids=["sync", "async", "method"]
)
def test_it_reports_what_it_wraps(fn: Callable[..., Any]) -> None:
    wrapped = translating_drf_refusals(fn)

    assert is_async(wrapped) is is_async(fn)
    assert inspect.signature(wrapped) == inspect.signature(fn)
    assert wrapped.__wrapped__ is fn  # ty: ignore[unresolved-attribute]
    assert (wrapped.__name__, wrapped.__qualname__, wrapped.__module__) == (
        fn.__name__,
        fn.__qualname__,
        fn.__module__,
    )
    assert wrapped.__annotations__ == fn.__annotations__
    assert fn.__dict__ == {}


def test_a_callable_with_no_name_of_its_own_is_named_for_what_it_is() -> None:
    wrapped = translating_drf_refusals(functools.partial(_create, title="t"))

    assert (wrapped.__name__, wrapped.__qualname__) == ("callable", "callable")
    assert inspect.signature(wrapped) == inspect.signature(functools.partial(_create, title="t"))


def test_an_empty_seat_stays_empty() -> None:
    assert translating_drf_refusals(None) is None


# --- What a reader of the compiled spec's callables sees ---------------------


def _documented_service(*, title: str = "") -> None:
    """The service's own words."""


_documented_service.audience = "staff"  # ty: ignore[unresolved-attribute]


async def _documented_aservice(*, title: str = "") -> None:
    """The async service's own words."""


def _documented_selector(**_: Any) -> QuerySet[Post]:
    """The selector's own words."""
    return Post.objects.all()


def _documented_kwargs(**_: Any) -> _Scope:
    """The provider's own words."""
    return {"tenant": "acme"}


class _Owner:
    def create(self, *, title: str = "") -> None:
        """The method's own words."""

    def rows(self, **_: Any) -> QuerySet[Post]:
        """The bound selector's own words."""
        return Post.objects.all()


_DOCUMENTED: dict[str, tuple[Callable[..., Any], str]] = {
    "function-service": (_documented_service, "The service's own words."),
    "method-service": (_Owner().create, "The method's own words."),
    "async-service": (_documented_aservice, "The async service's own words."),
    "function-selector": (_documented_selector, "The selector's own words."),
    "method-selector": (_Owner().rows, "The bound selector's own words."),
    "kwargs-provider": (_documented_kwargs, "The provider's own words."),
}


@pytest.mark.parametrize(("author", "words"), list(_DOCUMENTED.values()), ids=list(_DOCUMENTED))
def test_the_wrapped_callable_keeps_the_author_s_docstring(
    author: Callable[..., Any], words: str
) -> None:
    """A tool description is read off the callable the spec declares."""
    assert inspect.getdoc(translating_drf_refusals(author)) == words


def test_a_function_s_attributes_survive_the_wrap() -> None:
    wrapped = translating_drf_refusals(_documented_service)

    assert wrapped.audience == "staff"  # ty: ignore[unresolved-attribute]
    assert _documented_service.__dict__ == {"audience": "staff"}


def test_a_decorated_function_is_still_wrapped_by_the_translator() -> None:
    """Its own ``__wrapped__`` and ``__signature__`` attributes do not displace the translator's."""

    def inner(*, title: str) -> None: ...

    @functools.wraps(inner)
    def decorated(**kwargs: Any) -> None: ...

    wrapped = translating_drf_refusals(decorated)

    assert wrapped.__wrapped__ is decorated  # ty: ignore[unresolved-attribute]
    assert inspect.unwrap(wrapped) is inner
    assert inspect.signature(wrapped) == inspect.signature(decorated)


class _Callable:
    """The class's words, which a partial or an object has no function to read."""

    def __init__(self) -> None:
        self.note = "kept on the object"

    def __call__(self, *, title: str = "") -> None: ...


def _a_partial_with_an_attribute() -> Callable[..., Any]:
    partial = functools.partial(_create, title="t")
    partial.note = "kept on the partial"  # ty: ignore[unresolved-attribute]
    return partial


@pytest.mark.parametrize(
    "author",
    [_a_partial_with_an_attribute(), _Callable()],
    ids=["partial", "callable-object"],
)
def test_a_partial_or_a_callable_object_gets_no_docstring_or_attributes(
    author: Callable[..., Any],
) -> None:
    """``inspect.isfunction`` is how a reader tells a function's words from a class's.

    Copying the class's docstring would make ``functools.partial`` or the
    callable's class read as the description of this one callable, and copying
    the attributes would stamp the wrapper with what belongs to the object.
    Each is held apart: the docstring by ``__doc__``, the attributes by a
    ``note`` the author carries on the instance.
    """
    assert author.note  # ty: ignore[unresolved-attribute]

    wrapped = translating_drf_refusals(author)

    assert wrapped.__doc__ is None
    assert inspect.getdoc(wrapped) is None
    assert "note" not in wrapped.__dict__
    assert inspect.unwrap(wrapped) is author
