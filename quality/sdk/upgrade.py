"""The product's fold, SDK step: each product import of a name the release deprecates or removed."""

# does-not-cover: a name reached by attribute (`import pilecap.api as a; a.x`) or by string.
# does-not-cover: a product that vendored a platform module — it imports no `pilecap` name.
# does-not-cover: TypeScript props, and kit names beyond the five moved screen paths.

from __future__ import annotations

import ast
import difflib
import fnmatch
import io
import json
import re
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality.djb.rituals.divergence import git, platform_apps, resolves
from quality.sdk.surface import SCHEMA, SURFACE, changed_fields, qualified, released, version

#: The release whose kit took the screen modules below.
KIT_SCREENS = "2.5.0"
#: The screen modules K2 moved into the kit: the old path a product imports → the kit's.
MOVED = {
    f"@/screens/{m}": f"@pilecap/ui/{m}"
    for m in ("state", "verbs", "routes", "refusal-panel", "remedy-door")
}
_TS_IMPORT = re.compile(r"""from\s+["'](@/screens/[a-z-]+)["']""")
_FACE = ("frontend/src/kit/", "frontend/src/screens/widget/", "frontend/src/screens/customer/")


@dataclass
class Hit:
    """One product import of an SDK name: where, which name, the alias it binds."""

    path: str
    line: int
    key: str
    alias: str
    app: str


def shown(root: Path, ref: str, path: str) -> str | None:
    """`git show <ref>:<path>`'s text, or None when the ref has no such path."""
    done = git(root, "show", f"{ref}:{path}")
    return done.stdout if done.returncode == 0 else None


def surface_at(root: Path, ref: str) -> dict[str, Any] | None:
    """The release's surface, or None when it carries none (a release before the SDK)."""
    text = shown(root, ref, SURFACE)
    if text is None:
        return None
    doc = json.loads(text)
    return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else None


def releases_between(root: Path, base: str, target: str) -> list[tuple[str, str]]:
    """(version, ref) for the base, every release tag after it, and the target, oldest first."""
    v_base = (shown(root, base, "TEMPLATE_VERSION") or "0.0.0").strip()
    v_target = (shown(root, target, "TEMPLATE_VERSION") or "0.0.0").strip()
    tags = []
    for tag in git(root, "tag", "--list", "v*").stdout.split():
        try:
            if version(v_base) < version(tag) < version(v_target):
                tags.append((tag.removeprefix("v"), tag))
        except ValueError:
            continue
    return [(v_base, base), *sorted(tags, key=lambda t: version(t[0])), (v_target, target)]


def product_apps(root: Path) -> list[Path]:
    """The product's own apps: every `apps/<x>/` with an `apps.py`, the platform and example out."""
    platform = set(platform_apps(root))
    home = root / "apps"
    return sorted(
        d
        for d in (home.iterdir() if home.is_dir() else [])
        if (d / "apps.py").is_file()
        and d.name not in platform
        and not fnmatch.fnmatch(d.name, "example*")
    )


def imports(root: Path, unread: list[str] | None = None) -> list[Hit]:
    """Every `from pilecap[.<m>] import <name>` in the product's apps; `unread` the unparsable."""
    hits: list[Hit] = []
    for app in product_apps(root):
        for path in sorted(app.rglob("*.py")):
            if "migrations" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(), str(path))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
                if unread is not None:
                    unread.append(f"{path.relative_to(root).as_posix()} does not parse ({exc})")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    if node.module == "pilecap" or node.module.startswith("pilecap."):
                        hits += [
                            Hit(
                                path.relative_to(root).as_posix(),
                                node.lineno,
                                f"{node.module}.{a.name}",
                                a.asname or a.name,
                                app.name,
                            )
                            for a in node.names
                        ]
    return hits


def moved_screens(root: Path) -> list[tuple[str, int, str]]:
    """Every product client import of a screen path the kit took: (file, line, old path)."""
    out: list[tuple[str, int, str]] = []
    src = root / "frontend/src"
    for path in sorted(src.rglob("*.ts*") if src.is_dir() else []):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(_FACE) or "node_modules" in path.parts:
            continue
        for n, text in enumerate(path.read_text(errors="replace").splitlines(), 1):
            out += [(rel, n, m) for m in _TS_IMPORT.findall(text) if m in MOVED]
    return out


def rename_in(text: str, old: str, new: str, line: int, module: str, new_module: str) -> str:
    """`text` with `old` renamed `new` at its import and every bare use; '' when not exact."""
    lines = text.splitlines(keepends=True)
    node = next(
        (
            n
            for n in ast.walk(ast.parse(text))
            if isinstance(n, ast.ImportFrom) and n.lineno == line and n.module == module
        ),
        None,
    )
    alias = next((a for a in node.names if a.name == old), None) if node else None
    if node is None or alias is None or (new_module != module and len(node.names) != 1):
        return ""
    names = [
        (new if a is alias else a.name) + (f" as {a.asname}" if a.asname else "")
        for a in node.names
    ]
    stmt = f"from {new_module} import {', '.join(names)}\n"
    end = node.end_lineno or node.lineno
    body = "".join([*lines[: node.lineno - 1], stmt, *lines[end:]])
    return body if alias.asname else bare_renamed(body, old, new, skip=node.lineno)


def bare_renamed(body: str, old: str, new: str, *, skip: int) -> str:
    """Every NAME token `old` not after a `.` (and off line `skip`) replaced by `new`."""
    lines = body.splitlines(keepends=True)
    edits: list[tuple[int, int, int]] = []
    prev = ""
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
        if tok.type == tokenize.NAME and tok.string == old and prev != "." and tok.start[0] != skip:
            edits.append((tok.start[0], tok.start[1], tok.end[1]))
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT):
            prev = tok.string
    for row, col, end in reversed(edits):
        lines[row - 1] = lines[row - 1][:col] + new + lines[row - 1][end:]
    return "".join(lines)


def sdk_step(root: Path, base: str, target: str, *, fix: bool = False) -> int:
    """Read every surface from `base` to `target`; print each product import the fold breaks."""
    for ref in (base, target):
        if not resolves(root, ref):
            print(f"!! sdk: {ref} does not resolve to a commit here — fetch it; could-not-look")
            return 2
    print(f"== sdk step · {base} → {target}")
    chain = [(v, ref, surface_at(root, ref)) for v, ref in releases_between(root, base, target)]
    read = [(v, ref, s) for v, ref, s in chain if s is not None]
    for v, ref, s in chain:
        print(f"   surface    {ref} ({v}): {'read' if s else 'none — a release before the SDK'}")
    if not read or read[-1][1] != target:
        print(f"== sdk: {target} carries no {SURFACE} — nothing to read")
        return 0
    v_target, _ref, last = read[-1]
    first = read[0][2]
    known = {n for _v, _r, s in read for n in s["names"]}
    told: dict[str, dict[str, str]] = {}
    for _v, _r, s in read:
        told.update(s.get("deprecations") or {})
    gone_in: dict[str, str] = {}
    for v, _r, s in read:
        for n in known - set(s["names"]) - set(s.get("deprecations") or {}):
            gone_in.setdefault(n, v)
    unread: list[str] = []
    hits = imports(root, unread)
    for why in unread:
        print(f"!! sdk: {why} — could-not-look; its imports are unread")
    broken = 0
    renames: list[tuple[Hit, str]] = []
    for hit in hits:
        entry = (last.get("deprecations") or {}).get(hit.key)
        where = f"{hit.path}:{hit.line}"
        if hit.key in last["names"] and entry is None:
            was, now = (first or {}).get("names", {}).get(hit.key), last["names"][hit.key]
            if was and now.get("migration") and was != now:
                base_name = hit.key.rpartition(".")[2]
                for f in changed_fields(was, now):
                    print(f"run makemigrations {hit.app} — {base_name}.{f} changed — {where}")
                if was.get("meta") != now.get("meta"):
                    print(f"run makemigrations {hit.app} — {base_name}.Meta changed — {where}")
            continue
        if entry is not None:
            text = (
                f"imports {hit.key}: deprecated since {entry['since']}, removed in {entry['until']}"
            )
            text += f"; use {entry['instead']}"
            if entry.get("kind") == "signature":
                text += f"; signature {entry.get('change', '')}"
            print(f"{text} — {where}")
            if entry.get("kind") == "renamed":
                renames.append((hit, qualified(hit.key, entry["instead"])))
            continue
        if hit.key not in known:
            continue
        last_word = told.get(hit.key)
        instead = last_word["instead"] if last_word else "nothing — the SDK no longer has it"
        print(
            f"imports {hit.key}: removed in {gone_in.get(hit.key, v_target)}; use {instead}"
            f" — {where}"
        )
        if last_word and last_word.get("kind") == "renamed":
            renames.append((hit, qualified(hit.key, instead)))
        broken += 1
    for path, line, old in (
        moved_screens(root) if released(v_target) >= released(KIT_SCREENS) else []
    ):
        print(
            f"imports {old}: deprecated since {KIT_SCREENS}, removed in 3.0; use {MOVED[old]}"
            f" — {path}:{line}"
        )
    fixed = fix_renames(root, renames) if fix else 0
    if fix:
        print(f"== sdk --fix: {fixed} exact rename(s) rewritten — commit the diff above")
    broken = max(0, broken - fixed) if fix else broken
    print(
        f"census: sdk imports={len(hits)} removed={broken} unread={len(unread)} target={v_target}"
    )
    if unread:
        print(f"== {len(unread)} PRODUCT FILE(S) UNREAD — could-not-look, never a clean census.")
        return 2
    if broken:
        print(f"== {broken} IMPORT(S) OF A REMOVED NAME — the merge of {target} breaks them.")
        print("   Rewrite each to the name it prints; `--fix` rewrites an exact rename.")
        return 1
    print("== CLEAN · no product import of a removed SDK name")
    return 0


def fix_renames(root: Path, renames: Sequence[tuple[Hit, str]]) -> int:
    """Rewrite each exact rename in place, printing its diff; the count rewritten."""
    done = 0
    for hit, new_key in renames:
        module, _, old = hit.key.rpartition(".")
        new_module, _, new = new_key.rpartition(".")
        path = root / hit.path
        before = path.read_text()
        after = rename_in(before, old, new, hit.line, module, new_module)
        if not after:
            print(
                f"   fix: {hit.key} → {new_key} is not an exact rename here — by hand:"
                f" {hit.path}:{hit.line}"
            )
            continue
        diff = difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            f"a/{hit.path}", f"b/{hit.path}",
        )  # fmt: skip
        print("".join(diff), end="")
        path.write_text(after)
        done += 1
    return done
