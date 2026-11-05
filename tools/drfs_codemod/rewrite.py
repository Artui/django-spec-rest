"""Rewrite one module's drfs imports and spec declarations onto the kernel and this package.

Two visits over one parsed module. ``_Analysis`` reads it: what each local
name was imported as, which calls construct a drfs (or kernel) spec, which
keyword of each is mapped, moved or left, and which views in the module serve
a spec by name. ``_Rewrite`` then changes it. Every site left is marked with a
comment beginning ``MARKER`` above its statement, and returned as a
``Finding`` carrying the original line.

A second run over the output changes nothing: the kernel spellings it writes
are not drfs', so nothing is left to map, and a marker already above a
statement is not written again.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.helpers import get_full_name_for_node
from libcst.metadata import (
    CodeRange,
    ImportAssignment,
    MetadataWrapper,
    PositionProvider,
    Scope,
    ScopeProvider,
)

from drfs_codemod.import_map import DROPPED, IMPORTS
from drfs_codemod.signatures import Reads, find_function, module_file, reads_for

MARKER = "drfs-codemod:"

DRFS = "rest_framework_services"
KERNEL = "django_service_specs"

VALIDATOR = ("django_spec_rest.service_specs.serializer_validator", "SerializerValidator")
PRESENTER = ("django_spec_rest.service_specs.serializer_presenter", "SerializerPresenter")
PERMISSION = ("django_spec_rest.service_specs.drf_permission_check", "DRFPermissionCheck")

# Fields a kernel spec keeps under drfs' name and meaning: passed as written.
_KEPT = frozenset(
    {
        "service",
        "selector",
        "kind",
        "atomic",
        "idempotent",
        "partial",
        "many",
        "many_argument",
        "input_data",
        "instance_selector_spec",
        "collection_selector_spec",
        "output_selector_spec",
        "allow_none",
        "kwargs",
        "progress_reporter",
        "preconditions",
        "affordances",
        "metadata",
        "select_related",
        "prefetch_related",
        "annotations",
        "extend_queryset",
        "filter_set",
        # The kernel's own spellings, so a second run reads its own output.
        "validator",
        "presenter",
        "permissions",
        "reads",
        "shapes",
        "returns_many",
        "many_min_length",
        "many_max_length",
    }
)

_NESTED_ROLES = {
    "instance_selector_spec": "instance",
    "collection_selector_spec": "collection",
    "output_selector_spec": "output",
}

_ANSWERS = ("success_status", "response_finalizer")

_STATEMENTS = (cst.SimpleStatementLine, cst.BaseCompoundStatement)

_DIRECT_STATUS = re.compile(r"^(\d+|.*\bHTTP_\d+\w*)$")


@dataclass(frozen=True)
class Finding:
    """A site the codemod left: the file, the line in the file as it was read, and why."""

    path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


@dataclass
class _SpecCall:
    """One construction of a spec: its kind, its role if nested, and what becomes of each keyword."""

    kind: str
    role: str | None
    variable: str | None = None
    consumed: set[int] = field(default_factory=set)
    hoisted_from: cst.Call | None = None


@dataclass
class _UseSite:
    """A view or action in this module serving a spec by its variable name."""

    form: str
    class_node: cst.ClassDef
    anchor: cst.CSTNode
    statement: cst.BaseStatement
    action: str | None = None
    # The other keys of an ``action_specs`` dict, so an ``update`` entry's
    # answer is not written for a ``partial_update`` that has an entry of its own.
    entries: frozenset[str] = frozenset()


def _source(node: cst.CSTNode) -> str:
    return " ".join(cst.Module(body=[]).code_for_node(node).split())


def _keyword(arg: cst.Arg) -> str | None:
    return arg.keyword.value if arg.keyword is not None else None


def _kwargs(call: cst.Call) -> dict[str, cst.Arg]:
    return {name: arg for arg in call.args if (name := _keyword(arg)) is not None}


def _is_true(node: cst.BaseExpression) -> bool:
    return isinstance(node, cst.Name) and node.value == "True"


def _is_false_or_none(node: cst.BaseExpression) -> bool:
    return isinstance(node, cst.Name) and node.value in ("False", "None")


class _Imports(cst.CSTVisitor):
    """What each local name was imported as, read before the analysis needs it.

    Its own pass, since a module's ``visit`` comes before any import in it:
    the names drfs has nowhere to send are looked up from the module's scope
    when it is entered, and a function may name an import made below it.
    """

    def __init__(self, analysis: _Analysis) -> None:
        self.a = analysis

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or node.relative or isinstance(node.names, cst.ImportStar):
            return
        module = get_full_name_for_node(node.module) or ""
        for alias in node.names:
            name = get_full_name_for_node(alias.name) or ""
            local = alias.evaluated_alias or name
            self.a.origins[local] = (module, name)
            if module.startswith(DRFS) and (module, name) in DROPPED:
                self.a.dropped_imports[local] = alias

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name = get_full_name_for_node(alias.name) or ""
            # ``import a.b`` binds ``a``, which names the package ``a``.
            local = alias.evaluated_alias or name.split(".")[0]
            self.a.module_aliases[local] = name if alias.asname is not None else local


class _Analysis(cst.CSTVisitor):
    def __init__(self, path: Path, roots: Sequence[Path]) -> None:
        self.path = path
        self.roots = list(roots)
        self.origins: dict[str, tuple[str, str]] = {}
        self.module_aliases: dict[str, str] = {}
        self.specs: dict[int, _SpecCall] = {}
        self.answers: dict[str, dict[str, cst.Arg]] = {}
        self.use_sites: dict[str, list[_UseSite]] = {}
        self.consumed: set[int] = set()
        self.dropped_imports: dict[str, cst.ImportAlias] = {}
        self.live_dropped: set[str] = set()
        self.dropped_references: list[cst.Name] = []
        self._class: list[cst.ClassDef] = []
        self._module_level_targets: dict[int, str] = {}
        self.positions: Mapping[cst.CSTNode, CodeRange] = {}
        self.scopes: Mapping[cst.CSTNode, Scope | None] = {}

    # --- spec construction ---------------------------------------------------

    def spec_kind(self, func: cst.BaseExpression) -> str | None:
        """``ServiceSpec`` or ``SelectorSpec`` if ``func`` names drfs' or the kernel's, else ``None``."""
        origin: tuple[str, str] | None = None
        if isinstance(func, cst.Name):
            origin = self.origins.get(func.value)
        elif isinstance(func, cst.Attribute) and isinstance(func.value, cst.Name):
            module = self.module_aliases.get(func.value.value)
            # Through a drfs module import the class stays drfs' until that
            # import is rewritten by hand (it is marked), so its keywords stay
            # drfs' too: a run after that rewrites them.
            if module is not None and not module.startswith(DRFS):
                origin = (module, func.attr.value)
        if origin is None:
            return None
        target = IMPORTS.get(origin, origin)
        if target[0].startswith(KERNEL) and target[1] in ("ServiceSpec", "SelectorSpec"):
            return target[1]
        return None

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._class.append(node)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._class.pop()

    def visit_SimpleStatementLine(self, node: cst.SimpleStatementLine) -> None:
        for small in node.body:
            if not isinstance(small, cst.Assign) or len(small.targets) != 1:
                continue
            target = small.targets[0].target
            if not isinstance(target, cst.Name):
                continue
            if not self._class and isinstance(small.value, cst.Call):
                self._module_level_targets[id(small.value)] = target.value
            if self._class and len(self._class) == 1:
                self._class_assignment(node, target.value, small.value)

    def _class_assignment(
        self, line: cst.SimpleStatementLine, name: str, value: cst.BaseExpression
    ) -> None:
        owner = self._class[-1]
        if name == "spec" and isinstance(value, cst.Name):
            self.use_sites.setdefault(value.value, []).append(_UseSite("view", owner, line, line))
        if name == "action_specs" and isinstance(value, cst.Dict):
            entries = frozenset(
                element.key.evaluated_value
                for element in value.elements
                if isinstance(element, cst.DictElement)
                and isinstance(element.key, cst.SimpleString)
                and isinstance(element.key.evaluated_value, str)
            )
            for element in value.elements:
                if (
                    isinstance(element, cst.DictElement)
                    and isinstance(element.key, cst.SimpleString)
                    and isinstance(element.value, cst.Name)
                ):
                    action = element.key.evaluated_value
                    assert isinstance(action, str)
                    self.use_sites.setdefault(element.value.value, []).append(
                        _UseSite("hook", owner, line, line, action=action, entries=entries)
                    )

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        if len(self._class) != 1:
            return
        for decorator in node.decorators:
            call = decorator.decorator
            if (
                isinstance(call, cst.Call)
                and call.args
                and _keyword(call.args[0]) is None
                and isinstance(call.args[0].value, cst.Name)
                and (get_full_name_for_node(call.func) or "").split(".")[-1] == "service_action"
            ):
                self.use_sites.setdefault(call.args[0].value.value, []).append(
                    _UseSite("decorator", self._class[-1], decorator, node, action=node.name.value)
                )

    def visit_Call(self, node: cst.Call) -> None:
        kind = self.spec_kind(node.func)
        if kind is None:
            return
        spec = self.specs.setdefault(id(node), _SpecCall(kind=kind, role=None))
        spec.variable = self._module_level_targets.get(id(node))
        keywords = _kwargs(node)
        for name, role in _NESTED_ROLES.items():
            nested = keywords.get(name)
            if nested is not None and isinstance(nested.value, cst.Call):
                nested_kind = self.spec_kind(nested.value.func)
                if nested_kind == "SelectorSpec":
                    self.specs[id(nested.value)] = _SpecCall(kind=nested_kind, role=role)
        for name, arg in keywords.items():
            if self._consumes(spec, name, arg):
                spec.consumed.add(id(arg))
                self.consumed.add(id(arg))
        if spec.kind == "ServiceSpec" and spec.variable is not None:
            answers = {name: keywords[name] for name in _ANSWERS if name in keywords}
            if answers:
                self.answers[spec.variable] = answers

    def _consumes(self, spec: _SpecCall, name: str, arg: cst.Arg) -> bool:
        """Whether this keyword's source leaves the call for a comment, so a dropped name in it is not live."""
        if name in ("reads", "json_schema_registry", "field_audiences", *_ANSWERS):
            return True
        return name in ("output_filter_from_call", "document_service_error") and not (
            _is_true(arg.value) or _is_false_or_none(arg.value)
        )

    # --- references to names with nowhere to go ------------------------------

    def visit_Module(self, node: cst.Module) -> None:
        scope = self.scopes[node]
        assert scope is not None
        self._dropped_accesses: dict[int, str] = {}
        for local in self.dropped_imports:
            for assignment in scope.assignments[local]:
                if isinstance(assignment, ImportAssignment):
                    for access in assignment.references:
                        self._dropped_accesses[id(access.node)] = local

    def visit_Arg(self, node: cst.Arg) -> bool:
        return id(node) not in self.consumed

    def visit_Name(self, node: cst.Name) -> None:
        local = self._dropped_accesses.get(id(node))
        if local is not None:
            self.live_dropped.add(local)
            self.dropped_references.append(node)


class _Rewrite(cst.CSTTransformer):
    def __init__(self, analysis: _Analysis, context: CodemodContext, module: cst.Module) -> None:
        self.a = analysis
        self.context = context
        self._module = module
        self.findings: list[Finding] = []
        self._statements: list[cst.CSTNode] = []
        self._markers: dict[int, list[str]] = {}
        self._insert_after: dict[int, list[cst.BaseStatement]] = {}
        self._decorator_keywords: dict[int, list[cst.Arg]] = {}
        self._renames: dict[int, str] = {}
        self._plan_answers()
        self._plan_renames()
        self._dropped_names = {id(node) for node in analysis.dropped_references}

    # --- marking ---------------------------------------------------------------

    def _line(self, node: cst.CSTNode) -> int:
        return self.a.positions[node].start.line

    def mark(self, node: cst.CSTNode, reason: str, *, at: cst.CSTNode | None = None) -> None:
        """Report ``node``'s line, and put the marker above the statement around it (or ``at``)."""
        self.findings.append(Finding(str(self.a.path), self._line(node), reason))
        if at is None and not self._statements:
            return
        anchor = at if at is not None else self._statements[-1]
        text = f"# {MARKER} {reason}"
        markers = self._markers.setdefault(id(anchor), [])
        if text not in markers:
            markers.append(text)

    def _standing(self, original: cst.CSTNode) -> None:
        """Report a marker an earlier run left above this statement, unless this run writes it again."""
        fresh = set(self._markers.get(id(original), []))
        for line in getattr(original, "leading_lines", ()):
            text = line.comment.value if line.comment is not None else ""
            if text.startswith(f"# {MARKER} ") and text not in fresh:
                reason = text[len(f"# {MARKER} ") :]
                self.findings.append(Finding(str(self.a.path), self._line(original), reason))

    def _with_markers(self, original: cst.CSTNode, updated: cst.CSTNode) -> cst.CSTNode:
        markers = self._markers.pop(id(original), None)
        if not markers or not hasattr(updated, "leading_lines"):
            return updated
        existing = {
            line.comment.value for line in updated.leading_lines if line.comment is not None
        }
        added = [
            cst.EmptyLine(comment=cst.Comment(text)) for text in markers if text not in existing
        ]
        return updated.with_changes(leading_lines=[*updated.leading_lines, *added])

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, _STATEMENTS):
            self._statements.append(node)
        return super().on_visit(node)

    def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> object:
        result = super().on_leave(original_node, updated_node)
        if not isinstance(original_node, _STATEMENTS):
            return result
        self._statements.pop()
        self._standing(original_node)
        if isinstance(result, cst.CSTNode):
            result = self._with_markers(original_node, result)
        after = self._insert_after.pop(id(original_node), None)
        if after and isinstance(result, cst.BaseStatement):
            return cst.FlattenSentinel([result, *after])
        return result

    # --- imports ---------------------------------------------------------------

    def _plan_renames(self) -> None:
        """A renamed target imported under its old spelling renames that spelling's references too."""
        scope = self.a.scopes[self._module]
        assert scope is not None
        for local, origin in self.a.origins.items():
            target = IMPORTS.get(origin)
            if target is None or target[1] == origin[1] or local != origin[1]:
                continue
            for assignment in scope.assignments[local]:
                if isinstance(assignment, ImportAssignment):
                    for access in assignment.references:
                        self._renames[id(access.node)] = target[1]

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if id(original_node) in self._dropped_names:
            local = original_node.value
            module, name = self.a.origins[local]
            self.mark(original_node, f"{name}: {DROPPED[(module, name)]}")
        rename = self._renames.get(id(original_node))
        return updated_node.with_changes(value=rename) if rename else updated_node

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel:
        if original_node.module is None or original_node.relative:
            return updated_node
        module = get_full_name_for_node(original_node.module) or ""
        if not (module == DRFS or module.startswith(DRFS + ".")):
            return updated_node
        if isinstance(updated_node.names, cst.ImportStar):
            self.mark(
                original_node, "a star import from drfs: import each name from its new module"
            )
            return updated_node
        kept: list[cst.ImportAlias] = []
        for alias in updated_node.names:
            name = get_full_name_for_node(alias.name) or ""
            local = alias.evaluated_alias or name
            target = IMPORTS.get((module, name))
            if target is not None:
                keep_alias = alias.asname is not None and local != target[1]
                AddImportsVisitor.add_needed_import(
                    self.context, target[0], target[1], local if keep_alias else None
                )
                continue
            if (module, name) in DROPPED:
                if local in self.a.live_dropped:
                    self.mark(original_node, f"{name}: {DROPPED[(module, name)]}")
                    kept.append(alias)
                continue
            self.mark(original_node, f"{name}: not a name drfs 0.62.0 exports from {module}")
            kept.append(alias)
        if not kept:
            return cst.RemoveFromParent()
        kept[-1] = kept[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
        return updated_node.with_changes(names=kept)

    def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
        for alias in original_node.names:
            name = get_full_name_for_node(alias.name) or ""
            if name == DRFS or name.startswith(DRFS + "."):
                self.mark(
                    original_node,
                    f"import {name}: import each name it is used for from its new module",
                )
        return updated_node

    def leave_SimpleString(
        self, original_node: cst.SimpleString, updated_node: cst.SimpleString
    ) -> cst.SimpleString:
        value = original_node.evaluated_value
        if not isinstance(value, str) or not (value == DRFS or value.startswith(DRFS + ".")):
            return updated_node
        if value == DRFS:
            self.mark(
                original_node, "drfs' app label: django-spec-rest has no app, so remove the entry"
            )
            return updated_node
        module, _, name = value.rpartition(".")
        target = IMPORTS.get((module, name))
        if target is None:
            self.mark(original_node, f"{value}: no dotted path to rewrite it to")
            return updated_node
        quote = updated_node.quote
        return updated_node.with_changes(
            value=f"{updated_node.prefix}{quote}{target[0]}.{target[1]}{quote}"
        )

    # --- success_status and response_finalizer --------------------------------

    def _plan_answers(self) -> None:
        """Move each spec's answer onto the views in this module that serve it, where one does."""
        self._answered: dict[tuple[str, str], list[str]] = {}
        for variable, answers in self.a.answers.items():
            for site in self.a.use_sites.get(variable, []):
                for name, arg in answers.items():
                    spelled = self._place(site, name, arg.value)
                    if spelled:
                        self._answered.setdefault((variable, name), []).append(spelled)

    def _class_names(self, node: cst.ClassDef) -> set[str]:
        names: set[str] = set()
        for statement in node.body.body:
            if isinstance(statement, cst.SimpleStatementLine):
                for small in statement.body:
                    if isinstance(small, cst.Assign):
                        names.update(
                            t.target.value for t in small.targets if isinstance(t.target, cst.Name)
                        )
            elif isinstance(statement, cst.FunctionDef):
                names.add(statement.name.value)
        return names

    def _place(self, site: _UseSite, name: str, value: cst.BaseExpression) -> str | None:
        declared = self._class_names(site.class_node)
        view = site.class_node.name.value
        if site.form == "decorator":
            hook = f"get_{site.action}_{name}"
            if hook in declared:
                self._conflict(
                    site,
                    f"{view}.{site.action} declares {hook}; a decorator value beside it is refused",
                )
                return None
            decorator = site.anchor
            assert isinstance(decorator, cst.Decorator) and isinstance(
                decorator.decorator, cst.Call
            )
            if name in _kwargs(decorator.decorator):
                self._conflict(site, f"{view}.{site.action}'s decorator already declares {name}")
                return None
            self._decorator_keywords.setdefault(id(decorator), []).append(_keyword_arg(name, value))
            return f"@service_action(..., {name}=...) on {view}.{site.action}"
        if site.form == "view":
            if name in declared:
                self._conflict(site, f"{view} already declares {name}")
                return None
            self._insert(site.anchor, cst.parse_statement(f"{name} = {_source(value)}"))
            return f"{view}.{name}"
        actions = [site.action or ""]
        # drfs serves a PATCH the update entry's spec only when the view has
        # no partial_update entry of its own.
        if site.action == "update" and "partial_update" not in site.entries:
            actions.append("partial_update")
        spelled: list[str] = []
        for action in actions:
            hook = f"get_{action}_{name}"
            if hook in declared:
                self._conflict(site, f"{view} already declares {hook}")
                continue
            text = _source(value)
            body = text if _DIRECT_STATUS.match(text) else f"staticmethod({text})"
            self._insert(site.anchor, cst.parse_statement(f"{hook} = {body}"))
            spelled.append(f"{view}.{hook}")
        return ", ".join(spelled) or None

    def _conflict(self, site: _UseSite, reason: str) -> None:
        """A use site the answer cannot move onto, marked above it so a second run reports it too."""
        self.mark(site.anchor, reason, at=site.statement)

    def _insert(self, anchor: cst.CSTNode, statement: cst.BaseStatement) -> None:
        self._insert_after.setdefault(id(anchor), []).append(statement)

    def leave_Decorator(
        self, original_node: cst.Decorator, updated_node: cst.Decorator
    ) -> cst.Decorator:
        added = self._decorator_keywords.pop(id(original_node), None)
        if not added or not isinstance(updated_node.decorator, cst.Call):
            return updated_node
        call = updated_node.decorator
        return updated_node.with_changes(
            decorator=call.with_changes(args=[*_closed(call.args), *added])
        )

    # --- spec construction -----------------------------------------------------

    def _seat(
        self,
        seat: tuple[str, str],
        serializer: cst.BaseExpression,
        **keywords: cst.BaseExpression | None,
    ) -> cst.Call:
        AddImportsVisitor.add_needed_import(self.context, *seat)
        args = [cst.Arg(value=serializer)]
        args += [_keyword_arg(k, v) for k, v in keywords.items() if v is not None]
        return cst.Call(func=cst.Name(seat[1]), args=args)

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        spec = self.a.specs.get(id(original_node))
        if spec is None:
            return updated_node
        return _SpecRewrite(self, spec, original_node, updated_node).run()

    def reads_note(self, original: cst.Call, selector: cst.Arg) -> None:
        """Mark a selector whose signature names a read drfs filled, with the ``reads=`` it needs."""
        reads = self._selector_reads(selector.value)
        named = _source(selector.value)
        if isinstance(reads, str):
            self.mark(original, reads)
        elif reads is not None and reads.spelling is None:
            self.mark(original, f"selector={named}: {reads.note}")
        elif reads is not None:
            suffix = f" ({reads.note})" if reads.note else ""
            self.mark(
                original,
                f"selector={named} takes by name what drfs filled from the route or query string; "
                f"where the caller sends it, declare {reads.spelling}{suffix}",
            )

    def _selector_reads(self, value: cst.BaseExpression) -> Reads | str | None:
        if isinstance(value, cst.Lambda):
            parsed = ast.parse(_source(value), mode="eval").body
            assert isinstance(parsed, ast.Lambda)
            return reads_for(parsed)
        dotted = (
            get_full_name_for_node(value) if isinstance(value, (cst.Name, cst.Attribute)) else None
        )
        if dotted is None:
            return "its selector is no name: declare in reads= what drfs read by its signature"
        *owner, name = dotted.split(".")
        module: str | None
        if not owner:
            origin = self.a.origins.get(name)
            module, name = origin if origin else (None, name)
        else:
            head = owner[0]
            base = (
                ".".join(self.a.origins[head])
                if head in self.a.origins
                else self.a.module_aliases.get(head)
            )
            if base is None:
                return f"its selector {dotted} is out of reach: declare in reads= what drfs read by its signature"
            module = ".".join([base, *owner[1:]])
        if module is None:
            source = self._module.code
        else:
            file = module_file(self.a.roots, module)
            if file is None:
                return f"its selector {dotted} is out of reach: declare in reads= what drfs read by its signature"
            source = file.read_text(encoding="utf-8")
        function = find_function(source, name)
        if function is None:
            return f"its selector {dotted} is out of reach: declare in reads= what drfs read by its signature"
        return reads_for(function)

    def answers_note(self, original: cst.Call, spec: _SpecCall, arg: cst.Arg) -> None:
        name = _keyword(arg)
        assert name is not None
        moved = self._answered.get((spec.variable or "", name), [])
        value = _source(arg.value)
        if moved:
            self.mark(
                original,
                f"{name}={value} moved to {', '.join(moved)}; a view in another module serving "
                f"{spec.variable} declares it itself",
            )
            return
        self.mark(
            original,
            f"{name}={value} is the view's or the action's: set {name} on the view, "
            f"@service_action(..., {name}=...), or get_<action>_{name} on the viewset",
        )


def _closed(args: Sequence[cst.Arg]) -> list[cst.Arg]:
    """``args`` with a comma after the last one, so another can follow it."""
    if not args:
        return []
    last = args[-1]
    if isinstance(last.comma, cst.Comma):
        return list(args)
    return [
        *args[:-1],
        last.with_changes(comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))),
    ]


def _closed_elements(elements: Sequence[cst.BaseDictElement]) -> list[cst.BaseDictElement]:
    """``elements`` with a comma after the last one, so another can follow it."""
    if not elements or isinstance(elements[-1].comma, cst.Comma):
        return list(elements)
    last = elements[-1].with_changes(comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" ")))
    return [*elements[:-1], last]


def _finished(args: list[cst.Arg], original: Sequence[cst.Arg]) -> list[cst.Arg]:
    """End ``args`` as the original call ended: its last comma, and the space before the parenthesis."""
    if args and original:
        last = original[-1]
        args[-1] = args[-1].with_changes(
            comma=last.comma, whitespace_after_arg=last.whitespace_after_arg
        )
    return args


def _keyword_arg(name: str, value: cst.BaseExpression) -> cst.Arg:
    tight = cst.AssignEqual(
        whitespace_before=cst.SimpleWhitespace(""), whitespace_after=cst.SimpleWhitespace("")
    )
    return cst.Arg(keyword=cst.Name(name), value=value, equal=tight)


class _SpecRewrite:
    """The keywords of one spec construction, mapped onto the kernel's seats."""

    def __init__(
        self, rewrite: _Rewrite, spec: _SpecCall, original: cst.Call, updated: cst.Call
    ) -> None:
        self.r = rewrite
        self.spec = spec
        self.original = original
        self.updated = updated
        self.original_args = {_keyword(arg): arg for arg in original.args}

    def leave(self, name: str, reason: str) -> None:
        arg = self.original_args[name]
        self.r.mark(self.original, f"{reason}: was {name}={_source(arg.value)}")

    def run(self) -> cst.BaseExpression:
        keywords = _kwargs(self.updated)
        if self.spec.role == "output":
            return self._nested_output(keywords)
        registry = keywords.get("json_schema_registry")
        shared_registry = registry is not None and isinstance(
            registry.value, (cst.Name, cst.Attribute)
        )
        audiences = keywords.get("field_audiences")
        hoisted = self._hoisted(keywords)
        output = keywords.get("output_serializer") or (hoisted[0] if hoisted else None)
        seated: dict[str, cst.BaseExpression | None] = {
            "json_schema_registry": registry.value
            if registry is not None and shared_registry
            else None
        }
        presenter_extra = {
            **seated,
            "field_audiences": audiences.value if audiences is not None else None,
        }
        document = keywords.get("document_service_error")
        documented = document is not None and _is_true(document.value)
        out: list[cst.Arg] = []
        for arg in self.updated.args:
            name = _keyword(arg)
            if name == "input_serializer":
                context = keywords.get("input_serializer_context")
                seat = self.r._seat(
                    VALIDATOR,
                    arg.value,
                    serializer_context=context.value if context else None,
                    **seated,
                )
                out.append(arg.with_changes(keyword=cst.Name("validator"), value=seat))
            elif name == "output_serializer":
                context = keywords.get("output_serializer_context")
                out.append(
                    arg.with_changes(
                        keyword=cst.Name("presenter"),
                        value=self._presenter(arg, context, presenter_extra),
                    )
                )
            elif name == "output_selector_spec" and hoisted is not None:
                serializer, context, nested = hoisted
                if nested is not None:
                    comma = (
                        arg.comma
                        if isinstance(arg.comma, cst.Comma)
                        else cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                    )
                    out.append(
                        arg.with_changes(
                            value=nested, comma=comma, whitespace_after_arg=cst.SimpleWhitespace("")
                        )
                    )
                presenter = self._presenter(serializer, context, presenter_extra)
                out.append(arg.with_changes(keyword=cst.Name("presenter"), value=presenter))
            elif name in ("input_serializer_context", "output_serializer_context"):
                seat = "input_serializer" if name.startswith("input") else "output_serializer"
                if seat not in keywords and not (seat == "output_serializer" and hoisted):
                    self.leave(name, f"{name} with no {seat} has no seat to carry it")
            elif name == "permission_classes":
                out.extend(self._permissions(arg))
            elif name == "json_schema_registry":
                if not shared_registry or ("input_serializer" not in keywords and output is None):
                    self.leave(
                        name,
                        "json_schema_registry goes on the SerializerValidator and SerializerPresenter",
                    )
            elif name == "field_audiences":
                if output is None:
                    self.leave(
                        name,
                        "field_audiences goes on a SerializerPresenter, and this spec has none",
                    )
            elif name == "document_service_error":
                out.extend(self._document_service_error(arg, keywords))
            elif name == "metadata" and documented and isinstance(arg.value, cst.Dict):
                entry = cst.DictElement(
                    key=cst.SimpleString('"document_service_error"'), value=cst.Name("True")
                )
                out.append(
                    arg.with_changes(
                        value=arg.value.with_changes(
                            elements=[*_closed_elements(arg.value.elements), entry]
                        )
                    )
                )
            elif name == "output_filter_from_call":
                if not _is_true(arg.value):
                    self.leave(
                        name, "the kernel always filters the re-read by the call's arguments"
                    )
            elif name == "reads" and self._drfs_reads(arg):
                self.leave(
                    name,
                    "declare each read as a kernel Parameter: reads=Parameters.of(Parameter(...))",
                )
            elif name in _ANSWERS:
                self.r.answers_note(self.original, self.spec, self.original_args[name])
            else:
                out.append(arg)
        self._reads_note(out)
        return self.updated.with_changes(args=_finished(out, self.updated.args))

    def _reads_note(self, out: list[cst.Arg]) -> None:
        """Mark a selector left with no kernel ``reads=``, whichever run it is, so a second adds nothing."""
        if (
            self.spec.kind == "SelectorSpec"
            and "selector" in self.original_args
            and not any(_keyword(arg) == "reads" for arg in out)
        ):
            self.r.reads_note(self.original, self.original_args["selector"])

    def _drfs_reads(self, arg: cst.Arg) -> bool:
        """Whether ``reads=`` is drfs' list rather than the kernel's ``Parameters``, which a second run meets."""
        return not (
            isinstance(arg.value, cst.Call)
            and (get_full_name_for_node(arg.value.func) or "").endswith("Parameters.of")
        ) and not isinstance(arg.value, cst.Name)

    def _nested_output(self, keywords: dict[str, cst.Arg]) -> cst.Call:
        """An output selector: its serializer is lifted by the service around it, so only its own seats move."""
        out: list[cst.Arg] = []
        for arg in self.updated.args:
            name = _keyword(arg)
            if name == "permission_classes":
                out.extend(self._permissions(arg))
            elif name in ("field_audiences", "json_schema_registry"):
                self.leave(
                    name, f"{name} on an output selector goes on the service's SerializerPresenter"
                )
            elif name == "reads" and self._drfs_reads(arg):
                self.leave(
                    name,
                    "declare each read as a kernel Parameter: reads=Parameters.of(Parameter(...))",
                )
            else:
                out.append(arg)
        self._reads_note(out)
        return self.updated.with_changes(args=_finished(out, self.updated.args))

    def _presenter(
        self,
        serializer: cst.Arg | cst.BaseExpression,
        context: cst.Arg | cst.BaseExpression | None,
        extra: dict[str, cst.BaseExpression | None],
    ) -> cst.Call:
        value = serializer.value if isinstance(serializer, cst.Arg) else serializer
        context_value = context.value if isinstance(context, cst.Arg) else context
        keywords: dict[str, cst.BaseExpression | None] = {
            "serializer_context": context_value,
            **extra,
        }
        if context_value is not None:
            keyword = self._value_keyword()
            if keyword != "result":
                keywords["value_keyword"] = (
                    cst.Name("None") if keyword is None else cst.SimpleString(f'"{keyword}"')
                )
        return self.r._seat(PRESENTER, value, **keywords)

    def _value_keyword(self) -> str | None:
        """What drfs handed an output context callable the value as: ``result``, ``instance`` or nothing."""
        keywords = _kwargs(self.original)
        if self.spec.kind == "ServiceSpec":
            many = keywords.get("many")
            return None if many is not None and _is_true(many.value) else "result"
        kind = keywords.get("kind")
        spelled = _source(kind.value) if kind is not None else ""
        return "instance" if spelled.endswith("RETRIEVE") else None

    def _hoisted(
        self, keywords: dict[str, cst.Arg]
    ) -> tuple[cst.Arg, cst.Arg | None, cst.Call | None] | None:
        """An output selector's serializer, lifted onto this service, and what is left of the selector."""
        if self.spec.kind != "ServiceSpec":
            return None
        arg = keywords.get("output_selector_spec")
        if arg is None:
            return None
        if not isinstance(arg.value, cst.Call):
            self.r.mark(
                self.original,
                "its output_selector_spec is declared elsewhere: move that selector's output "
                "serializer onto this spec as presenter=SerializerPresenter(...)",
            )
            return None
        nested = arg.value
        nested_keywords = _kwargs(nested)
        serializer = nested_keywords.get("output_serializer")
        if serializer is None:
            return None
        context = nested_keywords.get("output_serializer_context")
        lifted = {"output_serializer", "output_serializer_context"}
        rest = [a for a in nested.args if _keyword(a) not in lifted]
        if all(_keyword(a) == "kind" for a in rest):
            return serializer, context, None
        return serializer, context, nested.with_changes(args=_finished(rest, nested.args))

    def _permissions(self, arg: cst.Arg) -> list[cst.Arg]:
        if self.spec.role is not None:
            self.leave(
                "permission_classes",
                "the kernel refuses permissions on a nested selector: declare them on the spec served",
            )
            return []
        if isinstance(arg.value, (cst.List, cst.Tuple)) and not arg.value.elements:
            self.leave(
                "permission_classes",
                "an empty permission_classes: say permissions=(Unrestricted(),) if the spec admits everyone",
            )
            return []
        seat = self.r._seat(PERMISSION, arg.value)
        element = cst.Element(value=seat, comma=cst.Comma())
        return [
            arg.with_changes(keyword=cst.Name("permissions"), value=cst.Tuple(elements=[element]))
        ]

    def _document_service_error(self, arg: cst.Arg, keywords: dict[str, cst.Arg]) -> list[cst.Arg]:
        if _is_false_or_none(arg.value):
            return []
        if not _is_true(arg.value):
            self.leave(
                "document_service_error",
                'say {"document_service_error": True} in metadata where it is true',
            )
            return []
        metadata = keywords.get("metadata")
        if metadata is None:
            entry = cst.parse_expression('{"document_service_error": True}')
            return [arg.with_changes(keyword=cst.Name("metadata"), value=entry)]
        if isinstance(metadata.value, cst.Dict):
            # The entry is added where the metadata keyword is rewritten.
            return []
        self.leave("document_service_error", 'add "document_service_error": True to its metadata')
        return []


def rewrite_source(
    source: str, path: Path, roots: Sequence[Path] = ()
) -> tuple[str, list[Finding]]:
    """``source`` rewritten, and the sites left in it. ``roots`` is where a selector's module is looked up."""
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    analysis = _Analysis(path, roots or [Path.cwd()])
    analysis.positions = wrapper.resolve(PositionProvider)
    analysis.scopes = wrapper.resolve(ScopeProvider)
    wrapper.module.visit(_Imports(analysis))
    wrapper.visit(analysis)
    context = CodemodContext()
    rewrite = _Rewrite(analysis, context, wrapper.module)
    changed = wrapper.visit(rewrite)
    changed = AddImportsVisitor(context).transform_module(changed)
    findings = sorted(rewrite.findings, key=lambda f: (f.line, f.reason))
    return changed.code, findings
