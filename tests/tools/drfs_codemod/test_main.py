"""``python -m drfs_codemod``: the files it rewrites, the report it writes, and ``--check``."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
from drfs_codemod.__main__ import main, python_files
from drfs_codemod.rewrite import MARKER

SPECS = textwrap.dedent(
    """\
    from rest_framework_services import SelectorKind, SelectorSpec, ServiceSpec


    def by_pk(*, pk: int):
        return pk


    target = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=by_pk)

    create = ServiceSpec(
        service=print,
        input_serializer=In,
        permission_classes=[],
        success_status=201,
    )
    """
)

_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<reason>.+)$")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "specs.py").write_text(SPECS)
    (tmp_path / "app" / "untouched.py").write_text("VALUE = 1\n")
    return tmp_path


def _report(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _marker_above(lines: list[str], line: int) -> set[str]:
    """The markers in the comment block directly above line ``line`` (1-based)."""
    found: set[str] = set()
    index = line - 2
    while index >= 0 and lines[index].lstrip().startswith("#"):
        text = lines[index].strip()
        if text.startswith(f"# {MARKER} "):
            found.add(text[len(f"# {MARKER} ") :])
        index -= 1
    return found


def test_each_report_line_names_the_written_file_s_marked_statement(project: Path) -> None:
    report = project / "report.txt"
    assert main([str(project / "app"), "--root", str(project), "--report", str(report)]) == 0
    lines = _report(report)
    assert lines[-1] == "3 sites left in 1 files"
    written = (project / "app" / "specs.py").read_text().splitlines()
    reasons = []
    for entry in lines[:-1]:
        match = _LINE.match(entry)
        assert match is not None, entry
        assert match["path"] == str(project / "app" / "specs.py")
        assert match["reason"] in _marker_above(written, int(match["line"]))
        reasons.append(match["reason"].split(" ")[0])
    assert reasons == ["selector=by_pk", "an", "success_status=201"]


def test_a_second_run_writes_nothing_and_reports_the_same(project: Path) -> None:
    first, second = project / "first.txt", project / "second.txt"
    main([str(project / "app"), "--root", str(project), "--report", str(first)])
    written = (project / "app" / "specs.py").read_text()
    assert main([str(project / "app"), "--root", str(project), "--check"]) == 0
    main([str(project / "app"), "--root", str(project), "--report", str(second)])
    assert (project / "app" / "specs.py").read_text() == written
    assert _report(second) == _report(first)


def test_check_writes_nothing_and_fails_while_a_file_would_change(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(project / "app"), "--root", str(project), "--check"]) == 1
    assert (project / "app" / "specs.py").read_text() == SPECS
    out, err = capsys.readouterr()
    assert err == "1 files would change\n"
    # Unwritten, a line is the file's as it stands: the spec's own line.
    assert out.splitlines()[0].startswith(f"{project / 'app' / 'specs.py'}:8: selector=by_pk")


def test_the_report_goes_to_stdout_by_default(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(project / "app" / "untouched.py")]) == 0
    out, err = capsys.readouterr()
    assert out == "0 sites left in 0 files\n"
    assert err == "0 files changed\n"


def test_hidden_and_installed_trees_are_skipped(tmp_path: Path) -> None:
    for relative in (
        "app/specs.py",
        "app/.hidden/specs.py",
        ".venv/lib/specs.py",
        "app/node_modules/specs.py",
        "app/site-packages/specs.py",
        "app/__pycache__/specs.py",
        "app/notes.txt",
    ):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text("")
    named = tmp_path / ".venv" / "lib" / "specs.py"
    assert list(python_files([tmp_path, named])) == [tmp_path / "app" / "specs.py", named]


def test_a_crlf_file_comes_back_crlf_with_its_markers_and_imports(project: Path) -> None:
    specs = project / "app" / "specs.py"
    specs.write_bytes(SPECS.replace("\n", "\r\n").encode())
    assert main([str(project / "app"), "--root", str(project)]) == 0
    written = specs.read_bytes()
    assert b"SerializerValidator" in written
    assert b"# drfs-codemod:" in written
    assert written.count(b"\n") == written.count(b"\r\n")
    # Nothing is left to change, and a file already in the kernel's spelling stays as it was.
    assert main([str(project / "app"), "--root", str(project), "--check"]) == 0
    untouched = project / "app" / "untouched.py"
    untouched.write_bytes(b"VALUE = 1\r\n")
    assert main([str(project / "app"), "--root", str(project), "--check"]) == 0
    assert untouched.read_bytes() == b"VALUE = 1\r\n"
