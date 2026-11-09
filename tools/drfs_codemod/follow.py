"""A spec's ``success_status`` and ``response_finalizer``, followed into a view in another module.

``rewrite_source`` sees one file, and a kernel spec has no seat for either
answer, so a ``specs/`` plus ``views/`` layout needs the run's files read
together. Three steps, each pure, with no file written by any of them:

1. Read every file (``_Index``): which specs carry an answer, and each module
   that imports each spec, however it spells the import.
2. Rewrite the views, to learn what each one actually placed. A view that
   refuses (it declares that answer already, or the value's name means something
   else there) marks itself and places nothing.
3. Rewrite every file again, the specs now saying where each answer went, or
   why it stayed. A spec never claims a placement that did not happen.

Only what is certain moves. Otherwise the spec keeps its note, which carries the
value, and the reason it was not followed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import libcst as cst
from libcst.metadata import ImportAssignment

from drfs_codemod.rewrite import (
    DRFS,
    Arrival,
    Carried,
    Finding,
    Followed,
    ImportSite,
    _Analysis,
    _source,
    rewrite_module,
    scan_source,
)
from drfs_codemod.signatures import module_file

_Spec = tuple[Path, str]

_NOT_A_NAME = "its value is not a literal or a plain name"


class Unreadable(Exception):
    """A file the run cannot read, which stops it before anything is written."""


@dataclass(frozen=True)
class Rewritten:
    """One file's result: its text, what is left in it, and whether an answer arrives in it."""

    output: str
    findings: list[Finding]
    receives: bool


@dataclass(frozen=True)
class _Module:
    file: Path
    analysis: _Analysis


@dataclass(frozen=True)
class _Server:
    """A module naming a spec by ``key``, all of whose uses of that name serve it."""

    file: Path
    key: str
    # How this module spells the spec's own module, for a name defined there.
    # ``None`` when it reaches the spec through a re-export, which holds only the spec.
    reach: tuple[int, str] | None


@dataclass
class _Plan:
    arrivals: dict[str, list[Arrival]] = field(default_factory=dict)
    left: dict[tuple[str, str], str] = field(default_factory=dict)
    moved: dict[tuple[str, str], str] = field(default_factory=dict)


def read_sources(files: Iterable[Path]) -> dict[Path, str]:
    """Each file's text, or ``Unreadable`` naming the first that is not UTF-8."""
    sources: dict[Path, str] = {}
    for file in files:
        try:
            sources[file] = file.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise Unreadable(f"{file}: not UTF-8 ({error.reason}); nothing was written") from error
    return sources


def _is_test(where: str) -> bool:
    """Whether a module is a test's, by its path under its root: one reads a spec, not serves it."""
    path = PurePosixPath(where)
    name = path.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "tests" in path.parts[:-1]
    )


class _Index:
    """Every file of the run, read once, and what is certain about each spec with an answer."""

    def __init__(self, sources: Mapping[Path, str], roots: Sequence[Path]) -> None:
        self.roots = [root.resolve() for root in roots]
        self.modules: dict[Path, _Module] = {}
        for path, source in sources.items():
            try:
                analysis, _ = scan_source(source, path, roots)
            except cst.ParserSyntaxError as error:
                raise Unreadable(
                    f"{path}:{error.raw_line}: cannot be parsed ({error.message}); "
                    "nothing was written"
                ) from error
            self.modules[path.resolve()] = _Module(path.resolve(), analysis)
        self.blocked: dict[_Spec, str] = {}
        self.servers: dict[_Spec, dict[tuple[Path, str], _Server]] = {}

    def display(self, file: Path) -> str:
        """``file`` under its root, for a comment written into a project: no absolute path."""
        for root in self.roots:
            if file.is_relative_to(root):
                return file.relative_to(root).as_posix()
        return file.name

    # --- resolving an import ----------------------------------------------------

    def _file(self, importer: Path, relative: int, dotted: str) -> Path | None:
        """The file of this run a module spelled so from ``importer`` is, else ``None``."""
        if relative:
            if relative > len(importer.parents):
                return None
            base = importer.parents[relative - 1]
            found = module_file([base], dotted) if dotted else base / "__init__.py"
        else:
            found = module_file(self.roots, dotted)
        resolved = found.resolve() if found is not None else None
        return resolved if resolved in self.modules else None

    def _origin(
        self, file: Path | None, name: str, seen: frozenset[_Spec] = frozenset()
    ) -> _Spec | None:
        """The spec ``name`` in ``file`` is, through any re-export made under the same name."""
        if file is None or (file, name) in seen:
            return None
        analysis = self.modules[file].analysis
        if name in analysis.answers:
            return file, name
        for site in analysis.imported:
            # An aliased or function-local re-export is blocked by its own census entry.
            if site.local == name == site.carried.obj:
                carried = site.carried
                target = self._file(file, carried.relative, carried.module)
                return self._origin(target, name, seen | {(file, name)})
        return None

    # --- who imports each spec --------------------------------------------------

    def _census(self) -> None:
        for module in self.modules.values():
            for site in module.analysis.imported:
                if site.carried.obj == "*":
                    self._star(module, site)
                    continue
                if site.carried.obj is not None:
                    self._by_name(module, site)
                self._by_attribute(module, site)

    def _star(self, module: _Module, site: ImportSite) -> None:
        where = self.display(module.file)
        carried = site.carried
        file = self._file(module.file, carried.relative, carried.module)
        if file is None or _is_test(where):
            return
        for variable in self.modules[file].analysis.answers:
            self.blocked.setdefault((file, variable), f"star-imported in {where}")

    def _by_name(self, module: _Module, site: ImportSite) -> None:
        carried = site.carried
        assert carried.obj is not None
        file = self._file(module.file, carried.relative, carried.module)
        spec = self._origin(file, carried.obj)
        if spec is None:
            return
        bound = module.analysis.module_scope.assignments[site.local]
        references = {
            id(access.node)
            for assignment in bound
            if isinstance(assignment, ImportAssignment)
            for access in assignment.references
        }
        reach = (carried.relative, carried.module) if spec[0] == file else None
        self._note_use(
            module, site, spec, site.local, references, reach, aliased=site.local != carried.obj
        )

    def _by_attribute(self, module: _Module, site: ImportSite) -> None:
        carried = site.carried
        if carried.obj is not None:
            base = ".".join(part for part in (carried.module, carried.obj) if part)
        else:
            base = carried.module if carried.asname else carried.module.split(".")[0]
        for dotted, nodes in module.analysis.attributes.items():
            head, *within, variable = dotted.split(".")
            if head != site.local:
                continue
            spelled = ".".join([base, *within])
            file = self._file(module.file, carried.relative, spelled)
            spec = self._origin(file, variable)
            if spec is None:
                continue
            reach = (carried.relative, spelled) if spec[0] == file else None
            references = {id(node) for node in nodes}
            self._note_use(module, site, spec, dotted, references, reach, aliased=False)

    def _note_use(
        self,
        module: _Module,
        site: ImportSite,
        spec: _Spec,
        key: str,
        references: set[int],
        reach: tuple[int, str] | None,
        *,
        aliased: bool,
    ) -> None:
        """Count a module as serving ``spec``, or record why that cannot be told."""
        where = self.display(module.file)
        sites = module.analysis.use_sites.get(key, [])
        if not sites and _is_test(where):
            return
        if not site.top_level:
            self.blocked.setdefault(spec, f"imported inside a function in {where}")
        elif aliased:
            self.blocked.setdefault(spec, f"imported as {site.local} in {where}")
        elif references - {id(use.reference) for use in sites}:
            self.blocked.setdefault(spec, f"used otherwise in {where}")
        elif sites:
            self.servers.setdefault(spec, {})[module.file, key] = _Server(module.file, key, reach)

    # --- what each spec's answers do --------------------------------------------

    def plan(self) -> dict[Path, _Plan]:
        self._census()
        plans = {file: _Plan() for file in self.modules}
        for file, module in self.modules.items():
            analysis = module.analysis
            for variable, answers in analysis.answers.items():
                spec = (file, variable)
                servers = list(self.servers.get(spec, {}).values())
                why = self.blocked.get(spec)
                if why is None and servers:
                    why = self._own_module(analysis, variable) or self._two_modules(servers)
                for name, arg in answers.items():
                    self._route(plans, module, spec, name, _source(arg.value), servers, why)
        return plans

    def _own_module(self, analysis: _Analysis, variable: str) -> str | None:
        if variable not in analysis.built_at_module_level:
            return "built inside a function"
        bound = analysis.module_scope.assignments[variable]
        if len(bound) != 1:
            return f"{variable} is bound more than once"
        # A view in its own module is such a use: it takes the answer there, as a run over one file does.
        if any(assignment.references for assignment in bound):
            return "used otherwise in its own module"
        return None

    def _two_modules(self, servers: Sequence[_Server]) -> str | None:
        modules = sorted({self.display(server.file) for server in servers})
        if len(modules) > 1:
            return f"served from {len(modules)} modules ({', '.join(modules)})"
        return None

    def _route(
        self,
        plans: dict[Path, _Plan],
        module: _Module,
        spec: _Spec,
        name: str,
        value: str,
        servers: Sequence[_Server],
        why: str | None,
    ) -> None:
        key = (spec[1], name)
        if why is not None:
            plans[spec[0]].left[key] = why
            return
        routes: list[tuple[_Server, Arrival]] = []
        for server in servers:
            resolved = self._value(module.analysis, value, server.reach)
            if isinstance(resolved, str):
                plans[spec[0]].left[key] = resolved
                return
            head, carried = resolved
            origin = self.display(spec[0])
            routes.append((server, Arrival(spec, name, value, origin, head, carried)))
        for server, arrival in routes:
            plans[server.file].arrivals.setdefault(server.key, []).append(arrival)

    def _value(
        self, analysis: _Analysis, value: str, reach: tuple[int, str] | None
    ) -> str | tuple[str | None, Carried | None]:
        """What ``value`` needs in the view, as (the name, its import), or why it cannot go there."""
        try:
            tree = ast.parse(value, mode="eval").body
        except SyntaxError:
            # ``_source`` folds a value to one line, so a comment inside it swallows the rest.
            return _NOT_A_NAME
        if not any(isinstance(node, ast.Name) for node in ast.walk(tree)):
            return None, None
        while isinstance(tree, ast.Attribute):
            tree = tree.value
        if not isinstance(tree, ast.Name):
            return _NOT_A_NAME
        head = tree.id
        bound = analysis.module_scope.assignments[head]
        if not bound:
            return f"{head} is not bound in its module"
        if any(isinstance(assignment, ImportAssignment) for assignment in bound):
            return self._imported_value(analysis, head, len(bound))
        if reach is None:
            return f"{head} is reached through a re-export, and that holds only the spec"
        return head, Carried(reach[1], head, None, reach[0])

    def _imported_value(
        self, analysis: _Analysis, head: str, bindings: int
    ) -> str | tuple[str | None, Carried | None]:
        """The spec module's own import of ``head``, carried only if it reads the same in a view."""
        if bindings != 1:
            return f"{head} is imported more than once"
        carried = next(
            site.carried for site in analysis.imported if site.local == head and site.top_level
        )
        if carried.relative:
            return f"{head} is imported relatively"
        # Carried as written it would be rewritten only by the next run.
        if carried.module.split(".")[0] == DRFS:
            return f"{head} is drfs'"
        return head, carried


def rewrite_files(sources: Mapping[Path, str], roots: Sequence[Path]) -> dict[Path, Rewritten]:
    """Each file of the run rewritten, its answers followed. ``Unreadable`` if one does not parse."""
    index = _Index(sources, roots)
    plans = index.plan()
    placed: dict[tuple[_Spec, str], list[str]] = {}
    for path, source in sources.items():
        plan = plans[path.resolve()]
        if plan.arrivals:
            followed = Followed(arrivals=plan.arrivals)
            for key, spelled in rewrite_module(source, path, roots, followed)[2].items():
                placed.setdefault(key, []).extend(spelled)
    for file, plan in plans.items():
        where = index.display(file)
        for arrivals in plan.arrivals.values():
            for arrival in arrivals:
                spec_plan = plans[arrival.spec[0]]
                key = (arrival.spec[1], arrival.name)
                spelled = placed.get((arrival.spec, arrival.name))
                if spelled:
                    spec_plan.moved[key] = f"{', '.join(spelled)} in {where}"
                else:
                    spec_plan.left[key] = f"the view in {where} refused it: see the comment there"
    results: dict[Path, Rewritten] = {}
    for path, source in sources.items():
        plan = plans[path.resolve()]
        followed = Followed(plan.arrivals, plan.moved, plan.left)
        output, findings, _ = rewrite_module(source, path, roots, followed)
        results[path] = Rewritten(output, findings, bool(plan.arrivals))
    return results
