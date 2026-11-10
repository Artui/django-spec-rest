from __future__ import annotations

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
    spec_caller_input_schema,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorRetrieveView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post


class TaskSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


def get_task(*, project_pk: int, pk: int) -> Post:
    return Post.objects.get(author_id=project_pk, pk=pk)


task_detail = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=get_task,
    permissions=(Unrestricted(),),
    reads=Parameters.of(
        Parameter("project_pk", "integer", required=True, help="The project the task belongs to."),
        Parameter("pk", "integer", required=True, help="The task to read."),
    ),
    presenter=SerializerPresenter(TaskSerializer),
)


def test_an_agent_is_told_both_captures_as_required_with_their_help() -> None:
    assert spec_caller_input_schema(task_detail) == {
        "type": "object",
        "properties": {
            "project_pk": {"type": "integer", "description": "The project the task belongs to."},
            "pk": {"type": "integer", "description": "The task to read."},
        },
        "additionalProperties": False,
        "required": ["project_pk", "pk"],
    }


@pytest.mark.django_db
def test_the_edge_reads_each_capture_from_the_route() -> None:
    project = Author.objects.create(name="project")
    task = Post.objects.create(title="task", author=project)
    view = type("_TaskView", (SelectorRetrieveView,), {"spec": task_detail})

    response = view.as_view()(
        APIRequestFactory().get("/"), project_pk=str(project.pk), pk=str(task.pk)
    )

    assert response.status_code == 200
    assert response.data == {"id": task.pk, "title": "task"}
