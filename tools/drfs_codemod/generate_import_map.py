"""Write ``import_map.py``: every name drfs 0.62.0 lets a project import, and where it goes.

Run against three source trees, never imported, only parsed::

    python tools/drfs_codemod/generate_import_map.py \\
        --drfs <site-packages>/rest_framework_services \\
        --kernel <site-packages>/django_service_specs \\
        --rest django_spec_rest

Each importable binding of each drfs module is followed to the module that
defines it. A name drfs imported from the kernel goes to the kernel's root when
the root exports that same object, else to the kernel module that defines it. A
name drfs defined goes where this package defines it, at the same path or the
one definition of that name here, unless a table below says otherwise. Every
other name is dropped, with the reason the codemod reports.

The decision is by the defining module, never by spelling: several names are
spelled alike in drfs and the kernel and are different objects, so a spelling
alone cannot say which one an import meant.
"""

from __future__ import annotations

import argparse
import ast
import pprint
from dataclasses import dataclass
from pathlib import Path

DRFS = "rest_framework_services"
KERNEL = "django_service_specs"
REST = "django_spec_rest"

# drfs' own definitions whose replacement is the kernel's object of the same
# name, from the kernel's root: the root-to-root namesakes. Each is a different
# object in drfs, so the generic rule would call it dropped.
KERNEL_NAMESAKES = frozenset(
    {
        "ServiceSpec",
        "SelectorSpec",
        "can_present_nothing",
        "server_owned_keys",
        "unguarded_specs",
        "resolve_callable_kwargs",
        "audience_projection_for_spec",
        "enforce_affordances",
        "aenforce_affordances",
        "unmet_operation_affordance",
        "aunmet_operation_affordance",
    }
)

# drfs' refusal twins, defined under ``service_specs/``: each is renamed here so
# that no spelling is shared with the kernel's class of the same name.
RENAMED_TWINS = {
    "InvalidArguments": "DRFInvalidArguments",
    "NotPermitted": "DRFNotPermitted",
    "PrincipalUnavailable": "DRFPrincipalUnavailable",
}

_DECLARING = "drfs' declaration type, gone with it; see 'Declaring a spec' on the moving page"

# Why a drfs name has no import to rewrite to, for the names a project is most
# likely to hold. Every other dropped name gets the default.
DROP_REASONS = {
    "PolymorphicServiceSpec": "declare one kernel spec per route or action",
    "UrlKwarg": "declare the capture as a kernel Parameter in reads=",
    "QueryParam": "declare the read as a kernel Parameter in reads= (or shapes= where no callable names it)",
    "ArgumentBinding": _DECLARING,
    "OfflineContract": "no counterpart: a kernel spec dispatches off HTTP through the kernel's dispatch",
    "TargetGuard": "use the kernel's preconditions and object permission, which see the row",
    "InputRequired": "an input marker: declare the read as a kernel Parameter in reads=",
    "NotClientInput": "an input marker: fill the key from a typed kwargs provider",
    "InputDescription": "an input marker: describe the read on its kernel Parameter",
    "dispatch_spec": "use the kernel's dispatch, whose signature differs",
    "adispatch_spec": "use the kernel's adispatch, whose signature differs",
    "render_spec_output": "use the kernel's present",
    "arender_spec_output": "use the kernel's apresent",
    "render_for_audience": "use the kernel's present_for_audience",
    "arender_for_audience": "use the kernel's apresent_for_audience",
    "enforce_permissions": "use the kernel's authorize",
    "aenforce_permissions": "use the kernel's aauthorize",
    "call_service": "use the kernel's run_service",
    "acall_service": "use the kernel's arun_service",
    "call_selector": "use the kernel's run_selector",
    "acall_selector": "use the kernel's arun_selector",
    "apply_queryset_shaping": "use the kernel's shape_queryset",
    "spec_to_json_schema": "use the kernel's spec_input_schema",
    "output_to_json_schema": "use the kernel's spec_output_schema",
    "serializer_to_json_schema": "use the kernel's spec_input_schema over a SerializerValidator",
    "filterset_to_json_schema": "use the kernel's filter_set_parameters",
    "capability_manifest": "no counterpart: it read a drfs spec",
    "build_audience_projection": "no counterpart: it read a drfs spec",
    "build_input_serializer": "no counterpart: it read a drfs spec",
    "validate_input": "no counterpart: it read a drfs spec",
}

DEFAULT_DROP_REASON = "drfs' own name, with no counterpart in django-spec-rest or the kernel"
PRIVATE_REASON = "a private helper, kept by no public name in django-spec-rest or the kernel"


def _private(module: str) -> bool:
    """A ``utils`` module or an underscored one: what this package and the kernel keep internal."""
    return any(part == "utils" or part.startswith("_") for part in module.split("."))


@dataclass(frozen=True)
class Definition:
    """Where a binding comes from: its module, the name there, and whether it was defined there."""

    module: str
    name: str
    external: bool = False


def _module_name(root: Path, package: str, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([package, *parts])


def _top_level(body: list[ast.stmt]) -> list[ast.stmt]:
    """The module's statements, with the branches of a top-level ``if`` or ``try`` read as its own."""
    out: list[ast.stmt] = []
    for node in body:
        out.append(node)
        if isinstance(node, ast.If):
            out.extend(_top_level(node.body) + _top_level(node.orelse))
        elif isinstance(node, ast.Try):
            out.extend(_top_level(node.body))
    return out


def _absolute(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = module.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join([*base, *([node.module] if node.module else [])])


def bindings(root: Path, package: str) -> dict[str, dict[str, Definition]]:
    """Each module of the tree at ``root``, mapped to the names it binds at its top level."""
    modules: dict[str, dict[str, Definition]] = {}
    for path in sorted(root.rglob("*.py")):
        if "migrations" in path.parts or "templates" in path.parts:
            continue
        module = _module_name(root, package, path)
        names: dict[str, Definition] = {}
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _top_level(tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] = Definition(module, node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = Definition(module, target.id)
            elif isinstance(node, ast.ImportFrom):
                source = _absolute(module, path.name == "__init__.py", node)
                for alias in node.names:
                    if alias.name != "*":
                        names[alias.asname or alias.name] = Definition(
                            source, alias.name, external=True
                        )
        modules[module] = names
    return modules


def resolve(trees: dict[str, dict[str, Definition]], module: str, name: str) -> Definition | None:
    """Follow ``name`` in ``module`` through re-exports to the module that defines it.

    ``None`` for a name that is a submodule, or one that leaves the trees
    (a ``typing`` or Django name a module happened to import).
    """
    seen: set[tuple[str, str]] = set()
    while (module, name) not in seen:
        seen.add((module, name))
        binding = trees.get(module, {}).get(name)
        if binding is None:
            return None
        if not binding.external:
            return binding
        if binding.module not in trees:
            return None
        module, name = binding.module, binding.name
    return None


def _rest_target(
    rest: dict[str, dict[str, Definition]], definition: Definition, name: str
) -> tuple[str, str] | None:
    """Where this package keeps a drfs definition: its root if the root exports it, else its module."""
    same_path = REST + definition.module[len(DRFS) :]
    found = resolve(rest, same_path, name)
    if found is None:
        candidates = {
            Definition(module, name)
            for module, names in rest.items()
            if name in names and not names[name].external
        }
        if len(candidates) != 1:
            return None
        found = candidates.pop()
    if resolve(rest, REST, name) == found:
        return REST, name
    return found.module, name


def build(
    drfs: Path, kernel: Path, rest: Path
) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[tuple[str, str], str]]:
    """The two tables: ``(drfs module, name) -> (module, name)``, and the dropped names' reasons."""
    trees = {**bindings(drfs, DRFS), **bindings(kernel, KERNEL)}
    rest_trees = bindings(rest, REST)
    mapped: dict[tuple[str, str], tuple[str, str]] = {}
    dropped: dict[tuple[str, str], str] = {}
    for module in sorted(m for m in trees if m.startswith(DRFS)):
        for name in sorted(trees[module]):
            if name.startswith("_") and name != "__version__":
                continue
            definition = resolve(trees, module, name)
            if definition is None:
                continue
            key = (module, name)
            if definition.module.startswith(KERNEL):
                if resolve(trees, KERNEL, definition.name) == definition:
                    mapped[key] = (KERNEL, definition.name)
                elif _private(definition.module):
                    dropped[key] = PRIVATE_REASON
                else:
                    mapped[key] = (definition.module, definition.name)
                continue
            if definition.name in KERNEL_NAMESAKES:
                mapped[key] = (KERNEL, definition.name)
                continue
            if (
                definition.module.startswith(f"{DRFS}.service_specs.")
                and definition.name in RENAMED_TWINS
            ):
                target = _rest_target(rest_trees, definition, RENAMED_TWINS[definition.name])
                assert target is not None, definition
                mapped[key] = target
                continue
            if definition.name in DROP_REASONS:
                dropped[key] = DROP_REASONS[definition.name]
                continue
            target = _rest_target(rest_trees, definition, definition.name)
            if target is None:
                dropped[key] = DEFAULT_DROP_REASON
            elif _private(target[0]):
                dropped[key] = PRIVATE_REASON
            else:
                mapped[key] = target
    return mapped, dropped


_HEADER = '''"""Generated by ``generate_import_map.py`` from drfs 0.62.0; do not edit by hand.

``IMPORTS`` maps a drfs module and a name it binds to the module and name a
project imports instead. ``DROPPED`` maps the names with nowhere to go to the
reason the codemod reports.
"""

from __future__ import annotations

'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drfs", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--rest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("import_map.py"))
    args = parser.parse_args()
    mapped, dropped = build(args.drfs, args.kernel, args.rest)
    body = (
        _HEADER
        + "IMPORTS: dict[tuple[str, str], tuple[str, str]] = "
        + pprint.pformat(mapped, width=100, sort_dicts=True)
        + "\n\nDROPPED: dict[tuple[str, str], str] = "
        + pprint.pformat(dropped, width=100, sort_dicts=True)
        + "\n"
    )
    args.out.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
