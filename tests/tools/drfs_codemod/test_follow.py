"""A spec's answers follow its import into the view serving it from another module.

Every test drives ``main``, the codemod as it is run. A move is proven by a
real request through the rewritten view, imported from the written files; what
is left is proven by its note, and by the view still importing as it stands.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import shutil
import stat
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


def _routed(view: type, actions: dict[str, str] | None) -> object:
    """``view`` as a route serves it: a viewset by its action map, a view by itself."""
    return view.as_view(actions) if actions else view.as_view()


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


def _tree(project: Project) -> dict[str, bytes]:
    """Every file under the package, by path: a snapshot to compare, temp files and all."""
    base = project.root / project.package
    return {
        path.relative_to(base).as_posix(): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _chain(project: Project) -> tuple[Path, Path, Path]:
    """``enrol`` (spec) is served by ``m``, which builds ``sm``, served by ``n``: ``m`` receives and empties."""
    spec = project.spec()
    project.write(
        "views/m.py",
        "from rest_framework.permissions import AllowAny\n"
        "from rest_framework_services import ServiceCreateView, ServiceSpec\n"
        "from {package}.specs.enrolment import enrol\n"
        "from tests.testapp.serializers import AuthorSerializer\n\n"
        "sm = ServiceSpec(service=print, input_serializer=AuthorSerializer,"
        " permission_classes=[AllowAny], success_status=203)\n\n\n"
        "class VM(ServiceCreateView):\n    spec = enrol\n",
    )
    project.write(
        "views/n.py",
        "from rest_framework_services import ServiceCreateView\n"
        "from .m import sm\n\n\nclass VN(ServiceCreateView):\n    spec = sm\n",
    )
    return (
        spec,
        project.root / project.package / "views/m.py",
        project.root / project.package / "views/n.py",
    )


def _stopped(project: Project, capsys: pytest.CaptureFixture[str]) -> str:
    """Run the codemod over the package, which must stop on a write with exit 2: what it said."""
    assert main([str(project.root / project.package), "--root", str(project.root)]) == 2
    return capsys.readouterr().err


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes to a read-only file")
def test_a_file_that_cannot_be_written_changes_no_file(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, n = _chain(project)
    n.chmod(0o444)
    before = _tree(project)
    assert f"{n.resolve()}: not writable; nothing was written" in _stopped(project, capsys)
    assert _tree(project) == before


def test_a_failure_while_staging_changes_no_file_and_leaves_no_temp_file(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _chain(project)
    before = _tree(project)
    calls: list[Path] = []
    real = shutil.copymode

    def fail_the_second(src: object, dst: object, **kwargs: object) -> None:
        calls.append(Path(str(dst)))
        if len(calls) == 2:
            raise OSError("disk full")
        real(src, dst)

    monkeypatch.setattr(shutil, "copymode", fail_the_second)
    assert "disk full" in _stopped(project, capsys)
    assert len(calls) == 2
    assert _tree(project) == before


def test_a_failure_among_the_replaces_can_leave_some_written_and_no_temp_file(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _chain(project)
    before = _tree(project)
    real = os.replace
    calls: list[object] = []

    def fail_the_second(src: object, dst: object) -> None:
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("moving failed")
        real(src, dst)

    monkeypatch.setattr(os, "replace", fail_the_second)
    said = _stopped(project, capsys)
    assert "moving failed" in said
    assert re.search(r"; 1 of \d+ changed files were written before it", said)
    after = _tree(project)
    assert after.keys() == before.keys()
    assert [name for name in after if after[name] != before[name]] == ["views/m.py"]


def test_a_written_file_keeps_its_mode(project: Project) -> None:
    spec, view = project.spec(), project.view()
    view.chmod(0o754)
    spec.chmod(0o640)
    project.run()
    assert "success_status = 202" in view.read_text()
    assert stat.S_IMODE(view.stat().st_mode) == 0o754
    assert stat.S_IMODE(spec.stat().st_mode) == 0o640


def test_a_symlinked_file_is_written_through_and_stays_a_link(project: Project) -> None:
    project.spec()
    view = project.view()
    kept = project.root / "kept.py"
    kept.write_text(view.read_text())
    view.unlink()
    view.symlink_to(kept)
    project.run()
    assert view.is_symlink()
    assert "success_status = 202" in kept.read_text()


def test_a_file_named_twice_through_a_symlink_is_written_once(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    # A link beside its target is one module to the analysis, which keys modules
    # on the resolved path, so it is no second server; the run keys its files the
    # same way, so the file is staged and counted once, not written twice over.
    project.spec()
    view = project.view()
    (view.parent / "alias.py").symlink_to(view)
    code, _ = project.run()
    assert code == 0
    assert capsys.readouterr().err == "2 files changed\n"
    assert view.read_text().count("success_status = 202") == 1
    assert (view.parent / "alias.py").is_symlink()
    assert not [path for path in view.parent.iterdir() if path.suffix == ".tmp"]


def test_a_crlf_file_stays_crlf(project: Project) -> None:
    spec, view = project.spec(), project.view()
    for file in (spec, view):
        file.write_bytes(file.read_bytes().replace(b"\n", b"\r\n"))
    project.run()
    for file in (spec, view):
        written = file.read_bytes()
        assert written.count(b"\n") == written.count(b"\r\n"), file
    assert b"    success_status = 202\r\n" in view.read_bytes()
    assert project.run(check=True)[0] == 0


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
    project.write("tests.py", f"{ABSOLUTE}\n\n\nuse = enrol\n")
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


# --- a registration is no server and no blocker ---------------------------------

REGISTRY = """\
from rest_framework_services import SpecRegistry
{importing}

enrolment_spec_registry = SpecRegistry()
enrolment_spec_registry.register("ENROL", {named})
"""


def _registry(project: Project, body: str | None = None) -> Path:
    """A registry module importing the spec; ``body`` replaces the whole text when given."""
    source = body or REGISTRY.replace("{importing}", ABSOLUTE).replace("{named}", "enrol")
    return project.write("specs/registry.py", source)


@pytest.mark.django_db
def test_a_spec_registered_beside_its_one_view_moves(project: Project) -> None:
    spec, view = project.spec(), project.view()
    registry = _registry(project)
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]
    assert "success_status=202," not in spec.read_text()
    # The registration is left as the tool writes it today: the spec is still imported and registered.
    written = registry.read_text()
    assert f"from {project.package}.specs.enrolment import enrol\n" in written
    assert 'enrolment_spec_registry.register("ENROL", enrol)\n' in written
    assert _markers(registry) == []
    response = _post(project.module().Enrol.as_view())
    assert response.status_code == 202, response.data


def test_a_spec_registered_through_its_module_moves(project: Project) -> None:
    project.spec()
    view = project.view()
    _registry(
        project,
        REGISTRY.replace("{importing}", "from ..specs import enrolment").replace(
            "{named}", "enrolment.enrol"
        ),
    )
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_registry_built_from_the_kernel_is_one(project: Project) -> None:
    project.spec()
    view = project.view()
    registry = _registry(project)
    registry.write_text(
        registry.read_text().replace(
            "from rest_framework_services import SpecRegistry",
            "from django_service_specs import SpecRegistry",
        )
    )
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


def test_a_spec_only_registered_keeps_the_plain_note(project: Project) -> None:
    spec = project.spec()
    _registry(project)
    project.run()
    assert (
        "success_status=202 is the view's or the action's: set success_status on the view, "
        "@service_action(..., success_status=...), or get_<action>_success_status on the viewset"
    ) in _markers(spec)
    assert "used otherwise" not in " ".join(_markers(spec))


def test_a_registration_beside_two_serving_modules_reports_two(project: Project) -> None:
    spec, view = project.spec(), project.view()
    other = project.view(relative="views/second.py")
    _registry(project)
    project.run()
    assert _answers(view) == [] == _answers(other)
    _assert_left(spec, "served from 2 modules (")
    assert "registry" not in " ".join(_markers(spec))


def test_a_module_registering_and_serving_the_spec_is_one_server(project: Project) -> None:
    project.spec()
    view = project.view()
    view.write_text(
        view.read_text()
        + "\nfrom rest_framework_services import SpecRegistry\n\n"
        + 'registry = SpecRegistry()\nregistry.register("ENROL", enrol)\n'
    )
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


# Each of these keeps the spec blocked. Beside ``test_a_spec_registered_beside_its_one_view_moves``
# every one is the registration with one conjunct of ``_Analysis._registration`` taken away:
# the method is ``register``, the receiver is a name, bound once at module level to a call of
# ``SpecRegistry`` imported from drfs or the kernel, and the spec is itself the argument.
NOT_A_REGISTRATION = {
    # not the ``register`` method
    "other method": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()",
        "r.add(enrol)",
    ),
    # not a name: ``admin.site`` is an attribute
    "admin site": ("from django.contrib import admin", "r = None", "admin.site.register(enrol)"),
    # a name of unknown origin
    "unknown class": (
        "from elsewhere import SpecRegistry",
        "r = SpecRegistry()",
        "r.register(enrol)",
    ),
    "unknown receiver": ("from elsewhere import r", "", "r.register(enrol)"),
    # not a name at all
    "call receiver": (
        "from rest_framework_services import SpecRegistry",
        "def make():\n    return SpecRegistry()",
        "make().register(enrol)",
    ),
    # a construction of another class, even the kernel's
    "other class": (
        "from django_service_specs import Affordance",
        "r = Affordance()",
        "r.register(enrol)",
    ),
    # a name that is not bound to a construction
    "not a construction": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry",
        "r.register(enrol)",
    ),
    "built by a function": (
        "from rest_framework_services import SpecRegistry",
        "r = make(SpecRegistry)",
        "r.register(enrol)",
    ),
    # bound more than once
    "bound twice": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()\nr = SpecRegistry()",
        "r.register(enrol)",
    ),
    # bound in a function, not the module
    "built in a function": (
        "from rest_framework_services import SpecRegistry",
        "def build():\n    r = SpecRegistry()\n    r.register(enrol)",
        "",
    ),
    "shadowed in a function": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()\n\n\ndef build(r):\n    r.register(enrol)",
        "",
    ),
    # the spec is part of the argument, not the argument
    "wrapped": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()",
        "r.register(wrap(enrol))",
    ),
    "unpacked": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()",
        "r.register(*enrol)",
    ),
    "called": (
        "from rest_framework_services import SpecRegistry",
        "r = SpecRegistry()",
        "r.register(enrol.service)",
    ),
}


@pytest.mark.parametrize("shape", NOT_A_REGISTRATION)
def test_a_use_that_is_not_a_registration_still_blocks(project: Project, shape: str) -> None:
    importing, setup, use = NOT_A_REGISTRATION[shape]
    spec, view = project.spec(), project.view()
    project.write("specs/registry.py", f"{importing}\n{ABSOLUTE}\n\n{setup}\n{use}\n")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, f"used otherwise in {project.package}/specs/registry.py")


def test_a_registry_imported_from_another_module_still_blocks(project: Project) -> None:
    spec, view = project.spec(), project.view()
    project.write(
        "specs/registries.py",
        "from rest_framework_services import SpecRegistry\n\nr = SpecRegistry()\n",
    )
    project.write(
        "specs/registry.py",
        f"from .registries import r\n{ABSOLUTE}\n\nr.register(enrol)\n",
    )
    project.run()
    assert _answers(view) == []
    _assert_left(spec, f"used otherwise in {project.package}/specs/registry.py")


def test_a_registration_beside_another_use_still_blocks(project: Project) -> None:
    spec, view = project.spec(), project.view()
    registry = _registry(project)
    registry.write_text(registry.read_text() + "\nALL = [enrol]\n")
    project.run()
    assert _answers(view) == []
    _assert_left(spec, f"used otherwise in {project.package}/specs/registry.py")


# --- what is left, by the view -------------------------------------------------


@pytest.mark.parametrize(
    "body, reason",
    [
        ("    success_status = 200\n", "Enrol already declares success_status"),
        ("    success_status: int = 200\n", "Enrol already declares success_status"),
        ("    if True:\n        success_status = 200\n", "Enrol already declares success_status"),
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


# --- two specs arriving in one view module --------------------------------------

NUMBERED_SPEC = """\
from rest_framework.permissions import AllowAny
from rest_framework_services import ServiceSpec
{head}
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

CODE = {code}


def create_author(*, data):
    return Author.objects.create(name=data["name"])


def finalize(*, response):
    response["X-Answer"] = "{who}"


{who}_spec = ServiceSpec(
    service=create_author,
    input_serializer=AuthorSerializer,
    output_serializer=AuthorSerializer,
    permission_classes=[AllowAny],
    success_status={status},
    response_finalizer=finalize,
)
"""

BILLING_VIEW = """\
from rest_framework_services import ServiceCreateView
from {package}.specs.first import first_spec
from {package}.specs.second import second_spec


class FirstView(ServiceCreateView):
    spec = first_spec


class SecondView(ServiceCreateView):
    spec = second_spec
"""


def _numbered(project: Project, who: str, code: int, status: str = "CODE", head: str = "") -> Path:
    source = NUMBERED_SPEC.replace("{who}", who).replace("{code}", str(code))
    return project.write(
        f"specs/{who}.py", source.replace("{status}", status).replace("{head}", head)
    )


@pytest.mark.django_db
def test_two_arrivals_of_one_name_from_two_modules_do_not_share_it(project: Project) -> None:
    first, second = _numbered(project, "first", 203), _numbered(project, "second", 202)
    view = project.write("views/billing.py", BILLING_VIEW)
    project.run()
    module = project.module("views.billing")
    ours = _post(module.FirstView.as_view())
    assert (ours.status_code, ours["X-Answer"]) == (203, "first")
    other = _post(module.SecondView.as_view())
    assert other.status_code == 201
    assert "X-Answer" not in other
    assert _answers(view) == ["success_status", "response_finalizer"]
    assert "moved to FirstView.success_status" in " ".join(_markers(first))
    markers = " ".join(_markers(view))
    assert "not moved: CODE here" in markers
    assert "not moved: finalize here" in markers
    for note in _markers(second):
        assert "see the comment there" in note
        assert "moved to" not in note
    assert project.run(check=True)[0] == 0


@pytest.mark.django_db
def test_two_arrivals_of_one_name_from_one_module_are_one_import(project: Project) -> None:
    both = _numbered(project, "first", 203)
    both.write_text(
        both.read_text()
        + both.read_text().split("ServiceSpec(\n")[0][:0]
        + (
            "\nsecond_spec = ServiceSpec(\n    service=create_author,\n"
            "    input_serializer=AuthorSerializer,\n    permission_classes=[AllowAny],\n"
            "    success_status=CODE,\n    response_finalizer=finalize,\n)\n"
        )
    )
    project.write(
        "views/billing.py",
        BILLING_VIEW.replace("specs.second import", "specs.first import"),
    )
    project.run()
    module = project.module("views.billing")
    for view in (module.FirstView, module.SecondView):
        response = _post(view.as_view())
        assert (response.status_code, response["X-Answer"]) == (203, "first")


@pytest.mark.django_db
def test_one_object_imported_with_and_without_an_alias_is_left(project: Project) -> None:
    first = _numbered(
        project,
        "first",
        0,
        "status.HTTP_202_ACCEPTED",
        "from rest_framework import status\n",
    )
    second = _numbered(
        project,
        "second",
        0,
        "st.HTTP_203_NON_AUTHORITATIVE_INFORMATION",
        "from rest_framework import status as st\n",
    )
    view = project.write("views/billing.py", BILLING_VIEW)
    project.run()
    ast.parse(view.read_text())
    assert "from rest_framework import status\n" in view.read_text()
    assert "status as st" not in view.read_text()
    assert "not moved: st here" in " ".join(_markers(view))
    assert "see the comment there" in " ".join(_markers(second))
    module = project.module("views.billing")
    assert _post(module.FirstView.as_view()).status_code == 202
    assert "moved to FirstView.success_status" in " ".join(_markers(first))


# --- a subclass serving another spec ---------------------------------------------

PLAIN_SPEC = """\
from rest_framework.permissions import AllowAny
from rest_framework_services import ServiceSpec

from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


def create_author(*, data):
    return Author.objects.create(name=data["name"])


plain = ServiceSpec(
    service=create_author,
    input_serializer=AuthorSerializer,
    output_serializer=AuthorSerializer,
    permission_classes=[AllowAny],
)
"""

CHILD = """\
{importing}
from {package}.specs.plain import plain


class Child({base}):
    {body}
"""

POST_AS_VIEW = None
CREATE_AS_VIEW = {"post": "create"}


def _child(project: Project, importing: str, base: str, body: str) -> Path:
    source = CHILD.replace("{importing}", importing).replace("{base}", base)
    return project.write("views/child.py", source.replace("{body}", body))


def _left_because_of_a_subclass(spec: Path, *views: Path) -> None:
    for view in views:
        assert _answers(view) == []
        ast.parse(view.read_text())
    _assert_left(spec, "see the comment there")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "template, body, actions, declares",
    [
        (ATTRIBUTE_VIEW, "spec = plain", POST_AS_VIEW, "spec"),
        (ATTRIBUTE_VIEW, "spec: object = plain", POST_AS_VIEW, "spec"),
        (HOOK_VIEW, 'action_specs = {"create": plain}', CREATE_AS_VIEW, "action_specs"),
    ],
    ids=["spec", "annotated spec", "action_specs"],
)
@pytest.mark.parametrize(
    "importing, base",
    [
        ("", "Enrol"),
        ("from .enrolment import Enrol", "Enrol"),
        ("from .enrolment import Enrol as Base", "Base"),
        ("from . import enrolment", "enrolment.Enrol"),
        ("from {package}.views import enrolment as e", "e.Enrol"),
        ("import {package}.views.enrolment as v", "v.Enrol"),
        ("import {package}.views.enrolment", "{package}.views.enrolment.Enrol"),
    ],
    ids=["same module", "by name", "aliased", "module", "module aliased", "dotted alias", "dotted"],
)
def test_a_subclass_serving_another_spec_does_not_inherit_the_answer(
    project: Project,
    template: str,
    body: str,
    actions: dict[str, str] | None,
    declares: str,
    importing: str,
    base: str,
) -> None:
    spec, view = project.spec(), project.view(template)
    project.write("specs/plain.py", PLAIN_SPEC)
    if importing:
        _child(project, importing, base, body)
        child_module, child_file = "views.child", project.root / project.package / "views/child.py"
    else:
        view.write_text(
            view.read_text()
            + f"\nfrom {project.package}.specs.plain import plain\n\n\n"
            + f"class Child(Enrol):\n    {body}\n"
        )
        child_module, child_file = "views.enrolment", view
    project.run()
    _left_because_of_a_subclass(spec, view)
    assert f"Child subclasses it and declares its own {declares}" in " ".join(_markers(view)) or (
        f"Child in {project.package}/views/child.py subclasses it and declares its own {declares}"
        in " ".join(_markers(view))
    )
    assert child_file.exists()
    response = _post(_routed(project.module(child_module).Child, actions))
    assert response.status_code == 201, response.data
    assert "X-Answer" not in response
    assert project.run(check=True)[0] == 0


@pytest.mark.django_db
def test_a_subclass_through_a_package_re_export_does_not_inherit_the_answer(
    project: Project,
) -> None:
    spec, view = project.spec(), project.view()
    project.write("specs/plain.py", PLAIN_SPEC)
    project.write("views/__init__.py", "from .enrolment import Enrol\n")
    _child(project, "from {package}.views import Enrol", "Enrol", "spec = plain")
    project.run()
    _left_because_of_a_subclass(spec, view)
    assert _post(project.module("views.child").Child.as_view()).status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("together", [False, True], ids=["across modules", "in one module"])
def test_a_subclass_of_a_subclass_does_not_inherit_the_answer(
    project: Project, together: bool
) -> None:
    spec, view = project.spec(), project.view()
    project.write("specs/plain.py", PLAIN_SPEC)
    middle = "class Middle(Enrol):\n    pass\n"
    if together:
        child = _child(project, "from .enrolment import Enrol", "Middle", "spec = plain")
        child.write_text(child.read_text().replace("class Child", f"{middle}\n\nclass Child"))
    else:
        project.write("views/middle.py", f"from .enrolment import Enrol\n\n\n{middle}")
        _child(project, "from .middle import Middle", "Middle", "spec = plain")
    project.run()
    _left_because_of_a_subclass(spec, view)
    assert _post(project.module("views.child").Child.as_view()).status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("elsewhere", [False, True])
def test_a_subclass_that_declares_neither_inherits_the_answer_as_it_should(
    project: Project, elsewhere: bool
) -> None:
    project.spec()
    view = project.view()
    project.write("specs/plain.py", PLAIN_SPEC)
    if elsewhere:
        _child(project, "from .enrolment import Enrol", "Enrol", "other = plain")
    else:
        view.write_text(view.read_text() + "\n\nclass Child(Enrol):\n    other = None\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]
    child = project.module("views.child" if elsewhere else "views.enrolment")
    response = _post(child.Child.as_view())
    assert (response.status_code, response["X-Answer"]) == (202, "stamped")


def test_a_subclass_the_run_cannot_resolve_is_not_seen(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write("specs/plain.py", PLAIN_SPEC)
    project.write(
        "views/child.py",
        "import {package}.specs.plain as Plain\n\n\n"
        "def load():\n    from .enrolment import Enrol\n\n    return Enrol\n\n\n"
        "Enrol = load()\n\n\nclass Child(Enrol):\n    spec = None\n\n\n"
        "class Module(Plain):\n    spec = None\n\n\nclass Missing(Plain.nothing):\n    spec = None\n\n\n"
        "Alias = Enrol\n\n\nclass Renamed(Alias):\n    spec = None\n",
    )
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


OWN_MODULE_VIEWS = {
    "view": ("ServiceCreateView", "spec = enrol", "spec = plain", POST_AS_VIEW),
    "hook": (
        "ServiceViewSet",
        'action_specs = {"create": enrol}',
        'action_specs = {"create": plain}',
        CREATE_AS_VIEW,
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("form", ["view", "hook"])
def test_a_subclass_in_the_specs_own_module_does_not_inherit_the_answer(
    project: Project, form: str
) -> None:
    server, serving, redeclared, actions = OWN_MODULE_VIEWS[form]
    spec = project.spec()
    spec.write_text(
        spec.read_text().replace(
            "from rest_framework_services import ServiceSpec",
            f"from rest_framework_services import {server}, ServiceSpec",
        )
        + "\nplain = ServiceSpec(\n    service=create_author,\n    input_serializer=AuthorSerializer,"
        f"\n    permission_classes=[AllowAny],\n)\n\n\nclass Base({server}):\n    {serving}\n"
        f"\n\nclass Child(Base):\n    {redeclared}\n"
    )
    project.run()
    assert _answers(spec) == []
    assert "Child subclasses it and declares its own" in " ".join(_markers(spec))
    response = _post(_routed(project.module("specs.enrolment").Child, actions))
    assert response.status_code == 201, response.data
    assert "X-Answer" not in response


# --- a star import of a package re-exporting the spec -----------------------------


@pytest.mark.parametrize(
    "package",
    [
        "from .enrolment import enrol, stamp\n",
        "import os\nfrom .enrolment import enrol, stamp\n",
        "from .enrolment import *\n",
    ],
    ids=["by name", "beside a plain import", "by star"],
)
def test_a_star_import_of_a_re_exporting_package_is_a_second_view(
    project: Project, package: str
) -> None:
    spec, one = project.spec(), project.view()
    project.write("specs/__init__.py", package)
    other = project.view(importing="from {package}.specs import *", relative="views/second.py")
    project.run()
    assert _answers(one) == _answers(other) == []
    _assert_left(spec, "star-imported in")


def test_a_test_module_star_import_of_a_package_is_no_second_view(project: Project) -> None:
    project.spec()
    view = project.view()
    project.write("specs/__init__.py", "from .enrolment import enrol, stamp\n")
    project.write("conftest.py", "from .specs import *\n")
    project.run()
    assert _answers(view) == ["success_status", "response_finalizer"]


# --- an annotated name in the view --------------------------------------------------


def test_an_annotated_name_the_class_binds_otherwise_is_not_carried(project: Project) -> None:
    project.spec()
    view = project.view()
    view.write_text(view.read_text() + "    stamp: object = None\n")
    project.run()
    assert "not moved: stamp here is not the name it is there" in " ".join(_markers(view))
    ast.parse(view.read_text())


# --- a star import in the view --------------------------------------------------------


@pytest.mark.django_db
def test_a_star_import_in_the_view_may_bind_the_name_the_answer_carries(project: Project) -> None:
    spec = project.spec("CODE", head="CODE = 202\n")
    project.write("constants.py", "CODE = 418\n")
    view = project.view(importing=f"{ABSOLUTE}\nfrom {{package}}.constants import *")
    view.write_text(view.read_text() + "\n\nOTHER = CODE\n")
    project.run()
    assert _answers(view) == []
    assert "not moved: CODE here may be bound by a star import" in " ".join(_markers(view))
    _assert_left(spec, "see the comment there")
    ast.parse(view.read_text())
    assert project.module().OTHER == 418


def test_a_star_import_in_the_view_does_not_stop_a_value_naming_nothing(project: Project) -> None:
    project.spec("202")
    project.write("constants.py", "CODE = 418\n")
    view = project.view(importing=f"{ABSOLUTE}\nfrom {{package}}.constants import *")
    project.run()
    assert _answers(view) == ["success_status"]


# --- two serving modules of one name ----------------------------------------------------


def test_two_serving_modules_with_one_display_name_are_two(
    project: Project, tmp_path: Path
) -> None:
    spec = project.spec()
    third = project.view(importing="from ..specs.enrolment import enrol")
    first = project.view(importing="from ..specs.enrolment import enrol", relative="orders/api.py")
    second = project.view(
        importing="from ..specs.enrolment import enrol", relative="billing/api.py"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    report = tmp_path / "report.txt"
    main([str(project.root / project.package), "--root", str(elsewhere), "--report", str(report)])
    assert _answers(first) == _answers(second) == _answers(third) == []
    # The file with a name of its own keeps it.
    _assert_left(spec, "served from 3 modules (billing/api.py, enrolment.py, orders/api.py)")


@pytest.mark.django_db
def test_a_module_imported_with_and_without_an_alias_moves_both(project: Project) -> None:
    _numbered(
        project,
        "first",
        0,
        "rest_framework.status.HTTP_202_ACCEPTED",
        "import rest_framework.status\n",
    )
    _numbered(
        project,
        "second",
        0,
        "st.HTTP_203_NON_AUTHORITATIVE_INFORMATION",
        "import rest_framework.status as st\n",
    )
    view = project.write("views/billing.py", BILLING_VIEW)
    project.run()
    module = project.module("views.billing")
    assert _post(module.FirstView.as_view()).status_code == 202
    assert _post(module.SecondView.as_view()).status_code == 203
    assert "under another name" not in " ".join(_markers(view))
    assert "import rest_framework.status as st\n" in view.read_text()
