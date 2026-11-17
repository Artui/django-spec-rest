from __future__ import annotations

from django.urls import include, path, re_path
from rest_framework.routers import SimpleRouter
from rest_framework.versioning import NamespaceVersioning, URLPathVersioning

from django_spec_rest import SelectorListView
from tests.views.linked_views import LISTING, ROUTES, PostViewSet

router = SimpleRouter()
router.register("posts", PostViewSet, basename="posts")
by_namespace = [
    path("", include((router.urls, "posts"))),
    path(
        "rows/",
        SelectorListView.as_view(
            spec=LISTING, link_routes=ROUTES, versioning_class=NamespaceVersioning
        ),
    ),
]

urlpatterns = [
    re_path(r"^(?P<version>v[12])/", include((router.urls, "posts"))),
    re_path(
        r"^(?P<version>v[12])/rows/$",
        SelectorListView.as_view(
            spec=LISTING, link_routes=ROUTES, versioning_class=URLPathVersioning
        ),
    ),
    path("n1/", include((by_namespace, "n1"), namespace="n1")),
]
