# Serving a spec on a spec-html page

A spec is the kernel's, so the spec a viewset serves can also be served by
[django-spec-html](https://artui.github.io/django-spec-html/)'s `SpecFormView`,
as a page a person fills a form in on. Most of it works there unchanged. The
seat that does not is a DRF permission class that treats `view` as a DRF view.
This page covers what such a class is handed on a page, how to make it work
there, and how to write a spec that needs no DRF view at all.

The examples below are `tests/recipes/one_spec_on_a_page.py`, and
`tests/recipes/test_one_spec_on_a_page.py` runs each one on both mounts.

## One spec, two mounts

A club's members add posts. The club is a [pool seed][django_service_specs.pool.pool_seeds.PoolSeeds]
that the project's middleware puts on the request as `request.club`. The
permission class reads the route's `club_pk`:

```python
--8<--
tests/recipes/one_spec_on_a_page.py:spec
--8<--
```

The viewset and the page register the same seeds:

```python
--8<--
tests/recipes/one_spec_on_a_page.py:mounts
--8<--
```

```python
urlpatterns = [
    path("clubs/<int:club_pk>/posts/", ClubPostViewSet.as_view({"post": "create"})),
    path("clubs/<int:club_pk>/posts/new/", add_post_page),
]
```

`route_kwargs={"club_pk": None}` is needed only on the page. The viewset
ignores a route capture that the spec does not declare. `SpecFormView` raises
`ImproperlyConfigured` for one, because it reads every URL kwarg as an
argument. The mapping tells it to drop the capture. A spec that declares the
capture as a read needs no mapping ([below](#the-transport-neutral-way)).

## What a call carries on a page

On every call it makes, the page puts two things in the call's context:

- `request`: the Django `HttpRequest`.
- `view`: the `SpecFormView` instance. Its `kwargs` are the URL's captures,
  as on any Django view.

[`DRFPermissionCheck`][django_spec_rest.service_specs.drf_permission_check.DRFPermissionCheck]
asks the carried view as it is. It builds an offline request or view only for
the half a call does not carry (see [DRF permission classes](permissions.md#off-http)).

The Django request is not handed over as it is. DRF has not wrapped it, so
the check wraps a shallow copy in a DRF `Request` and changes three things
on the copy:

- `request.user` is the principal.
- `request.method` is `"POST"`, even while the page renders a GET.
- `request.data` is empty. The form's values are not in it.

Everything else on the copy is still the page's request: its headers, its
session, and the attributes middleware set, such as `request.club`. The
page asks its class-level check before it reads the form, so the query
string is the page's own as well.

So a class that reads `request.user`, `view.kwargs`, or an attribute your
middleware sets works on both mounts. A class that treats `view` as the
DRF view does not:

- It calls a method of the DRF view: `view.get_permissions`, `view.get_queryset`,
  `view.filter_queryset`, `view.get_object`. `SpecFormView` defines none of
  these, so the call raises `AttributeError`.
- It reads an attribute that a viewset or a role mixin sets, such as
  `view.action` (the page has no `action`) or a role your own base
  viewset attaches.
- It branches on `request.method` or reads `request.data`.

## The bridge: a mixin on the page

Where a project's classes call methods of their own on the view, the page
can answer those methods. Here the class asks the view for its club, and a
mixin that reads only `self.kwargs` answers on both the viewset and the
page:

```python
--8<--
tests/recipes/one_spec_on_a_page.py:bridge
--8<--
```

Give the mixin only the methods the classes call.

## The transport-neutral way

A spec that reads nothing from a DRF view needs no mixin:

- **Route captures are declared reads.** `reads=Parameters.of(Parameter("club_pk", ...))`
  fills the parameter from the route on both mounts, so the service receives
  `club_pk`. The page then needs no `route_kwargs`.
- **The scope is a pool seed registered on both mounts.** The resolver declares
  `request`: `DEFAULT_POOL_SEEDS.extend(club=lambda *, request: request.club)`.
  On the viewset, `request` is DRF's `Request`, which hands attribute reads
  to the Django request it wraps. On the page, it is the Django request. So
  `request.club` reads the same object on both.
- **The role check reads the seed.** Use a kernel
  [`PermissionCheck`][django_service_specs.authorization.permission_check.PermissionCheck] that
  declares the seed by name. Or keep a DRF class, as long as it reads only
  `request.user` and `view.kwargs`.

```python
--8<--
tests/recipes/one_spec_on_a_page.py:neutral
--8<--
```

A class-level check should not read a route capture from `arguments`. The
viewset passes the call's arguments, but the page asks before it reads the
form, so the check gets `arguments=None`. The seed is resolved before
either mount asks, so read the capture through the seed instead.

## What stays REST-only

Some things a viewset's spec may do have no counterpart on a page:

- **A provider applying the list's `filter_queryset`.** A `kwargs` provider,
  a seed's resolver, or any other spec callable that declares `view` gets the page, which
  has no `filter_queryset` or `get_queryset`. Filter in the selector, with a
  [`filter_set`](selector-filtering.md), or start from a seed.
- **A provider writing onto the view for the serializer to read later.** A
  page validates with a form and renders a template, and no serializer reads
  the view. Return the value from the provider, or make it a seed, so each
  stage that needs it declares it.
