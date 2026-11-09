"""``python -m drfs_codemod PATH...``: rewrite each file in place and report each site left.

The report is one line per site, ``path:line: reason``, in the order of the
files and their lines, then a count. A line is the file's as it stands after
the run: the written file's for one rewritten, where the marker sits above
the statement named. ``--check`` writes
nothing and exits 1 if any file would change, which is how a second run proves
it has nothing left to do, and it reports what a run would move and leave.

The files named are read as one run, since a spec's answers follow its import
into the view serving it from another module. Nothing is written until every
file has parsed; one that does not stops the run with exit 2. A view is written
before a spec, so a failed write never takes an answer from a spec that has not
reached its view.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

from drfs_codemod.follow import Unreadable, read_sources, rewrite_files
from drfs_codemod.rewrite import Finding, rewrite_source

_SKIPPED = {"node_modules", "site-packages", "__pycache__"}


def python_files(paths: list[Path]) -> Iterator[Path]:
    """Each ``.py`` file named or under a directory named, outside hidden and installed trees."""
    for path in paths:
        if path.is_file():
            yield path
            continue
        for file in sorted(path.rglob("*.py")):
            parts = file.relative_to(path).parts
            if not any(part.startswith(".") or part in _SKIPPED for part in parts):
                yield file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drfs_codemod", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to rewrite")
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help=(
            "where a dotted module is looked up, to read a selector's signature or to follow a "
            "view's import of its spec (repeatable; default: .)"
        ),
    )
    parser.add_argument(
        "--check", action="store_true", help="write nothing; exit 1 if a file would change"
    )
    parser.add_argument("--report", type=Path, help="write the report here instead of to stdout")
    args = parser.parse_args(argv)
    roots = args.root or [Path.cwd()]
    files = {file.resolve(): file for file in python_files(args.paths)}
    try:
        sources = read_sources(list(files.values()))
        results = rewrite_files(sources, roots)
    except Unreadable as error:
        sys.stderr.write(f"{error}\n")
        return 2
    changed = [file for file, result in results.items() if result.output != sources[file]]
    if not args.check:
        for file in sorted(changed, key=lambda file: not results[file].receives):
            file.write_text(results[file].output, encoding="utf-8")
    findings: list[Finding] = []
    for file, result in results.items():
        left = result.findings
        if file in changed and not args.check:
            # Read back, so each line is the written file's: every site
            # left carries a marker, which a run over the output reports
            # at its own line, and nothing else changes on that run.
            _, left = rewrite_source(result.output, file, roots)
        findings.extend(left)
    lines = [str(finding) for finding in findings]
    lines.append(f"{len(findings)} sites left in {len({f.path for f in findings})} files")
    report = "\n".join(lines) + "\n"
    if args.report is not None:
        args.report.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    verb = "would change" if args.check else "changed"
    sys.stderr.write(f"{len(changed)} files {verb}\n")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
