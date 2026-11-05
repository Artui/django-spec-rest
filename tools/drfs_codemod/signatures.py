"""What a selector drfs filled by its signature needs declared as reads on a kernel spec.

drfs handed a selector the route captures and query values its signature
named. The kernel hands a spec only its declared parameters, so each such
name becomes a ``Parameter`` in ``reads``. Which names those are cannot be
told at the spec, only from the selector's ``def``, which is usually in
another module: this file finds that ``def`` by parsing, never importing,
and spells the ``reads=`` it would take. The codemod never applies it: a key
a provider or a server binding filled would become the caller's to choose.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import django_service_specs

# What the kernel itself fills by name, so a parameter so named is no read.
SEED_NAMES = frozenset(django_service_specs.RESERVED_POOL_SEEDS | django_service_specs.CALL_SEEDS)

_TYPES = {"int": "integer", "bool": "boolean", "str": "string", "float": "number"}
_SEQUENCES = {"list", "List", "Sequence", "tuple", "Tuple", "set", "frozenset"}


@dataclass(frozen=True)
class Reads:
    """The ``reads=`` a selector's signature asks for, or why it cannot be spelled."""

    spelling: str | None
    note: str | None = None


def _unwrap_optional(node: ast.expr) -> tuple[ast.expr, bool]:
    """``X | None`` or ``Optional[X]`` as ``(X, True)``; anything else as itself."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        sides = [node.left, node.right]
        rest = [
            side for side in sides if not (isinstance(side, ast.Constant) and side.value is None)
        ]
        if len(rest) == 1:
            return rest[0], True
    if isinstance(node, ast.Subscript) and _name(node.value) == "Optional":
        return node.slice, True
    return node, False


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kernel_type(annotation: ast.expr | None) -> tuple[str, str | None, bool, bool]:
    """``(type, items, optional, guessed)`` for an annotation, as a kernel ``Parameter`` spells them."""
    if annotation is None:
        return "string", None, False, True
    inner, optional = _unwrap_optional(annotation)
    if isinstance(inner, ast.Subscript) and _name(inner.value) == "Annotated":
        first = inner.slice.elts[0] if isinstance(inner.slice, ast.Tuple) else inner.slice
        inner, again = _unwrap_optional(first)
        optional = optional or again
    if isinstance(inner, ast.Subscript) and _name(inner.value) in _SEQUENCES:
        element = inner.slice.elts[0] if isinstance(inner.slice, ast.Tuple) else inner.slice
        items = _TYPES.get(_name(element) or "")
        return "array", items or "string", optional, items is None
    simple = _TYPES.get(_name(inner) or "")
    return simple or "string", None, optional, simple is None


def _parameter(arg: ast.arg, default: ast.expr | None) -> tuple[str, bool]:
    kind, items, optional, guessed = _kernel_type(arg.annotation)
    parts = [f'"{arg.arg}"', f'"{kind}"']
    if items is not None:
        parts.append(f'items="{items}"')
    if default is None and not optional:
        parts.append("required=True")
    elif default is not None and not (isinstance(default, ast.Constant) and default.value is None):
        parts.append(f"default={ast.unparse(default)}")
    return f"Parameter({', '.join(parts)})", guessed


def reads_for(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> Reads | None:
    """The ``reads=`` for a selector ``def``, or ``None`` when it names nothing beyond the seeds."""
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    pairs = [
        *zip(positional, [*defaults, *arguments.defaults], strict=True),
        *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
    ]
    named = [
        (arg, default) for arg, default in pairs if arg.arg not in SEED_NAMES | {"self", "cls"}
    ]
    if arguments.kwarg is not None:
        return Reads(
            None, f"its selector takes **{arguments.kwarg.arg}: declare in reads= each key it reads"
        )
    if not named:
        return None
    spelled = [_parameter(arg, default) for arg, default in named]
    spelling = "reads=Parameters.of(" + ", ".join(text for text, _ in spelled) + ")"
    guessed = [
        arg.arg for (arg, _), (_, was_guessed) in zip(named, spelled, strict=True) if was_guessed
    ]
    note = f"type guessed for {', '.join(guessed)}" if guessed else None
    return Reads(spelling, note)


def find_function(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The top-level ``def name`` in ``source``, or ``None``."""
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def module_file(roots: list[Path], module: str) -> Path | None:
    """The file defining a dotted ``module`` under one of ``roots``, or ``None``."""
    relative = Path(*module.split("."))
    for root in roots:
        for candidate in (root / relative.with_suffix(".py"), root / relative / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None
