"""A spec's answers follow its import into the view serving it from another module.

Every test drives ``main``, the codemod as it is run. A move is proven by a
real request through the rewritten view, imported from the written files; what
is left is proven by its note, and by the view still importing as it stands.
"""

from __future__ import annotations

import ast
import importlib
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from drfs_codemod.__main__ import main
from drfs_codemod.rewrite import MARKER
from rest_framework.test import APIRequestFactory

from tests.testapp.models import Author

factory = APIRequestFactory()

SPEC_MODULE = """\
from rest_framework.permissions import AllowAny
from rest_framework_services import ServiceSpec

from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


def create_author(*, data):
    return Author.objects.create(name=data["name"])


def stamp(*, response):
    response["X-Answer"] = "stamped"


enrol = ServiceSpec(
    service=create_author,
    input_serializer=AuthorSerializer,
    output_serializer=AuthorSerializer,
    permission_classes=[AllowAny],
    success_status={status},
    response_finalizer=stamp,
)
"""

ATTRIBUTE_VIEW = """\
from rest_framework_services import ServiceCreateView
{importing}


class Enrol(ServiceCreateView):
    spec = {named}
"""

HOOK_VIEW = """\
from rest_framework_services import ServiceViewSet
{importing}


class Enrol(ServiceViewSet):
    action_specs = {{"create": {named}}}
"""

DECORATOR_VIEW = """\
from rest_framework_services import ServiceViewSet, service_action
{importing}


class Enrol(ServiceViewSet):
    @service_action({named}, methods=["post"])
    def create(self, request):
        pass
"""

ABSOLUTE = "from {package}.specs.enrolment import enrol"


class Project:
    """A package on ``sys.path`` under a name no other test imports, with ``specs/`` and ``views/``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.package = f"followed_{uuid.uuid4().hex}"

    def write(self, relative: str, content: str) -> Path:
        """Write ``relative`` under the package, each directory on the way a package too."""
        path = self.root / self.package / relative
        for parent in reversed([*path.relative_to(self.root).parents][:-1]):
            (self.root / parent).mkdir(exist_ok=True)
            (self.root / parent / "__init__.py").touch()
        path.write_text(content.replace("{package}", self.package))
        return path

    def spec(self, status: str = "202", head: str = "") -> Path:
        source = SPEC_MODULE.replace("{status}", status)
        return self.write("specs/enrolment.py", head + source)

    def view(
        self,
        template: str = ATTRIBUTE_VIEW,
        importing: str = ABSOLUTE,
        named: str = "enrol",
        relative: str = "views/enrolment.py",
    ) -> Path:
        source = template.replace("{importing}", importing).replace("{named}", named)
        return self.write(relative, source.replace("{{", "{").replace("}}", "}"))

    def run(self, *paths: Path, check: bool = False) -> tuple[int, list[str]]:
        """Run the codemod, by default over the package, with the report's lines."""
        report = self.root / "report.txt"
        named = [str(path) for path in paths] or [str(self.root / self.package)]
        argv = [*named, "--root", str(self.root), "--report", str(report)]
        code = main([*argv, "--check"] if check else argv)
        return code, report.read_text().splitlines()

    def module(self, relative: str = "views.enrolment") -> ModuleType:
        return importlib.import_module(f"{self.package}.{relative}")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.syspath_prepend(tmp_path)
    return Project(tmp_path)


def _markers(path: Path) -> list[str]:
    return [
        line.strip()[len(f"# {MARKER} ") :]
        for line in path.read_text().splitlines()
        if line.strip().startswith(f"# {MARKER} ")
    ]


def _assert_left(spec: Path, why: str) -> None:
    """Both answers are in the spec's notes with their values and ``why``, and neither moved."""
    notes = _markers(spec)
    for value in ("success_status=", "response_finalizer=stamp"):
        kept = [note for note in notes if note.startswith(value)]
        assert len(kept) == 1, notes
        assert "is the view's or the action's" in kept[0]
        assert why in kept[0]
    assert "moved to" not in " ".join(notes)


def _answers(view: Path) -> list[str]:
    return [
        node.targets[0].id
        for node in ast.walk(ast.parse(view.read_text()))
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and ("success_status" in node.targets[0].id or "finalizer" in node.targets[0].id)
    ]


def _post(view) -> object:
    return view(factory.post("/", {"name": "a"}, format="json"))


# --- what moves ----------------------------------------------------------------


@pytest.mark.django_db
def test_both_answers_reach_the_view_and_answer_a_request(project: Project) -> None:
    spec, view = project.spec(), project.view()
    assert project.run()[0] == 0
    written = view.read_text()
    assert "    success_status = 202\n" in written
    assert "    response_finalizer = stamp\n" in written
    assert f"from {project.package}.specs.enrolment import stamp, enrol" in written
    assert "success_status=202," not in spec.read_text()
    response = _post(project.module().Enrol.as_view())
    assert response.status_code == 202, response.data
    assert response["X-Answer"] == "stamped"
    assert Author.objects.filter(name="a").exists()


@pytest.mark.django_db
def test_the_hook_form_answers_its_action(project: Project) -> None:
    project.spec()
    view = project.view(HOOK_VIEW)
    project.run()
    assert "get_create_success_status = 202\n" in view.read_text()
    assert "get_create_response_finalizer = staticmethod(stamp)\n" in view.read_text()
    response = _post(project.module().Enrol.as_view({"post": "create"}))
    assert response.status_code == 202, response.data
    assert response["X-Answer"] == "stamped"


@pytest.mark.django_db
def test_the_decorator_form_answers_its_action(project: Project) -> None:
    project.spec()
    view = project.view(DECORATOR_VIEW)
    project.run()
    assert "success_status=202, response_finalizer=stamp)" in view.read_text()
    response = _post(project.module().Enrol.as_view({"post": "create"}))
    assert response.status_code == 202, response.data
    assert response["X-Answer"] == "stamped"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "importing, named",
    [
        ("from ..specs.enrolment import enrol", "enrol"),
        ("from ..specs import enrolment", "enrolment.enrol"),
        ("from .. import specs", "specs.enrolment.enrol"),
        ("from {package}.specs import enrolment", "enrolment.enrol"),
        ("from {package}.specs import enrolment as e", "e.enrol"),
        ("import {package}.specs.enrolment as e", "e.enrol"),
        ("import {package}.specs.enrolment", "{package}.specs.enrolment.enrol"),
    ],
)
def test_each_certain_import_is_followed(project: Project, importing: str, named: str) -> None:
    project.spec()
    project.view(importing=importing, named=named.replace("{package}", project.package))
    project.run()
    response = _post(project.module().Enrol.as_view())
    assert response.status_code == 202, response.data
    assert response["X-Answer"] == "stamped"


@pytest.mark.django_db
def test_a_package_re_exporting_the_spec_is_followed_to_it(project: Project) -> None:
    project.spec("status.HTTP_202_ACCEPTED", head="from rest_framework import status\n")
    project.write("specs/__init__.py", "from .enrolment import enrol, stamp\n")
    project.view(importing="from {package}.specs import enrol")
    project.run()
    response = _post(project.module().Enrol.as_view())
    assert response.status_code == 202, response.data


@pytest.mark.django_db
def test_two_views_in_one_module_each_take_it_as_the_same_module_does(project: Project) -> None:
    project.spec()
    view = project.view()
    view.write_text(view.read_text() + "\n\nclass Again(ServiceCreateView):\n    spec = enrol\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"] * 2
    assert _post(project.module().Again.as_view()).status_code == 202


def test_the_report_names_where_it_moved(project: Project) -> None:
    project.spec()
    project.view()
    _, lines = project.run()
    assert (
        f"success_status=202 moved to Enrol.success_status in {project.package}/views/enrolment.py"
        in "\n".join(lines)
    )


def test_a_second_run_changes_nothing_and_reports_the_same(project: Project) -> None:
    spec, view = project.spec(), project.view()
    _, first = project.run()
    written = spec.read_text(), view.read_text()
    assert project.run(check=True)[0] == 0
    _, second = project.run()
    assert (spec.read_text(), view.read_text()) == written
    assert second == first


def test_check_reports_the_move_and_writes_nothing(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec, view = project.spec(), project.view()
    before = spec.read_text(), view.read_text()
    code, lines = project.run(check=True)
    assert code == 1
    assert (spec.read_text(), view.read_text()) == before
    assert "moved to Enrol.success_status" in "\n".join(lines)
    # The spec and the view both.
    assert capsys.readouterr().err == "2 files would change\n"


def test_overlapping_paths_count_one_view_once(project: Project) -> None:
    project.spec()
    view = project.view()
    spelled_otherwise = view.parent / ".." / "views" / view.name
    _, lines = project.run(project.root / project.package, spelled_otherwise)
    assert _answers(view) == ["success_status", "response_finalizer"]
    assert lines[-1] == "2 sites left in 1 files"
    assert "moved to Enrol.success_status in " in "\n".join(lines)


def test_a_view_is_written_before_the_spec_it_empties(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, view = project.spec(), project.view()
    before = spec.read_text()
    real = Path.write_text

    def refuse_the_view(self: Path, *args: object, **kwargs: object) -> int:
        if self == view:
            raise PermissionError(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse_the_view)
    with pytest.raises(PermissionError):
        main([str(project.root / project.package), "--root", str(project.root)])
    assert spec.read_text() == before


# --- what is left, by who imports it -------------------------------------------


def test_a_spec_imported_by_two_views_is_left(project: Project) -> None:
    spec, one = project.spec(), project.view()
    other = project.view(relative="views/other.py")
    project.run()
    assert _answers(one) == _answers(other) == []
    _assert_left(spec, "served from 2 modules")
    importlib.invalidate_caches()
    assert project.module().Enrol.spec is not None


def test_a_spec_imported_under_an_alias_is_left(project: Project) -> None:
    spec = project.spec()
    view = project.view(importing=f"{ABSOLUTE} as joining", named="joining")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "imported as joining")


def test_an_alias_elsewhere_leaves_the_view_it_would_have_moved_to(project: Project) -> None:
    spec = project.spec()
    view = project.view()
    project.write("elsewhere.py", f"{ABSOLUTE} as joining\n".replace("{package}", project.package))
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "imported as joining")


def test_a_view_outside_the_run_takes_nothing(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.run(spec)
    assert _answers(view) == []
    _assert_left(spec, "")


def test_a_spec_outside_the_run_is_not_touched(project: Project) -> None:
    spec, view = project.spec(), project.view()
    before = spec.read_text()
    project.run(view)
    assert _answers(view) == []
    assert spec.read_text() == before


def test_a_root_that_does_not_reach_the_spec_moves_nothing(
    project: Project, tmp_path: Path
) -> None:
    spec, view = project.spec(), project.view()
    report = tmp_path / "report.txt"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    main([str(project.root / project.package), "--root", str(elsewhere), "--report", str(report)])
    assert _answers(view) == []
    _assert_left(spec, "")


def test_a_spec_with_a_view_in_its_own_module_stays_with_it(project: Project) -> None:
    spec = project.spec()
    spec.write_text(
        "from rest_framework_services import ServiceCreateView\n"
        + spec.read_text()
        + "\n\nclass Here(ServiceCreateView):\n    spec = enrol\n"
    )
    view = project.view()
    project.run()
    assert _answers(view) == []
    assert _answers(spec) == ["success_status", "response_finalizer"]
    assert "a view in another module serving enrol declares it itself" in " ".join(_markers(spec))


@pytest.mark.parametrize(
    "use",
    [
        "\n\nurlpatterns = [Enrol.as_view(spec=enrol)]\n",
        "\n\ndef helper():\n    return enrol.service\n",
    ],
)
def test_a_use_beside_the_serving_one_leaves_it(project: Project, use: str) -> None:
    spec, view = project.spec(), project.view()
    view.write_text(view.read_text() + use)
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "used otherwise in")


def test_a_same_named_attribute_of_another_name_is_not_the_spec(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write(
        "tasks.py",
        "import thing\n\nfrom .specs import enrolment\n\nservice = thing.enrol.service\n",
    )
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_module_reference_beside_the_serving_one_leaves_it(project: Project) -> None:
    spec = project.spec()
    view = project.view(importing="from ..specs import enrolment", named="enrolment.enrol")
    view.write_text(view.read_text() + "\n\nservice = enrolment.enrol.service\n")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "used otherwise in")


def test_a_use_in_its_own_module_leaves_it(project: Project) -> None:
    spec = project.spec()
    spec.write_text(spec.read_text() + "\nALL = [enrol]\n")
    view = project.view()
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "used otherwise in its own module")


def test_a_spec_bound_twice_is_left(project: Project) -> None:
    spec = project.spec()
    spec.write_text(spec.read_text() + "\nenrol = None\n")
    view = project.view()
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "bound more than once")


def test_a_spec_built_in_a_function_is_left(project: Project) -> None:
    spec = project.write(
        "specs/enrolment.py",
        "from rest_framework_services import ServiceSpec\n\n\n"
        "def build():\n    enrol = ServiceSpec(service=print, success_status=202)\n"
        "    return enrol\n\n\nenrol = build()\n",
    )
    view = project.view()
    project.run()
    assert _answers(view) == []
    assert "success_status=202 is the view's" in " ".join(_markers(spec))


def test_a_function_local_import_leaves_it(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.write(
        "tasks.py",
        f"def run():\n    {ABSOLUTE}\n    return enrol\n".replace("{package}", project.package),
    )
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "imported inside a function")


def test_a_function_local_module_import_leaves_it(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.write(
        "tasks.py",
        "def run():\n    from .specs import enrolment\n    return enrolment.enrol\n",
    )
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "imported inside a function")


def test_a_star_import_leaves_it(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.write("tasks.py", "from .specs.enrolment import *\n")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "star-imported in")


def test_a_test_module_reading_the_spec_is_no_second_view(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write(
        "tests/test_enrol.py",
        f"{ABSOLUTE}\n\n\ndef test_it():\n    assert enrol.service\n",
    )
    project.write(
        "tests/test_alias.py",
        f"{ABSOLUTE} as joining\n\n\ndef test_it():\n    assert joining.service\n",
    )
    project.write(
        "test_module.py",
        "from .specs import enrolment\n\n\ndef test_it():\n    assert enrolment.enrol\n",
    )
    project.write("tests/helpers.py", f"{ABSOLUTE}\n\n\nuse = enrol\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_test_module_serving_the_spec_is_a_second_view(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.view(relative="tests/test_view.py")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "served from 2 modules")


def test_a_re_export_under_another_name_is_not_the_spec(project: Project) -> None:
    spec = project.spec()
    project.write("specs/__init__.py", "from .enrolment import stamp as enrol\n")
    view = project.view(importing="from {package}.specs import enrol")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "")


def test_re_exports_in_a_ring_resolve_to_nothing(project: Project) -> None:
    spec = project.spec()
    project.write("one.py", "from .two import enrol\n")
    project.write("two.py", "from .one import enrol\n")
    project.view(importing="from ..one import enrol")
    project.run()
    _assert_left(spec, "")


def test_a_relative_import_climbing_past_the_filesystem_resolves_to_nothing(
    project: Project,
) -> None:
    spec, view = project.spec(), project.view()
    dots = "." * (len(view.parents) + 2)
    project.write("tasks.py", f"from {dots}specs.enrolment import enrol\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]
    assert spec.exists()


def test_a_star_import_of_what_is_outside_the_run_blocks_nothing(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write("tasks.py", "from os.path import *\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_test_module_star_import_is_no_second_view(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write("conftest.py", "from .specs.enrolment import *\n")
    project.write("enrol_test.py", "from .specs.enrolment import *\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_an_import_nothing_reads_is_no_second_view(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write("reexport.py", f"{ABSOLUTE}\n".replace("{package}", project.package))
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_spec_nothing_imports_keeps_the_plain_note(project: Project) -> None:
    spec = project.spec()
    spec.write_text(spec.read_text() + "\nALL = [enrol]\n")
    project.run()
    assert (
        "success_status=202 is the view's or the action's: set success_status on the view, "
        "@service_action(..., success_status=...), or get_<action>_success_status on the viewset"
    ) in _markers(spec)


def test_an_earlier_run_s_note_is_not_followed(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.run(spec)
    project.run()
    assert _answers(view) == []
    _assert_left(spec, "")


# --- what is left, by the view -------------------------------------------------


@pytest.mark.parametrize(
    "body, reason",
    [
        ("    success_status = 200\n", "Enrol already declares success_status"),
        ("    def get_x(self):\n        pass\n\n    success_status = 200\n", "already declares"),
    ],
)
def test_a_view_already_answering_is_marked_and_the_spec_keeps_the_note(
    project: Project, body: str, reason: str
) -> None:
    spec, view = project.spec(), project.view()
    view.write_text(view.read_text() + body)
    project.run()
    assert reason in " ".join(_markers(view))
    notes = {note.split("=")[0]: note for note in _markers(spec)}
    assert notes["success_status"].startswith("success_status=202 is the view's or the action's")
    assert "the view in" in notes["success_status"]
    assert "see the comment there" in notes["success_status"]
    # The other answer had nothing in its way.
    assert notes["response_finalizer"].startswith("response_finalizer=stamp moved to")
    assert "    response_finalizer = stamp\n" in view.read_text()
    second = view.read_text(), spec.read_text()
    assert project.run(check=True)[0] == 0
    assert (view.read_text(), spec.read_text()) == second


def test_a_refused_answer_brings_no_import(project: Project) -> None:
    project.spec()
    view = project.view()
    view.write_text(view.read_text() + "    response_finalizer = None\n")
    project.run()
    assert "stamp" not in view.read_text()


def test_a_name_the_view_binds_otherwise_is_not_carried(project: Project) -> None:
    spec = project.spec()
    view = project.view()
    view.write_text(view.read_text() + "\n\ndef stamp():\n    pass\n")
    project.run()
    assert "not moved: stamp here is not the name it is there" in " ".join(_markers(view))
    assert _answers(view) == ["success_status"]
    notes = " ".join(_markers(spec))
    assert "response_finalizer=stamp is the view's or the action's" in notes
    assert "see the comment there" in notes
    ast.parse(view.read_text())


def test_a_name_the_class_binds_otherwise_is_not_carried(project: Project) -> None:
    project.spec()
    view = project.view()
    view.write_text(view.read_text() + "    stamp = None\n")
    project.run()
    assert "not moved: stamp here is not the name it is there" in " ".join(_markers(view))


def test_an_import_of_the_same_name_below_the_view_is_not_read(project: Project) -> None:
    project.spec()
    view = project.view()
    import_line = f"from {project.package}.specs.enrolment import stamp\n"
    view.write_text(view.read_text() + "\n\n" + import_line)
    project.run()
    assert "not moved: stamp here" in " ".join(_markers(view))


def test_a_second_binding_of_the_name_is_not_read(project: Project) -> None:
    project.spec()
    view = project.view(importing=f"{ABSOLUTE}, stamp\nstamp = None")
    project.run()
    assert "not moved: stamp here" in " ".join(_markers(view))


def test_a_function_local_import_of_the_name_is_not_read(project: Project) -> None:
    project.spec()
    local = "from {package}.specs.enrolment import stamp"
    view = project.view(importing=f"{ABSOLUTE}\n\n\ndef helper():\n    {local}\n\n\nstamp = None")
    project.run()
    assert "not moved: stamp here" in " ".join(_markers(view))


def test_another_import_of_the_name_is_not_read(project: Project) -> None:
    project.spec()
    view = project.view(importing=f"{ABSOLUTE}\nfrom elsewhere import stamp")
    project.run()
    assert "not moved: stamp here" in " ".join(_markers(view))


def test_an_import_of_the_same_name_above_the_view_is_reused(project: Project) -> None:
    project.spec()
    view = project.view(importing=f"{ABSOLUTE}, stamp")
    project.run()
    assert view.read_text().count("stamp") == 2
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_an_unparseable_file_stops_the_run_before_a_write(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec, view = project.spec(), project.view()
    broken = project.write("views/broken.py", "class Enrol(\n")
    before = spec.read_text(), view.read_text()
    code = main([str(project.root / project.package), "--root", str(project.root)])
    assert code == 2
    assert (spec.read_text(), view.read_text()) == before
    assert str(broken) in capsys.readouterr().err


def test_an_undecodable_file_stops_the_run_before_a_write(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = project.spec()
    before = spec.read_text()
    broken = project.root / project.package / "latin.py"
    broken.write_bytes(b"NAME = '\xff'\n")
    assert main([str(project.root / project.package), "--root", str(project.root)]) == 2
    assert spec.read_text() == before
    assert str(broken) in capsys.readouterr().err


# --- the value in the view -----------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "head, status, spelled",
    [
        (
            "from rest_framework import status\n",
            "status.HTTP_202_ACCEPTED",
            "from rest_framework import status",
        ),
        (
            "from rest_framework import status as st\n",
            "st.HTTP_202_ACCEPTED",
            "from rest_framework import status as st",
        ),
        (
            "import rest_framework.status\n",
            "rest_framework.status.HTTP_202_ACCEPTED",
            "import rest_framework.status",
        ),
        (
            "import rest_framework.status as st\n",
            "st.HTTP_202_ACCEPTED",
            "import rest_framework.status as st",
        ),
        ("ACCEPTED = 202\n", "ACCEPTED", "ACCEPTED"),
    ],
)
def test_a_name_is_carried_with_its_import(
    project: Project, head: str, status: str, spelled: str
) -> None:
    project.spec(status, head=head)
    view = project.view()
    project.run()
    assert spelled in view.read_text()
    response = _post(project.module().Enrol.as_view())
    assert response.status_code == 202, response.data


@pytest.mark.django_db
def test_a_relative_view_carries_the_spec_s_own_name_relatively(project: Project) -> None:
    project.spec()
    view = project.view(importing="from ..specs.enrolment import enrol")
    project.run()
    assert "from ..specs.enrolment import stamp\n" in view.read_text()
    assert _post(project.module().Enrol.as_view())["X-Answer"] == "stamped"


@pytest.mark.parametrize(
    "value",
    ["'created'", "None", "True", "200 + 2", "lambda: 202"],
)
def test_a_value_naming_nothing_moves_as_written(project: Project, value: str) -> None:
    project.spec(value)
    view = project.view()
    project.run()
    assert f"    success_status = {value}\n" in view.read_text()
    ast.parse(view.read_text())


@pytest.mark.parametrize(
    "head, value, why",
    [
        ("", "lambda *, pk: pk", "not a literal or a plain name"),
        ("", "compute()", "not a literal or a plain name"),
        ("", "len", "len is not bound in its module"),
        ("from .codes import ACCEPTED\n", "ACCEPTED", "ACCEPTED is imported relatively"),
        (
            "from rest_framework_services import SelectorKind\n",
            "SelectorKind",
            "SelectorKind is drfs'",
        ),
        (
            "try:\n    from a import CODE\nexcept ImportError:\n    from b import CODE\n",
            "CODE",
            "CODE is imported more than once",
        ),
        ("", "(  # created\n        202\n    )", "not a literal or a plain name"),
    ],
)
def test_a_value_that_would_not_resolve_is_left_and_the_view_imports(
    project: Project, head: str, value: str, why: str
) -> None:
    spec = project.spec(value, head=head)
    project.write("specs/codes.py", "ACCEPTED = 202\n")
    view = project.view()
    project.run()
    assert _answers(view) == ["response_finalizer"]
    notes = [note for note in _markers(spec) if note.startswith("success_status=")]
    assert len(notes) == 1
    assert "is the view's or the action's" in notes[0]
    assert why in notes[0]
    ast.parse(view.read_text())


@pytest.mark.django_db
def test_a_function_local_import_of_the_value_s_name_is_not_the_one_carried(
    project: Project,
) -> None:
    project.spec(
        "status.HTTP_202_ACCEPTED",
        head="def elsewhere():\n    from nowhere import status\n\n\n"
        "from rest_framework import status\n",
    )
    view = project.view()
    project.run()
    assert "from rest_framework import status" in view.read_text()
    assert _post(project.module().Enrol.as_view()).status_code == 202


def test_a_spec_s_own_name_through_a_module_s_re_export_is_left(project: Project) -> None:
    spec = project.spec()
    project.write("specs/__init__.py", "from .enrolment import enrol\n")
    view = project.view(importing="from {package} import specs", named="specs.enrol")
    project.run()
    assert _answers(view) == ["success_status"]
    assert "stamp is reached through a re-export" in " ".join(_markers(spec))


def test_a_spec_s_own_name_through_a_re_export_is_left(project: Project) -> None:
    spec = project.spec()
    project.write("specs/__init__.py", "from .enrolment import enrol\n")
    view = project.view(importing="from {package}.specs import enrol")
    project.run()
    assert _answers(view) == ["success_status"]
    assert "stamp is reached through a re-export" in " ".join(_markers(spec))
    ast.parse(view.read_text())


@pytest.mark.django_db
def test_every_written_view_still_imports_when_a_value_is_left(project: Project) -> None:
    project.spec("compute()", head="def compute():\n    return 202\n\n\n")
    project.view()
    project.run()
    assert project.module().Enrol.response_finalizer is not None
