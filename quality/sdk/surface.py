"""The SDK's promise: `quality/sdk_surface.json` derived from `pilecap`; rule 97 ratchets it."""

# does-not-cover: behaviour under an unchanged signature — names, parameters, fields and Meta only.
# does-not-cover: a method of an exported class — its constructor is the signature read.
# does-not-cover: a manager or a property of an exported model — declared fields and Meta only.
# does-not-cover: TypeScript props — the kit's exported names only (2.6's).

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.sdk.census import ROOT, declared_all, facade_modules, parse

#: The derived file, and the kit's names-only surface it carries.
SURFACE = "quality/sdk_surface.json"
KIT_SURFACE = "frontend/src/kit/surface.json"
SCHEMA = "pilecap-sdk-surface/1"
SECTIONS = ("deprecations", "names", "ts")
KINDS = ("removed", "renamed", "signature")
#: The drawer whose `rule_id_namespace:` makes a tree a product's.
LOCAL_RULES = "quality/local/rules.yaml"
SKIP_LINE = (
    "sdk-surface: a product tree — the promise is the template's; the census reads it at the fold"
)
REGENERATE = "python -m quality.sdk --surface"
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")
_RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\]", re.M)
_INTENT = re.compile(r"^## \[Unreleased\][^\n]*?\b(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\b", re.M)
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:(a|b|rc)(\d+))?")
_TYPED_PRE = re.compile(r"-(alpha|beta|rc)\.(\d+)$")
_TYPED = {"alpha": "a", "beta": "b", "rc": "rc"}
_PHASE = {"a": 0, "b": 1, "rc": 2, "": 3}
#: The two signature texts the ratchet reads no parameters from.
UNRATCHETABLE = ("(?)", "(*args, **kwargs)")

Version = tuple[int, int, int, int, int]


# --- versions ------------------------------------------------------------------------------------


def version(text: str) -> Version:
    """A PEP 440 `N.N[.N][(a|b|rc)N]` (a leading `v`, a typed `-alpha.N` allowed), comparable."""
    typed = text.strip().removeprefix("v")
    typed = _TYPED_PRE.sub(lambda m: f"{_TYPED[m[1]]}{m[2]}", typed)
    found = _VERSION.fullmatch(typed)
    if not found:
        raise ValueError(text)
    major, minor, patch, phase, n = found.groups()
    return (int(major), int(minor), int(patch or 0), _PHASE[phase or ""], int(n or 0))


def released(text: str) -> Version:
    """The release `text` is, or is a candidate for — `2.5.0a1` reads as `2.5.0`."""
    return (*version(text)[:3], _PHASE[""], 0)


def prerelease(text: str) -> bool:
    """Whether `text` names a candidate (`a`, `b` or `rc`) rather than a release."""
    return version(text) != released(text)


def one_minor_past(since: str, until: str) -> bool:
    """Whether `until` is at least one minor release after `since`; a candidate is its release."""
    s, u = released(since), released(until)
    return u >= (s[0], s[1] + 1, 0, _PHASE[""], 0)


def deprecation_problem(name: str, entry: Mapping[str, str], deprecated: Iterable[str]) -> str:
    """Why one `DEPRECATED` entry is not a promise ('' when it is one)."""
    kind = entry.get("kind", "")
    if kind not in KINDS:
        return f"{name}: kind {kind!r} is none of {', '.join(KINDS)}"
    try:
        if not one_minor_past(entry.get("since", ""), entry.get("until", "")):
            return (
                f"{name}: until {entry.get('until')} is not one minor past since"
                f" {entry.get('since')} — a deprecation is served for at least one minor release"
            )
    except ValueError:
        pair = f"({entry.get('since')!r}, {entry.get('until')!r})"
        return f"{name}: since/until do not read as releases {pair}"
    if kind == "signature" and "→" not in entry.get("change", ""):
        return f"{name}: a `signature` entry carries its old→new text in `change`"
    if kind == "removed" and not entry.get("change"):
        return (
            f"{name}: a `removed` entry names the object it serves until {entry.get('until')}"
            " in `change`"
        )
    if kind != "signature" and qualified(name, entry.get("instead", "")) in set(deprecated):
        return f"{name}: instead {entry.get('instead')} is itself deprecated"
    return ""


def qualified(name: str, instead: str) -> str:
    """`instead` as a dotted name: a bare name lives in the deprecated name's own module."""
    return instead if "." in instead else f"{name.rpartition('.')[0]}.{instead}"


# --- signatures ----------------------------------------------------------------------------------


def signature_text(obj: Any) -> str:
    """Parameter names, kinds and which carry a default — never annotations or default values."""
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return "(?)"
    out: list[str] = []
    star = False
    params = list(sig.parameters.values())
    for i, p in enumerate(params):
        if p.kind is p.VAR_POSITIONAL:
            out.append(f"*{p.name}")
            star = True
        elif p.kind is p.VAR_KEYWORD:
            out.append(f"**{p.name}")
        else:
            if p.kind is p.KEYWORD_ONLY and not star:
                out.append("*")
                star = True
            out.append(p.name + ("=" if p.default is not p.empty else ""))
        nxt = params[i + 1] if i + 1 < len(params) else None
        if p.kind is p.POSITIONAL_ONLY and (nxt is None or nxt.kind is not p.POSITIONAL_ONLY):
            out.append("/")
    return f"({', '.join(out)})"


@dataclass
class Params:
    """A signature text read back: positional order, every keyword, the two catch-alls."""

    positional: list[str] = field(default_factory=list)
    keyword: set[str] = field(default_factory=set)
    defaults: set[str] = field(default_factory=set)
    posonly: set[str] = field(default_factory=set)
    var_pos: bool = False
    var_kw: bool = False

    @classmethod
    def read(cls, text: str) -> Params:
        """Parse `signature_text`'s form."""
        out = cls()
        tokens = [t for t in text.strip()[1:-1].split(", ") if t]
        pos_only = tokens.index("/") if "/" in tokens else -1
        keyword_only = False
        for i, token in enumerate(tokens):
            if token == "/":  # noqa: S105 — a path token compared to a separator, not a credential
                continue
            if token == "*":  # noqa: S105 — a path token compared to a wildcard, not a credential
                keyword_only = True
            elif token.startswith("**"):
                out.var_kw = True
            elif token.startswith("*"):
                out.var_pos = keyword_only = True
            else:
                name = token.rstrip("=")
                if token.endswith("="):
                    out.defaults.add(name)
                if not keyword_only:
                    out.positional.append(name)
                if i > pos_only:
                    out.keyword.add(name)
                else:
                    out.posonly.add(name)
        return out

    @property
    def names(self) -> set[str]:
        """Every named parameter."""
        return set(self.positional) | self.keyword


def narrowing(old: str, new: str) -> str:
    """Why `new` refuses a call `old` accepted ('' when every old call still binds)."""
    if "(?)" in (old, new):
        return ""
    a, b = Params.read(old), Params.read(new)
    why: list[str] = []
    if a.var_pos and not b.var_pos:
        why.append("*args dropped")
    if a.var_kw and not b.var_kw:
        why.append("**kwargs dropped")
    renamed: set[str] = set()
    for i, name in enumerate(a.positional):
        other = b.positional[i] if i < len(b.positional) else None
        if other is not None and {name, other} <= a.posonly | b.posonly:
            renamed.add(other)
        elif not b.var_pos and other != name:
            why.append(f"positional {name} moved or removed")
    why += [f"{n} removed" for n in sorted(a.keyword - b.keyword) if not b.var_kw]
    why += [f"required {n} added" for n in sorted(b.names - a.names - b.defaults - renamed)]
    why += [f"{n} lost its default" for n in sorted((a.defaults & b.names) - b.defaults)]
    return "; ".join(dict.fromkeys(why))


# --- models --------------------------------------------------------------------------------------


def _norm(value: Any) -> Any:
    """A deconstructed value as JSON with no address in it: classes and callables by name."""
    from django.db import models

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_norm(v) for v in value]
        return sorted(items, key=json.dumps) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, type) and issubclass(value, models.Model):
        return value._meta.label
    if isinstance(value, type) or callable(value):
        return f"{getattr(value, '__module__', '')}.{getattr(value, '__qualname__', '?')}"
    if hasattr(value, "deconstruct"):
        return _norm(value.deconstruct())
    return _ADDRESS.sub("", f"{type(value).__qualname__}:{value}")


def digest(value: Any) -> str:
    """Twelve base64 characters of the SHA-256 of the normalised value."""
    # why-not: hex — twelve hex digits read as a high-entropy secret to rule 23's scanner.
    raw = hashlib.sha256(json.dumps(_norm(value), sort_keys=True).encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()[:12]


META = (
    "abstract", "ordering", "unique_together", "indexes", "constraints", "managed",
    "default_related_name", "get_latest_by", "permissions", "default_permissions", "proxy",
)  # fmt: skip


def changed_fields(was: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """The fields whose digest differs between two model entries, gained or lost included."""
    old, new = dict(was.get("fields") or []), dict(now.get("fields") or [])
    return sorted(f for f in set(old) | set(new) if old.get(f) != new.get(f))


def model_entry(model: Any) -> dict[str, Any]:
    """Per declared field its `deconstruct()` digest (pairs), and one digest of the Meta."""
    # why-not: a {name: digest} map — `"password": "<digest>"` reads as a secret to rule 23.
    opts = model._meta
    fields = [*opts.local_fields, *opts.local_many_to_many]
    meta = {a: getattr(opts, a, None) for a in META}
    if not opts.abstract:
        meta["db_table"] = opts.db_table
    return {
        "fields": sorted([f.name, digest(f.deconstruct()[1:])] for f in fields),
        "meta": digest(meta),
        "migration": True,
    }


# --- derivation (imports the facade under Django) ------------------------------------------------


def public_modules(root: Path) -> list[tuple[str, bool]]:
    """Each facade module a product imports: (dotted name, is the testing half); `_x` out."""
    return [
        (module, testing)
        for module, _path, testing in facade_modules(root)
        if not module.rpartition(".")[2].startswith("_") or module == "pilecap"
    ]


def entry_for(obj: Any) -> dict[str, Any]:
    """One exported name's kind, source and signature (and fields, for a model)."""
    from django.db import models

    source = f"{getattr(obj, '__module__', '')}.{getattr(obj, '__qualname__', '')}".strip(".")
    if inspect.ismodule(obj):
        return {"kind": "module", "source": obj.__name__}
    if isinstance(obj, type) and issubclass(obj, models.Model):
        return {"kind": "model", "source": source, **model_entry(obj)}
    if isinstance(obj, type):
        return {"kind": "class", "source": source, "sig": signature_text(obj)}
    if inspect.isroutine(obj):
        return {"kind": "function", "source": source, "sig": signature_text(obj)}
    if callable(obj) and not isinstance(obj, (str, bytes)):
        return {"kind": "callable", "sig": signature_text(obj)}
    return {"kind": "value", "type": type(obj).__qualname__}


def derive(root: Path) -> tuple[dict[str, Any], list[str]]:
    """The surface the tree's facade exports, and every deprecation that is not a promise."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    sys.path.insert(0, str(root))
    import importlib

    import django

    django.setup()
    from pilecap._deprecated import target

    names: dict[str, Any] = {}
    deprecations: dict[str, dict[str, str]] = {}
    for module, _testing in public_modules(root):
        loaded = importlib.import_module(module)
        for name in getattr(loaded, "__all__", ()):
            names[f"{module}.{name}"] = entry_for(getattr(loaded, name))
        for name, entry in (vars(loaded).get("DEPRECATED") or {}).items():
            deprecations[f"{module}.{name}"] = {k: v for k, v in vars(entry).items() if v}
    problems: list[str] = []
    for name, entry in sorted(deprecations.items()):
        problem = deprecation_problem(name, entry, deprecations)
        if not problem and qualified(name, entry["instead"]) not in names:
            problem = f"{name}: instead {entry['instead']} is not a public name of the SDK"
        if not problem and entry["kind"] == "removed" and entry.get("change"):
            try:
                target(name.rpartition(".")[0], entry["change"])
            except (ImportError, AttributeError):
                problem = f"{name}: the removed object {entry['change']} does not resolve"
        if problem:
            problems.append(problem)
    kit = root / KIT_SURFACE
    ts = json.loads(kit.read_text())["modules"] if kit.is_file() else {}
    return {"deprecations": deprecations, "names": names, "ts": ts}, problems


def render(surface: Mapping[str, Any]) -> str:
    """The file's bytes: one line per entry, every key sorted — diffable and byte-stable."""
    lines = ["{", f' "schema": {json.dumps(SCHEMA)},']
    for i, section in enumerate(SECTIONS):
        items = sorted((surface.get(section) or {}).items())
        tail = "," if i < len(SECTIONS) - 1 else ""
        if not items:
            lines.append(f" {json.dumps(section)}: {{}}{tail}")
            continue
        lines.append(f" {json.dumps(section)}: {{")
        body = [
            f"  {json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}"
            for k, v in items
        ]
        lines.append(",\n".join(body))
        lines.append(f" }}{tail}")
    return "\n".join([*lines, "}"]) + "\n"


# --- the ratchet (no Django: the file, the facade's text, git) -----------------------------------


@dataclass
class Read:
    """What the facade's text says it exports and deprecates, without importing it."""

    names: dict[str, str] = field(default_factory=dict)
    deprecations: dict[str, dict[str, str]] = field(default_factory=dict)
    where: dict[str, str] = field(default_factory=dict)


def _literal_deprecations(tree: ast.Module) -> dict[str, dict[str, str]]:
    """`DEPRECATED = {"old": Deprecation(since=…, …)}` as plain dicts, literals only."""
    out: dict[str, dict[str, str]] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "DEPRECATED" for t in targets):
            continue
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Dict):
            continue
        for key, call in zip(value.keys, value.values, strict=True):
            if isinstance(key, ast.Constant) and isinstance(call, ast.Call):
                fields = ("since", "until", "instead", "kind", "change")
                args = dict(zip(fields, call.args, strict=False))
                args.update({k.arg: k.value for k in call.keywords if k.arg})
                out[str(key.value)] = {
                    k: str(v.value)
                    for k, v in args.items()
                    if isinstance(v, ast.Constant) and v.value
                }
    return out


def read_facade(root: Path) -> Read:
    """Every public facade module's `__all__` and `DEPRECATED`, read off its text."""
    read = Read()
    files = {module: path for module, path, _t in facade_modules(root)}
    for module, _testing in public_modules(root):
        path = files[module]
        tree = parse(path)
        rel = path.relative_to(root).as_posix()
        for name in declared_all(tree) or []:
            read.names[f"{module}.{name}"] = rel
        for name, entry in _literal_deprecations(tree).items():
            read.deprecations[f"{module}.{name}"] = entry
            read.where[f"{module}.{name}"] = rel
    return read


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `root`, both streams captured."""
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)


def load(text: str, where: str) -> dict[str, Any]:
    """A surface file's JSON; could-not-look when it does not read as one."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CouldNotLook(f"{where} is not JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise CouldNotLook(f"{where} is not a {SCHEMA} document")
    return doc


def releases(root: Path) -> list[str]:
    """The released versions `CHANGELOG.md` names, newest first."""
    try:
        return _RELEASE.findall((root / "CHANGELOG.md").read_text())
    except OSError as exc:
        raise CouldNotLook(
            "CHANGELOG.md is unreadable — the previous release is named there"
        ) from exc


def tagged(root: Path, tag: str) -> bool:
    """Whether `tag` resolves to a commit in this checkout."""
    return git(root, "rev-parse", "-q", "--verify", f"{tag}^{{commit}}").returncode == 0


def cutting_from_unreleased(root: Path) -> bool:
    """Whether CHANGELOG.md still heads `## [Unreleased]` — the release is not being cut."""
    return "\n## [Unreleased]" in (root / "CHANGELOG.md").read_text()


def previous(root: Path, before: str = "") -> tuple[str, dict[str, Any], str]:
    """(the release before `before` — or before the tree — its surface, where it came from)."""
    named = releases(root)
    if before in named:
        named = named[named.index(before) + 1 :]
    elif named and named[0] == current(root) and not cutting_from_unreleased(root):
        named = named[1:]
    named = [n for n in named if not prerelease(n)] or named
    if not named:
        return "", {}, "previous: no release in CHANGELOG.md — compared against the empty surface"
    tag = f"v{named[0]}"
    if not tagged(root, tag):
        return (
            tag,
            {},
            f"previous: {tag} does not resolve here — compared against the empty surface",
        )
    shown = git(root, "show", f"{tag}:{SURFACE}")
    if shown.returncode != 0:
        return (
            tag,
            {},
            f"previous: {tag} carries no {SURFACE} — the first release; every name added",
        )
    return tag, load(shown.stdout, f"{tag}:{SURFACE}"), f"previous: {tag}"


def current(root: Path) -> str:
    """`TEMPLATE_VERSION`, whitespace out."""
    return "".join((root / "TEMPLATE_VERSION").read_text().split())


def intent(root: Path) -> str:
    """The version `## [Unreleased] — <x.y.z>` names ('' when the heading names none)."""
    found = _INTENT.search((root / "CHANGELOG.md").read_text())
    return found.group(1) if found else ""


def building(root: Path, prev: str) -> tuple[str, str]:
    """(the release being built, the line saying how it was read) — never an assumed minor."""
    if not prev or version(current(root)) > version(prev):
        return current(root), ""
    named = intent(root)
    if named and version(named) > version(prev):
        return named, f"building: {named}, the ## [Unreleased] heading's"
    major, minor, patch = version(prev)[:3]
    nxt = f"{major}.{minor}.{patch + 1}"
    return nxt, f"building: ## [Unreleased] names no version — judged as {nxt}"


@dataclass
class Finding:
    """One rule-97 finding: where, which class, the sentence with its remedy."""

    path: str
    klass: str
    why: str


def judge_drift(cur: Mapping[str, Any], read: Read, kit: Mapping[str, Any]) -> list[Finding]:
    """(a) the file says what the tree exports, deprecates and the kit names."""
    out: list[Finding] = []
    filed = set(cur.get("names") or {})
    for name in sorted(set(read.names) - filed):
        out.append(
            Finding(
                read.names[name],
                "drift",
                f"{name} is exported and absent from {SURFACE} — run {REGENERATE}",
            )
        )
    for name in sorted(filed - set(read.names)):
        out.append(
            Finding(
                SURFACE,
                "drift",
                f"{name} is in {SURFACE} and no longer exported — run {REGENERATE}",
            )
        )
    if (cur.get("deprecations") or {}) != read.deprecations:
        out.append(
            Finding(
                SURFACE,
                "drift",
                f"the deprecations block is not the facade's DEPRECATED tables — run {REGENERATE}",
            )
        )
    if (cur.get("ts") or {}) != kit:
        out.append(
            Finding(SURFACE, "drift", f"the ts block is not {KIT_SURFACE} — run {REGENERATE}")
        )
    for name, entry in sorted(read.deprecations.items()):
        problem = deprecation_problem(name, entry, read.deprecations)
        if problem:
            out.append(Finding(read.where[name], "deprecation", problem))
    return out


def judge_release(prev: Mapping[str, Any], cur: Mapping[str, Any], release: str) -> list[Finding]:
    """(b) every name the previous release promised is kept, or leaves on a declared schedule."""
    out: list[Finding] = []
    before, now = prev.get("names") or {}, cur.get("names") or {}
    was, dep = prev.get("deprecations") or {}, cur.get("deprecations") or {}

    def home(name: str) -> str:
        module = name.rpartition(".")[0]
        return f"{module.replace('.', '/')}{'/__init__' if module == 'pilecap' else ''}.py"

    def due(entry: Mapping[str, str]) -> bool:
        return released(entry["until"]) <= released(release)

    for name, old in sorted(before.items()):
        new = now.get(name)
        entry = dep.get(name)
        if new is None:
            if entry and entry.get("kind") != "signature":
                if entry["kind"] == "renamed" and qualified(name, entry["instead"]) not in now:
                    out.append(
                        Finding(
                            home(name),
                            "renamed",
                            f"{name} is renamed to {entry['instead']}, which the SDK lacks",
                        )
                    )
                continue
            if name in was and due(was[name]):
                continue
            out.append(
                Finding(
                    home(name),
                    "removed",
                    (
                        f"{name} left the SDK with no deprecation. Keep it, or declare it in"
                        f' {home(name)}: DEPRECATED = {{"{name.rpartition(".")[2]}":'
                        f' Deprecation(since="{release}", until="<one minor later>",'
                        ' instead="<the name to use>", kind="removed"|"renamed")}'
                        " — removing a name with no deprecation is a major release"
                    ),
                )
            )
            continue
        if old.get("kind") != new.get("kind"):
            out.append(
                Finding(
                    home(name),
                    "signature",
                    f"{name} changed kind {old.get('kind')} → {new.get('kind')}",
                )
            )
            continue
        why = narrowing(str(old.get("sig", "")), str(new.get("sig", ""))) if "sig" in old else ""
        if why and not (entry and entry.get("kind") == "signature"):
            out.append(
                Finding(
                    home(name),
                    "signature",
                    (
                        f"{name} narrowed {old.get('sig')} → {new.get('sig')}: {why}. A narrowed"
                        " public signature is a major release; keep the old call binding (an"
                        " optional parameter is"
                        " minor), or declare a `signature` Deprecation with its old→new text"
                    ),
                )
            )
    for name, entry in sorted(was.items()):
        if name not in dep and not due(entry) and name not in now:
            out.append(
                Finding(
                    home(name),
                    "removed",
                    f"{name} was deprecated until {entry['until']} and left before it",
                )
            )
    for module, names in sorted((prev.get("ts") or {}).items()):
        gone = sorted(set(names) - set((cur.get("ts") or {}).get(module, [])))
        if gone:
            out.append(
                Finding(
                    KIT_SURFACE,
                    "removed",
                    f"{module} no longer exports {', '.join(gone)} — the kit's names are ratcheted",
                )
            )
    return out


def ratchet(root: Path) -> int:
    """Rule 97's census: `count` and `finding` lines; exit 0 · 2 could-not-look."""
    file = root / SURFACE
    if not file.is_file():
        raise CouldNotLook(f"{SURFACE} is absent — run {REGENERATE}")
    cur = load(file.read_text(), SURFACE)
    read = read_facade(root)
    print(f"count surface_names {len(cur.get('names') or {})}")
    print(f"count facade_names {len(read.names)}")
    local = root / LOCAL_RULES
    from quality.djb.boundary import namespace_in

    if namespace_in(local.read_text() if local.is_file() else None):
        print(SKIP_LINE)
        return 0
    kit_file = root / KIT_SURFACE
    kit = json.loads(kit_file.read_text())["modules"] if kit_file.is_file() else {}
    tag, prev, line = previous(root)
    print(line)
    print(f"count previous_names {len(prev.get('names') or {})}")
    sigs = [e.get("sig") for e in (cur.get("names") or {}).values()]
    print(f"count unratchetable_signatures {sum(s in UNRATCHETABLE for s in sigs)}")
    release, how = building(root, tag.removeprefix("v"))
    if how:
        print(how)
    from quality.sdk.reference import judge as judge_reference

    findings = judge_drift(cur, read, kit) + judge_release(prev, cur, release)
    findings += [Finding(path, "reference", why) for path, why in judge_reference(root)]
    for f in findings:
        print(f"finding {f.path}\t{f.klass}\t{f.why}")
    return 0


def main(argv: Sequence[str], root: Path | None = None) -> int:
    """`--surface [--check]` derives the file; `--ratchet` is rule 97's census."""
    parser = argparse.ArgumentParser(prog="python -m quality.sdk")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--surface", action="store_true", help=f"derive {SURFACE}")
    mode.add_argument("--ratchet", action="store_true", help="rule 97's census")
    parser.add_argument("--check", action="store_true", help="exit 1 when the file is stale")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(list(argv))
    home = (args.root or root or ROOT).resolve()
    try:
        if args.ratchet:
            return ratchet(home)
        surface, problems = derive(home)
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    for problem in problems:
        print(f"  !! deprecation: {problem}")
    text = render(surface)
    file = home / SURFACE
    stale = not file.is_file() or file.read_text() != text
    counts = " · ".join(
        f"{len(surface[s])} {w}"
        for s, w in zip(SECTIONS, ("deprecated", "names", "kit modules"), strict=True)
    )
    if args.check:
        print(f"surface: {'STALE — run ' + REGENERATE if stale else 'current'} · {counts}")
        return 1 if stale or problems else 0
    if problems:
        print(f"surface: not written — {len(problems)} deprecation(s) are not promises")
        return 1
    file.write_text(text)
    print(f"surface: wrote {SURFACE} · {counts}")
    return 0
