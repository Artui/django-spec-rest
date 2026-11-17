from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from django_spec_rest import ServiceCreateView, ServiceDeleteView
from tests.views.linked_views import (
    ARCHIVE,
    BY_TITLE,
    PLAIN,
    SHAPED,
    TITLED,
    LinkedDetail,
    LinkedList,
    PostViewSet,
    UnlinkedList,
)

router = SimpleRouter()
router.register("posts", PostViewSet, basename="posts")

urlpatterns = [
    path("", include((router.urls, "posts"))),
    # ``spec`` as an ``as_view`` keyword: the class attribute stays ``None``.
    path("archive/<int:pk>/", ServiceDeleteView.as_view(spec=ARCHIVE), name="archive"),
    path("linked/", LinkedList.as_view(), name="linked"),
    path("linked/<int:pk>/", LinkedDetail.as_view(), name="linked-detail"),
    path("unlinked/", UnlinkedList.as_view(), name="unlinked"),
    path("shaped/", LinkedList.as_view(spec=SHAPED), name="shaped"),
    path("titled/", LinkedList.as_view(spec=TITLED), name="titled"),
    path("plain/", LinkedList.as_view(spec=PLAIN), name="plain"),
    path("by-title/<slug:title>/", ServiceCreateView.as_view(spec=BY_TITLE), name="by-title"),
]
