"""Every name a facade module re-exports, read off its text: `local` → (source module, its name)."""

# does-not-cover: a name bound by code (`globals()`, a loop, a star import) or a non-literal table.
# does-not-cover: an alias of an attribute (`x = models.Y`) — a bare name already bound only.

from __future__ import annotations

import ast

#: The facade's lazy-import guard: a top-level `if TYPE_CHECKING:` block's imports are exports.
GUARD = "TYPE_CHECKING"
#: The deprecation table a module's `__getattr__ = shim(...)` serves.
TABLE = "DEPRECATED"
_FIELDS = ("since", "until", "instead", "kind", "change")


def _statements(tree: ast.Module) -> list[ast.stmt]:
    """The top level, with each top-level `if TYPE_CHECKING:` block's body spliced in."""
    out: list[ast.stmt] = []
    for node in tree.body:
        test = node.test if isinstance(node, ast.If) else None
        guarded = isinstance(test, ast.Name) and test.id == GUARD
        guarded |= isinstance(test, ast.Attribute) and test.attr == GUARD
        out.extend(node.body if isinstance(node, ast.If) and guarded else [node])
    return out


def _absolute(module: str, node: ast.ImportFrom) -> str:
    source = node.module or ""
    if not node.level:
        return source
    parts = module.rsplit(".", 1)[0].split(".")
    base = parts[: len(parts) - node.level + 1]
    return ".".join([*base, source] if source else base)


def _table(nodes: list[ast.stmt]) -> dict[str, dict[str, str]]:
    """`DEPRECATED = {"old": Deprecation(...)}`'s literal entries as plain dicts."""
    out: dict[str, dict[str, str]] = {}
    for node in nodes:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not any(isinstance(t, ast.Name) and t.id == TABLE for t in targets):
            continue
        if not isinstance(value, ast.Dict):
            continue
        for key, call in zip(value.keys, value.values, strict=True):
            if isinstance(key, ast.Constant) and isinstance(call, ast.Call):
                args = dict(zip(_FIELDS, call.args, strict=False))
                args.update({k.arg: k.value for k in call.keywords if k.arg})
                out[str(key.value)] = {
                    k: str(v.value) for k, v in args.items() if isinstance(v, ast.Constant)
                }
    return out


def _serves_shim(nodes: list[ast.stmt]) -> bool:
    """Whether the module's `__getattr__` is `shim(...)`'s."""
    return any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__getattr__" for t in n.targets)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", getattr(n.value.func, "attr", "")) == "shim"
        for n in nodes
    )


def reexports(tree: ast.Module, module: str) -> dict[str, tuple[str, str]]:
    """Imports (top level and under `TYPE_CHECKING`), aliases of them, and shim-served names."""
    nodes = _statements(tree)
    out: dict[str, tuple[str, str]] = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            source = _absolute(module, node)
            for alias in node.names:
                out[alias.asname or alias.name] = (source, alias.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            bound = out.get(node.value.id)
            for target in node.targets:
                if bound is not None and isinstance(target, ast.Name):
                    out[target.id] = bound
    if _serves_shim(nodes):
        for old, entry in _table(nodes).items():
            kind, dotted = entry.get("kind"), ""
            if kind == "renamed":
                dotted = entry.get("instead", "")
            elif kind == "removed":
                dotted = entry.get("change", "")
            if "." in dotted:
                source, _, name = dotted.rpartition(".")
                out[old] = (source, name)
            elif dotted in out:
                out[old] = out[dotted]
    return out
