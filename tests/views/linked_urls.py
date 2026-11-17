from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from django_spec_rest import ServiceCreateView, ServiceDeleteView, ServiceUpdateView
from tests.views.linked_views import (
    ARCHIVE,
    BY_TITLE,
    CREATE,
    PLAIN,
    SHAPED,
    TITLED,
    LinkedDetail,
    LinkedList,
    PostViewSet,
    TouchViewSet,
    UnlinkedList,
)

router = SimpleRouter()
router.register("posts", PostViewSet, basename="posts")
touches = SimpleRouter()
touches.register("touches", TouchViewSet, basename="touches")

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
    path("", include((touches.urls, "touch"))),
    path("by-title/<slug:title>/", ServiceUpdateView.as_view(spec=BY_TITLE), name="by-title"),
    path("create/", ServiceCreateView.as_view(spec=CREATE), name="create"),
]
