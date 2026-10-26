"""The plant namespace census."""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from apps.core.roads import road
from quality import checks as C
from quality import worlds as W
from quality.checks import EVENT_SEGMENT, FLOOR_PROXIES, event_name_segments
from quality.could_not_look import CouldNotLook as PlantCollisionCouldNotLook
from quality.engine._hub import JUDGED_SHAPE_CENSUS, ROOT
from quality.reason_floor import MIN_REASON

# --- the plant namespace census ----------------------------------------------
#
# A PLANT IS A CREATION WHERE NO PRODUCT'S FILE CAN BE. `mode: create` over a
# path a product really has is `PLANT REFUSED` at `Plant.put` — loud, but
# only on the tree that has the file, which is never the tree the plan was
# written on: the template's self-test went green over `frontend/src/app/
# page.tsx`, a path every Next product has, and a product's fold paid. This census
# asks the question of the PLAN instead of the tree, so it has the same answer
# everywhere: every `mode: create` or `mode: default` plant — the template's
# or a drawer's — has a path segment equal to `PROBE_APP`, the ONE declaration
# of the reserved name, or it is exit 2 before anything is planted.
#
# THE EXEMPTION GRAMMAR IS CLOSED, and it has three members:
#   mode: default     a creation only where absent — cannot collide, by mode;
#   apps/example/**   the worked example, by the standing promise that it
#                     keeps every shape a rule needs (stated once, here);
#   namespace_exempt  on the plant itself, `<reason> (MOVE-TRIGGER YYYY-MM-
#                     DD)`: the member's own declaration of why its path can
#                     never be a product's (a runner keyed on an app's NAME
#                     cannot be moved under a nested segment). A declaration
#                     on a plant the census would not refuse is vacuous and
#                     refused, so the valve count means what it says.
# No runner learns the reserved name; the census reads `rules.yaml` only.

#: The worked example's root — exempt by promise, never per form.
PLANT_NAMESPACE_EXAMPLE_ROOT = "apps/example/"
#: The one shape a `namespace_exempt:` value takes: a reason, then a dated
#: MOVE-TRIGGER in parentheses as its last word.
NAMESPACE_EXEMPT_RE = re.compile(
    r"^(?P<reason>\S.*\S)\s+\(MOVE-TRIGGER (?P<date>\d{4}-\d{2}-\d{2})\)$"
)


def _namespace_exempt_problem(value: object) -> str:
    """'' when `value` is a well-formed declaration; else what is wrong with it."""
    if not isinstance(value, str) or not value.strip():
        return "is empty — a valve with no reason is an off switch"
    m = NAMESPACE_EXEMPT_RE.match(value.strip())
    if not m:
        return (
            f"reads {value!r}, which does not end in a dated `(MOVE-TRIGGER YYYY-MM-DD)` — an "
            "exemption with no date is a note somebody wrote once"
        )
    try:
        datetime.date.fromisoformat(m.group("date"))
    except ValueError:
        return f"carries MOVE-TRIGGER {m.group('date')}, which is not a date"
    if len(m.group("reason")) < MIN_REASON:
        return f"gives the reason {m.group('reason')!r}, too short to be one"
    return ""


def plant_namespace_census(rules: list[dict]) -> tuple[list[str], dict[str, int], list[str]]:
    """Judge every create/default plant against the reserved segment.

    Returns (refusals, counts, declaring rule ids). The counts are derived from
    the plan handed in and nothing else — the head line of the self-test prints
    them, and a number typed anywhere would be a census that agrees with itself.
    """
    refusals: list[str] = []
    counts = {"judged": 0, "reserved": 0, "example": 0, "default": 0, "declared": 0, "outside": 0}
    declaring: list[str] = []
    for rule in rules:
        rid = str(rule.get("id", "?"))
        for kind in ("canaries", "negatives"):
            noun = "canary" if kind == "canaries" else "negative"
            for entry in rule.get(kind) or []:
                for e in entry_forms(entry):
                    if "plant_at" not in e:
                        continue
                    mode = e.get("mode")
                    plant_at = str(e.get("plant_at"))
                    fixture = e.get("fixture")
                    reserved = PROBE_APP in plant_at.split("/")
                    declared = "namespace_exempt" in e
                    if mode not in ("create", "default"):
                        if declared:
                            refusals.append(
                                f"rule {rid}: {noun} {fixture} at {plant_at} declares "
                                f"namespace_exempt on a mode: {mode} plant — the census judges "
                                "only creations (create, default), so the declaration exempts "
                                "nothing; remove it"
                            )
                        continue
                    counts["judged"] += 1
                    if declared:
                        if reserved:
                            refusals.append(
                                f"rule {rid}: {noun} {fixture} at {plant_at} declares "
                                f"namespace_exempt, and its path already carries the {PROBE_APP} "
                                "segment — a declaration that exempts nothing is vacuous; remove it"
                            )
                            continue
                        if mode == "default":
                            refusals.append(
                                f"rule {rid}: {noun} {fixture} at {plant_at} declares "
                                "namespace_exempt on a mode: default plant, which creates only "
                                "where the path is absent and is exempt by mode — the declaration "
                                "is vacuous; remove it"
                            )
                            continue
                        if plant_at.startswith(PLANT_NAMESPACE_EXAMPLE_ROOT):
                            refusals.append(
                                f"rule {rid}: {noun} {fixture} at {plant_at} declares "
                                f"namespace_exempt under {PLANT_NAMESPACE_EXAMPLE_ROOT}, which is "
                                "exempt by the worked example's promise — vacuous; remove it"
                            )
                            continue
                        problem = _namespace_exempt_problem(e.get("namespace_exempt"))
                        if problem:
                            refusals.append(
                                f"rule {rid}: {noun} {fixture} at {plant_at}: namespace_exempt "
                                f"{problem}. The shape is `namespace_exempt: <why this path can "
                                "never be a product's> (MOVE-TRIGGER <date>)`"
                            )
                            continue
                        counts["declared"] += 1
                        if rid not in declaring:
                            declaring.append(rid)
                    elif reserved:
                        counts["reserved"] += 1
                    elif mode == "default":
                        counts["default"] += 1
                    elif plant_at.startswith(PLANT_NAMESPACE_EXAMPLE_ROOT):
                        counts["example"] += 1
                    else:
                        counts["outside"] += 1
                        refusals.append(
                            f"rule {rid}: PLANT OUTSIDE THE RESERVED NAMESPACE — {fixture} is "
                            f"declared mode: {mode} at {plant_at}, which carries no {PROBE_APP} "
                            "segment; a plant is a creation where no product's file can be — "
                            f"move it under a {PROBE_APP} directory beneath the layer it proves, "
                            "or declare namespace_exempt: <why this path can never be a "
                            "product's> (MOVE-TRIGGER <date>)"
                        )
    return refusals, counts, declaring


def plant_namespace_line(rules: list[dict]) -> str:
    """The census's counts, one line, as the self-test's head prints them."""
    _refusals, c, declaring = plant_namespace_census(rules)
    by = f" (rules {', '.join(declaring)})" if declaring else ""
    return (
        f"plant census: {c['judged']} create/default · {c['reserved']} under {PROBE_APP} · "
        f"{c['example']} example · {c['default']} default (exempt by mode) · "
        f"{c['declared']} exempt{by} · {c['outside']} outside"
    )


# --- THE PLANT-COLLISION CENSUS: a plant never carries a name a real app serves
#
# A RULE THAT RESOLVES BY NAME JUDGES A PLANT AGAINST THE REAL TREE. Rule 42
# keys a service by `(module, name)`; 43 and 49 redefine a real route or
# service on purpose; 3 reads a URL name; 73 reads words. A plant named after
# something a real app serves is therefore judged against the real site rather
# than against itself — the canary inherits the real service's doors and goes
# dead, or the negative inherits a real finding and goes loud — and the tree
# that grows the name is never the tree the plant was written on. The census
# asks, before anything is planted: does any plant carry a name the tree under
# test serves? The plants are every fixture the plan names (`claimed_fixtures`,
# `extra_files:` included — never a directory glob; a file no rule plants is
# the orphan census's question) and every file under `DRIVE_FIXTURE_DIR`
# (the drives' own plants, which no `rules.yaml` entry names). What the tree
# serves is `manage.py introspect` — routes, URL names, tools, events,
# workflows, activities, the one reader — plus an `@service` walk over
# `apps/**/services.py`, because `introspect` has no services registry.
#
# A COLLISION THAT IS THE FORM UNDER TEST IS DECLARED ON THE PLANT, one line
# per name, where a reviewer reading the plant sees it: `# collides: <name> —
# <why>` (`// collides:` in TS/JS, `<!-- collides: … -->` in Markdown). A
# declaration whose name no longer collides is refused as vacuous — the
# `namespace_exempt` law above — so a real service renamed away cannot leave a
# stale sentence behind.
#
# EXIT 2, NEVER A VIOLATION: an undeclared collision is a dead canary in
# waiting, which is broken enforcement. And a tree the census cannot look at —
# `introspect` would not run, a plant would not parse — is exit 2 naming why,
# never a judgment on the half it could read.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * a plant colliding by SIGNATURE rather than by name — rule 42's bare-name
#     fallback (`quality/checks/rule_42.py`, the reach census's unqualified branch)
#     resolves a call by its last segment, and a plant whose call shape matches
#     a real service's is not a name this census reads;
#   * a `.py-tpl` under `apps/core/management/app_template/` — scaffolding, not
#     a plant, and no rule names it;
#   * a name a PRODUCT's app serves on the TEMPLATE's tree — the census runs on
#     the product's own tree too, where that app exists; coverage there, not a
#     blind spot here;
#   * a `mode: replace` plant over a real file where the replacement IS the real
#     site (rule 45's `ping`) — declared on the plant, never exempted by mode;
#   * the services half reads `@service` by decorator name over `services.py`
#     modules only — a service defined elsewhere, or under another decorator
#     name, is not in the served set until `introspect` carries a services
#     registry (the honest closure; not built here).

#: The declaration, on the plant. The comment marker is the file's own (`#`,
#: `//`, `<!--`); the body is `<name> — <reason>`, the reason at least
#: `MIN_REASON` characters, the dash the em dash every declaration here uses.
PLANT_COLLIDES_RE = re.compile(r"(?:#|//|<!--)\s*collides:(?P<body>.*?)\s*(?:-->)?\s*$")
PLANT_COLLIDES_BODY_RE = re.compile(r"^\s*(?P<name>[^\s—]+)\s+—\s+(?P<reason>\S.*?)\s*$")
#: Rule 73's population and its neighbours: the fixtures whose names are WORDS
#: in text rather than definitions, read by word (a word carrying `_` or `-`).
PLANT_TEXT_WORD_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".md"})
PLANT_TEXT_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


#: A dotted event name as a string literal, in any fixture.
#: An event name quoted in a plant, in the one grammar rule 16 judges by —
#: `quality.checks.event_shape`'s segments, read from the runtime's own module.
def plant_event_string_re() -> re.Pattern[str]:
    """A quoted `<app>.<noun>.<past-verb>` in a plant's text, in the runtime's grammar."""
    inner = r"\.".join([EVENT_SEGMENT] * event_name_segments())
    return re.compile(rf"""["']({inner})["']""")


#: The second population: the drives' own fixtures, which no rule names.
DRIVE_FIXTURE_DIR = ROOT / "scripts" / "tests" / "fixtures"
#: The sections of `manage.py introspect` the census reads; a missing one is
#: could-not-look, never an empty table.
PLANT_COLLISION_INTROSPECT_KEYS = ("routes", "urls", "tools", "events", "workflows", "activities")
#: Every kind of name the real tree serves, in the order a refusal names them.
SERVED_KINDS = ("service", "route", "url_name", "tool", "event", "workflow", "activity")
#: Which served kinds a planted name of each kind can collide with. A function
#: or a `name=` string may be any capability's name; a class is a workflow's; a
#: dotted string is an event's; a word in text may be anything but an event
#: (an event is dotted, and a word never is).
_PLANT_KIND_REACH: dict[str, tuple[str, ...]] = {
    "def": ("service", "route", "url_name", "tool", "workflow", "activity"),
    "name=": ("service", "route", "url_name", "tool", "workflow", "activity"),
    "class": ("workflow",),
    "event": ("event",),
    "word": ("service", "route", "url_name", "tool", "workflow", "activity"),
}
#: `introspect` reads the registries and opens no connection (measured: a
#: `DATABASE_NAME` naming no database answers exit 0). A tree with no `.env`
#: and nothing in the environment — the narrowed worlds `test_selftest_shapes.sh`
#: builds are clones with no `.env` — has settings that refuse to configure at
#: all, so the census names a database that does not exist rather than none: if
#: `introspect` ever opens a connection, that is a loud could-not-look, never a
#: read of somebody else's database.
PLANT_COLLISION_NO_DATABASE = "plant_census_opens_no_connection"


def _plant_rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


_PLANT_AST_CACHE: dict[Path, object] = {}


def _plant_real_ast(path: Path) -> object:
    """A real module's AST, once per run; a real module that will not parse is could-not-look."""
    import ast as _ast

    if path not in _PLANT_AST_CACHE:
        try:
            _PLANT_AST_CACHE[path] = _ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            raise PlantCollisionCouldNotLook(
                f"the real module {_plant_rel(path)} could not be read or parsed ({exc})"
            ) from exc
    return _PLANT_AST_CACHE[path]


def _plant_name_line(path: Path, name: str) -> int | None:
    """The line `name` is defined or assigned on in `path` — top level first, then anywhere."""
    import ast as _ast

    tree = _plant_real_ast(path)

    def defines(node: object) -> bool:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            return node.name == name
        if isinstance(node, (_ast.Assign, _ast.AnnAssign)):
            targets = node.targets if isinstance(node, _ast.Assign) else [node.target]
            return any(isinstance(t, _ast.Name) and t.id == name for t in targets)
        return False

    for node in getattr(tree, "body", []):
        if defines(node):
            return int(node.lineno)
    for node in _ast.walk(tree):  # type: ignore[arg-type]
        if defines(node):
            return int(node.lineno)  # type: ignore[attr-defined]
    return None


def _plant_dotted_site(dotted: str) -> str:
    """`apps.<x>.<y>.name` as `apps/<x>/<y>.py:<line>`; anything not in this tree stays dotted."""
    parts = dotted.split(".")
    if not parts or parts[0] not in ("apps", "config"):
        return dotted
    for i in range(len(parts) - 1, 0, -1):
        base = ROOT.joinpath(*parts[:i])
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                line = _plant_name_line(candidate, parts[i])
                rel = _plant_rel(candidate)
                return f"{rel}:{line}" if line else rel
    return dotted


def _plant_skip_real(path: Path) -> bool:
    """Tests, migrations and the reserved probe app are never what the tree SERVES."""
    return bool({"tests", "migrations", PROBE_APP} & set(path.relative_to(ROOT).parts))


def plant_served_names() -> dict[str, dict[str, list[str]]]:
    """What the tree under test serves: kind -> name -> its real sites (`file:line`).

    `introspect` is RUN, never read from `.rung/introspect.json` — that file is
    `rung_start.sh`'s snapshot of the tree it started on, and the census judges
    the tree under test. Raises `PlantCollisionCouldNotLook` naming why.
    """
    import ast as _ast

    served: dict[str, dict[str, list[str]]] = {kind: {} for kind in SERVED_KINDS}

    def add(kind: str, name: str, site: str) -> None:
        sites = served[kind].setdefault(name, [])
        if site not in sites:
            sites.append(site)

    # -- the services half: `introspect` has no services registry --------------
    for path in W.service_modules(ROOT):
        if _plant_skip_real(path):
            continue
        for node in _ast.walk(_plant_real_ast(path)):  # type: ignore[arg-type]
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if "service" in W.decorator_names(node):
                    add("service", node.name, f"{_plant_rel(path)}:{node.lineno}")

    # -- the introspect half: the one reader of routes, URLs, tools, events, workflows
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    if not (env.get("DATABASE_NAME") or env.get("DATABASE_URL")) and not (ROOT / ".env").is_file():
        env["DATABASE_NAME"] = PLANT_COLLISION_NO_DATABASE
    try:
        proc = subprocess.run(
            [sys.executable, "manage.py", "introspect"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlantCollisionCouldNotLook(f"`manage.py introspect` did not run ({exc})") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise PlantCollisionCouldNotLook(
            f"`manage.py introspect` exited {proc.returncode}: {' | '.join(tail)}"
        )
    try:
        intro = json.loads(proc.stdout)
    except ValueError as exc:
        raise PlantCollisionCouldNotLook(
            f"`manage.py introspect` printed something that is not JSON ({exc})"
        ) from exc
    missing = [k for k in PLANT_COLLISION_INTROSPECT_KEYS if not isinstance(intro.get(k), list)]
    if missing:
        raise PlantCollisionCouldNotLook(
            f"`manage.py introspect` carries no {', '.join(missing)} section — a missing "
            "section is not an empty one"
        )

    def probe(dotted: str) -> bool:
        return f".{PROBE_APP}." in f".{dotted}."

    for r in intro["routes"]:
        view = str(r.get("view") or "")
        if probe(view):
            continue
        site = _plant_dotted_site(view)
        add("route", view.rsplit(".", 1)[-1], site)
        if r.get("name"):
            add("url_name", str(r["name"]).split(":")[-1], site)
    for u in intro["urls"]:
        view = str(u.get("view") or "")
        if u.get("name") and not probe(view):
            add("url_name", str(u["name"]).split(":")[-1], _plant_dotted_site(view))
    tool_sites: dict[str, str] = {}
    for path in sorted(ROOT.glob("apps/**/mcp.py")):
        if _plant_skip_real(path):
            continue
        for node in _ast.walk(_plant_real_ast(path)):  # type: ignore[arg-type]
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if not isinstance(d, _ast.Call):
                    continue
                func = d.func
                called = (
                    func.attr
                    if isinstance(func, _ast.Attribute)
                    else func.id
                    if isinstance(func, _ast.Name)
                    else ""
                )
                if called != "tool":
                    continue
                named = next(
                    (
                        k.value.value
                        for k in d.keywords
                        if k.arg == "name"
                        and isinstance(k.value, _ast.Constant)
                        and isinstance(k.value.value, str)
                    ),
                    node.name,
                )
                tool_sites.setdefault(named, f"{_plant_rel(path)}:{node.lineno}")
    for t in intro["tools"]:
        name = str(t.get("name") or "")
        if name:
            add("tool", name, tool_sites.get(name, f"the MCP tool {name!r} (introspect)"))
    for e in intro["events"]:
        app, name = str(e.get("app") or ""), str(e.get("name") or "")
        if not name or app == PROBE_APP:
            continue
        events_py = ROOT / "apps" / app / "events.py"
        line = (
            _plant_name_line(events_py, str(e.get("constant") or ""))
            if events_py.is_file()
            else None
        )
        add("event", name, f"{_plant_rel(events_py)}:{line}" if line else f"apps/{app}/events.py")
    for w in intro["workflows"]:
        definition = str(w.get("definition") or "")
        if w.get("name") and not probe(definition):
            add("workflow", str(w["name"]), _plant_dotted_site(definition))
    for a in intro["activities"]:
        function = str(a.get("function") or "")
        if a.get("name") and not probe(function):
            add("activity", str(a["name"]), _plant_dotted_site(function))
    # A NAME THIS TREE SERVES IS NAMED BY THIS TREE'S SITE. A URL name ninja
    # mounts appears twice (the route's view and ninja's own wrapper); the
    # library's half is kept only where no site in this tree serves the name.
    for table in served.values():
        for name, sites in table.items():
            ours = [s for s in sites if ".py" in s]
            if ours:
                table[name] = ours
    return served


def plant_collision_population(rules: list[dict]) -> list[Path]:
    """Every plant the census reads: the plan's fixtures, then the drives' fixtures."""
    planned = sorted(claimed_fixtures(rules))
    drives = sorted(
        p
        for p in DRIVE_FIXTURE_DIR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    return [*planned, *drives]


def _plant_marker(path: Path) -> tuple[str, str]:
    """The comment a declaration takes in this file: (opener, closer)."""
    if path.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        return "//", ""
    if path.suffix == ".md":
        return "<!--", " -->"
    return "#", ""


def plant_declared_names(
    path: Path,
) -> tuple[list[tuple[str, str]], list[tuple[int, str, str]], list[str]]:
    """One plant's (names it carries, its declarations, its malformed declarations).

    Names are `(kind, name)`; a declaration is `(line, name, reason)`. The
    declaration lines are blanked before the names are read, so a name that
    appears ONLY in its own declaration collides with nothing (and is vacuous).
    Raises `PlantCollisionCouldNotLook` on a file that will not decode or parse.
    """
    import ast as _ast
    import textwrap as _textwrap

    rel = _plant_rel(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PlantCollisionCouldNotLook(f"{rel}: the census could not read it ({exc})") from exc
    declarations: list[tuple[int, str, str]] = []
    malformed: list[str] = []
    kept: list[str] = []
    opener, closer = _plant_marker(path)
    for lineno, line in enumerate(text.splitlines(), 1):
        m = PLANT_COLLIDES_RE.search(line)
        if not m:
            kept.append(line)
            continue
        kept.append("")
        body = PLANT_COLLIDES_BODY_RE.match(m.group("body"))
        if not body:
            malformed.append(
                f"{rel}:{lineno}: the collision declaration reads {line.strip()!r}; the shape is "
                f"`{opener} collides: <name> — <why the collision is the form under test>{closer}`"
            )
            continue
        if len(body.group("reason")) < MIN_REASON:
            malformed.append(
                f"{rel}:{lineno}: the collision declaration for {body.group('name')} gives the "
                f"reason {body.group('reason')!r}, too short to be one"
            )
            continue
        declarations.append((lineno, body.group("name"), body.group("reason")))
    stripped = "\n".join(kept) + "\n"
    names: list[tuple[str, str]] = []
    if path.suffix == ".py":
        # A FRAGMENT IS STILL A PLANT. An `append` fixture may be a class-body
        # fragment, indented for the class it lands in; it is read dedented,
        # and a file that parses neither way is could-not-look, never skipped.
        try:
            tree = _ast.parse(_textwrap.dedent(stripped))
        except SyntaxError as exc:
            raise PlantCollisionCouldNotLook(
                f"{rel}: the census could not parse it ({exc.msg}, line {exc.lineno}) — a plant "
                "whose names cannot be read is never skipped"
            ) from exc
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                names.append(("def", node.name))
            elif isinstance(node, _ast.ClassDef):
                names.append(("class", node.name))
            elif isinstance(node, _ast.Call):
                for k in node.keywords:
                    if (
                        k.arg in ("name", "url_name")
                        and isinstance(k.value, _ast.Constant)
                        and isinstance(k.value.value, str)
                    ):
                        names.append(("name=", k.value.value))
    names.extend(("event", m.group(1)) for m in plant_event_string_re().finditer(stripped))
    if path.suffix in PLANT_TEXT_WORD_SUFFIXES:
        names.extend(
            ("word", w)
            for w in sorted(set(PLANT_TEXT_WORD_RE.findall(stripped)))
            if "_" in w or "-" in w
        )
    return names, declarations, malformed


def plant_collision_census(
    plants: list[Path], served: dict[str, dict[str, list[str]]]
) -> tuple[list[str], dict[str, int]]:
    """Judge every plant's names against what the tree serves.

    Returns (refusals, counts). Counts are per (plant, name): `names` collided,
    `declared` of them carry their declaration, `undeclared` do not; `plants`
    is how many files were read. Every refusal is exit 2 at the caller.
    """
    refusals: list[str] = []
    counts = {"plants": 0, "names": 0, "declared": 0, "undeclared": 0}
    for path in plants:
        rel = _plant_rel(path)
        try:
            names, declarations, malformed = plant_declared_names(path)
        except PlantCollisionCouldNotLook as exc:
            refusals.append(f"PLANT COLLISION CENSUS COULD NOT LOOK — {exc}")
            continue
        counts["plants"] += 1
        refusals.extend(f"PLANT COLLISION DECLARATION MALFORMED — {m}" for m in malformed)
        hits: dict[str, list[str]] = {}
        for kind, name in names:
            for real_kind in _PLANT_KIND_REACH[kind]:
                for site in served.get(real_kind, {}).get(name, []):
                    hit = f"{real_kind} {name} = {site}"
                    if hit not in hits.setdefault(name, []):
                        hits[name].append(hit)
        declared: dict[str, int] = {}
        for lineno, name, _reason in declarations:
            if name in declared:
                refusals.append(
                    f"PLANT COLLISION DECLARATION MALFORMED — {rel}:{lineno}: {name} is declared "
                    f"twice (first at line {declared[name]}); one line per name"
                )
                continue
            declared[name] = lineno
            if name not in hits:
                refusals.append(
                    f"PLANT COLLISION DECLARATION VACUOUS — {rel}:{lineno} declares that it "
                    f"collides on {name}, and nothing this tree serves is named {name}: a "
                    "declaration that exempts nothing is vacuous — remove it (the real name was "
                    "renamed away, or it never collided)"
                )
        opener, closer = _plant_marker(path)
        for name in sorted(hits, key=lambda n: SERVED_KINDS.index(hits[n][0].split(" ", 1)[0])):
            counts["names"] += 1
            if name in declared:
                counts["declared"] += 1
                continue
            counts["undeclared"] += 1
            refusals.append(
                f"PLANT COLLISION — {rel}: {'; '.join(hits[name])} — a plant carrying a name a "
                "real app serves is judged against the real site, not against itself: a rule "
                "that resolves by name reads the real one, and the canary goes dead (or the "
                "negative goes loud) on the tree that grew the name. Rename the plant to a name "
                "nothing serves, or, where the collision IS the form under test, declare it on "
                f"the plant: `{opener} collides: {name} — <why the collision is the mechanism "
                f"under test>{closer}`"
            )
    return refusals, counts


def plant_collision_run(rules: list[dict] | None = None) -> tuple[list[str], str]:
    """The census over this tree: (refusals, the head line). Every refusal is exit 2."""
    started = time.monotonic()
    try:
        served = plant_served_names()
    except PlantCollisionCouldNotLook as exc:
        return (
            [f"PLANT COLLISION CENSUS COULD NOT LOOK — {exc}; nothing was judged"],
            f"plant collisions: COULD NOT LOOK — {exc}",
        )
    plants = plant_collision_population(RULES if rules is None else rules)
    refusals, c = plant_collision_census(plants, served)
    n_served = sum(len(v) for v in served.values())
    return refusals, (
        f"plant collisions: {c['names']} names · {c['declared']} declared · "
        f"{c['undeclared']} undeclared — {c['plants']} of {len(plants)} plants and drive "
        f"fixtures read against {n_served} served names (introspect + the @service walk), "
        f"{time.monotonic() - started:.1f}s"
    )


def plant_collision_leg() -> None:
    """The census's own canaries and negatives, over plants it builds and a served table it forges.

    Every form is written into a scratch directory outside the tree and judged
    against a forged served table, so nothing here depends on what any real app
    serves — the names are the probe's own and nothing the example serves.
    """
    served: dict[str, dict[str, list[str]]] = {kind: {} for kind in SERVED_KINDS}
    served["service"]["census_probe_served"] = ["apps/probe_forged/services.py:1"]
    served["url_name"]["census-probe-served"] = ["apps/probe_forged/urls.py:1"]
    reason = "the probe's own collision, declared because it is the form under test"
    forms: list[tuple[str, str, str, str]] = [
        # (kind, file name, text, what the refusal must carry — "" for a negative)
        (
            "canary",
            "undeclared.py",
            "@service\ndef census_probe_served():\n    return None\n",
            "service census_probe_served = apps/probe_forged/services.py:1",
        ),
        (
            "negative",
            "declared.py",
            f"# collides: census_probe_served — {reason}\n@service\n"
            "def census_probe_served():\n    return None\n",
            "",
        ),
        (
            "canary",
            "vacuous.py",
            f"# collides: census_probe_unserved — {reason}\ndef census_probe_unserved():\n"
            "    return None\n",
            "VACUOUS",
        ),
        ("canary", "unparseable.py", "def census_probe_served(:\n", "COULD NOT LOOK"),
        (
            "canary",
            "short_reason.py",
            "# collides: census_probe_served — short\ndef census_probe_served():\n"
            "    return None\n",
            "too short",
        ),
        (
            "canary",
            "a_word.ts",
            'export const line = "open census-probe-served now";\n',
            "url_name census-probe-served",
        ),
        (
            "negative",
            "a_declared_word.ts",
            f"// collides: census-probe-served — {reason}\n"
            'export const line = "open census-probe-served now";\n',
            "",
        ),
        (
            "negative",
            "a_declared_word.md",
            f"<!-- collides: census-probe-served — {reason} -->\nopen census-probe-served now\n",
            "",
        ),
    ]
    fired = silent = 0
    with tempfile.TemporaryDirectory(prefix="plant-collision-") as scratch:
        for kind, name, text, want in forms:
            path = Path(scratch) / name
            path.write_text(text, encoding="utf-8")
            refusals, counts = plant_collision_census([path], served)
            if kind == "canary":
                if any(want in r for r in refusals):
                    fired += 1
                else:
                    RUN.broken.append(
                        f"PLANT-COLLISION CANARY DEAD — the form {name} did not produce a refusal "
                        f"carrying {want!r}: {refusals or 'nothing at all'}"
                    )
            elif refusals or counts["declared"] != 1:
                RUN.broken.append(
                    f"PLANT-COLLISION FALSE-POSITIVE REGRESSION — the declared form {name} was "
                    f"refused or not counted declared ({counts}): {refusals}"
                )
            else:
                silent += 1
    say(
        f"plant-collision census: its own forms — {fired} canaries fired · {silent} negatives "
        "silent"
    )


@road("blind_spot", example="quality/engine/plants.py::consistency")
def require_blind_spot(rule: dict, *, who: str | None = None) -> str | None:
    """Every rule declares what it cannot see: the refusal for one with no `does_not_cover`.

    None when the declaration names its blind spot; otherwise the one sentence
    `consistency()` records as broken enforcement (exit 2) — an instrument that
    does not say what it misses is one whose silence reads as a pass. `who`
    names a declaration that is not a rule (the runner seam); a rule is named
    by its id.
    """
    if str(rule.get("does_not_cover", "")).strip():
        return None
    name = who or f"rule {rule.get('id')}"
    return f"{name}: no does_not_cover — an undeclared blind spot"


#: A system check's registered id, as `apps/<x>/checks.py` writes it.
_REGISTERED_CHECK_ID = re.compile(r"""\bid=["']([a-z][a-z0-9_]*\.[EW]\d{3})["']""")


@road("check_ids", example="quality/engine/plants.py::consistency")
def check_id_census() -> list[str]:
    """THE REVERSE CENSUS: a system check id the tree REGISTERS that no rule claims is exit 2.

    The forward census (in `consistency`) asks whether every id a rule declares
    is present in a `checks.py`; this asks the other direction. A check that
    reports under an id no rule names is a finding with no statement, no
    `--explain`, no valve and no trailer — a red the engine cannot account for.
    Read from the template's `apps/core/checks.py` and every app's
    `checks.py`, by the `id="<tag>.<E|W>NNN"` a Django check message carries;
    the tag is the template's or the product's namespace.
    """
    out: list[str] = []
    namespace = world_module().RULE_ID_NAMESPACE
    prefixes = {TEMPLATE_CHECK_PREFIX} | ({namespace} if namespace else set())
    for path in sorted(ROOT.glob("apps/*/checks.py")):
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(_file_lines(path), start=1):
            for cid in _REGISTERED_CHECK_ID.findall(line):
                if cid.split(".", 1)[0] not in prefixes:
                    continue
                if cid not in DJANGO_ID_TO_RULE:
                    out.append(
                        f"{rel}:{lineno}: the system check id {cid} is registered and no rule "
                        "claims it — a red the engine cannot explain (no statement, no valve, no "
                        "trailer). Name it in the owning rule's `django_check_ids:`, or retire "
                        "the check"
                    )
    return out


def consistency() -> None:
    seam_consistency()
    for problem in [*_LOCAL_PROBLEMS, *_LOCAL_RATCHET_PROBLEMS]:
        RUN.broken.append(problem)
    for problem in _FLOOR_PROBLEMS:
        RUN.broken.append(f"member floors: {problem}")
    for problem in _NAMESPACE_PROBLEMS:
        RUN.broken.append(problem)
    if _PARTITION_PROBLEM:
        RUN.broken.append(_PARTITION_PROBLEM)
    local_ratchet_consistency()
    RUN.broken.extend(frozen_problems())
    local_plant_consistency()
    RUN.broken.extend(plant_mode_findings(RULES))
    RUN.broken.extend(plant_namespace_census(RULES)[0])
    RUN.broken.extend(duplicate_id_findings(RULES))
    RUN.broken.extend(check_id_census())
    fixture_census()
    RUN.broken.extend(fixture_dir_findings())
    for rule in RULES:
        rid = str(rule["id"])
        shape = id_shape_problem(rid)
        if shape:
            RUN.broken.append(shape)
        impl = rule.get("check")
        if impl:
            unresolved = resolve_check_problem(rid, str(impl))
            if unresolved:
                RUN.broken.append(unresolved)
        if (
            not impl
            and not rule.get("django_check_ids")
            and not rule.get("diff")
            and not rule.get("runner")
        ):
            RUN.broken.append(f"rule {rid}: no mechanism at all — not a rule, a wish")
        proxy = rule.get("floor_proxy")
        if proxy and proxy not in FLOOR_PROXIES:
            RUN.broken.append(f"rule {rid}: floor proxy {proxy!r} not in registry")
        doc = rule.get("doc") or {}
        doc_path = ROOT / doc.get("file", "")
        if not doc_path.is_file():
            RUN.broken.append(f"rule {rid}: doc file {doc.get('file')} missing")
        elif str(doc.get("contains", "")).lower() not in doc_path.read_text().lower():
            RUN.broken.append(
                f"rule {rid}: doc {doc['file']} no longer states the rule (anchor "
                f"{doc['contains']!r} missing)"
            )
        # THE VALVE, AS DATA (contract B.1). Every rule says how a legitimate
        # exception to it is recorded — the marker, and where it has to sit —
        # or says that nothing can excuse it and why. Before this field the
        # grammar was prose in four files (`quality/gate.py`'s generic
        # override, `checks.py`'s `# authz:`/`# reach:`/`# door:`/
        # `# role-bound:`, the conventions skill's table) and a reader holding
        # a red had no way to learn any of it from the red. A rule with
        # NEITHER form is exit 2 rather than a quieter trailer: the census of
        # which rules genuinely have no valve is the point of the field, and a
        # rule that silently declined to answer it would be the one place the
        # census cannot see.
        valve = rule.get("valve")
        if not isinstance(valve, dict):
            RUN.broken.append(
                f"rule {rid}: no valve — declare `valve: {{ marker: ..., where: ... }}` or "
                "`valve: { none: <why nothing can excuse this> }`; a red that cannot say how "
                "to record a legitimate exception is a red nobody can act on"
            )
        else:
            excuse = str(valve.get("none") or "").strip()
            marker = str(valve.get("marker") or "").strip()
            where = str(valve.get("where") or "").strip()
            if excuse and (marker or where):
                RUN.broken.append(
                    f"rule {rid}: valve declares `none:` AND a marker — one or the other, "
                    "never both; a reader cannot be told there is no valve and handed one"
                )
            elif excuse:
                if len(excuse) < MIN_REASON:
                    RUN.broken.append(
                        f"rule {rid}: valve `none:` reason is {len(excuse)} characters — a "
                        "claim that nothing can excuse this rule is exactly the claim that "
                        "owes a sentence a reviewer can disagree with"
                    )
            elif not (marker and where):
                RUN.broken.append(
                    f"rule {rid}: valve declares neither `marker:` + `where:` nor "
                    "`none: <reason>` — a valve a reader cannot paste, in a place the rule "
                    "will not read it, is not a valve"
                )
        canaries = rule.get("canaries") or []
        if len(canaries) < 2:
            RUN.broken.append(
                f"rule {rid}: fewer than two canary forms — a check that can't "
                "demonstrably fail two ways is decoration"
            )
        if not rule.get("negatives"):
            RUN.broken.append(f"rule {rid}: no negatives — restraint unproven")
        if not rule.get("floors"):
            RUN.broken.append(f"rule {rid}: no floors — green-because-empty would read as a pass")
        # the recorded self-test population. Required rather than
        # defaulted, because a rule that arrives without one is ratcheted at
        # zero and its canaries could all stop being planted in silence — which
        # is the exact failure this key exists to end.
        declared = rule.get("selftest_floor")
        if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
            RUN.broken.append(
                f"rule {rid}: no selftest_floor — record how many canary forms and negatives "
                "this rule's plan holds, so a plan that quietly loses one is exit 2 and not a "
                "smaller total nobody reads"
            )
        else:
            for kind, count in declared.items():
                try:
                    if int(count) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    RUN.broken.append(
                        f"rule {rid}: selftest_floor {kind!r} is {count!r}, which is not a count"
                    )
        for klass, count in (rule.get("ratchets") or {}).items():
            # A ratchet nobody can read is an off switch with extra steps.
            if not str(klass).strip():
                RUN.broken.append(f"rule {rid}: a ratchet with no class name")
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                RUN.broken.append(
                    f"rule {rid}: ratchet {klass!r} is {count!r}, which is not a count"
                )
        RUN.broken.extend(frozen_declaration_problems(rule))
        # `remedies:` is a fix form per finding class (ADR gate-6). An empty one
        # is worse than none: `--explain` prints the key and the reader learns
        # that somebody meant to write a remedy here.
        remedies = rule.get("remedies")
        if remedies is not None:
            if not isinstance(remedies, dict) or not remedies:
                RUN.broken.append(
                    f"rule {rid}: `remedies:` is {remedies!r} — it is a mapping of finding "
                    "class (or `*`) to the fix form for that class, and an empty one is a "
                    "promise `--explain` cannot keep"
                )
            else:
                for klass, text in remedies.items():
                    if not str(klass).strip() or len(str(text or "").strip()) < MIN_REASON:
                        RUN.broken.append(
                            f"rule {rid}: remedy {klass!r} is {text!r} — a fix form says what "
                            "to WRITE INSTEAD, and a reader cannot act on a blank one"
                        )
        blind = require_blind_spot(rule)
        if blind is not None:
            RUN.broken.append(blind)
        registry_floor_consistency(rule)
        rule_seam_consistency(rule)
        for kind, base in fixture_bases(rid):
            for entry in rule.get(kind) or []:
                for e in entry_forms(entry):
                    if not (base / rid / e["fixture"]).is_file():
                        RUN.broken.append(
                            f"rule {rid}: {kind[:-1]} fixture {e['fixture']} missing from "
                            f"{(base / rid).relative_to(ROOT)}/"
                        )
                # A form may DECLARE the world it needs when its plant path
                # cannot say so, and a declaration naming an app that is not on
                # this tree is a plan for a world nobody can enter.
                declared = entry.get("needs_app")
                if declared and not (ROOT / "apps" / str(declared)).is_dir():
                    RUN.broken.append(
                        f"rule {rid}: {kind[:-1]} {entry['fixture']} declares "
                        f"`needs_app: {declared}`, which is not an app under apps/"
                    )
        for cid in rule.get("django_check_ids") or []:
            # THE CHECK TAG IS THE ID'S FOURTH SPELLING (ADR gate-5). A
            # product's system check answers `acme.W001`, never `djb.W001`:
            # two products and the template all writing `djb.` is the id
            # collision again, one layer down, where Django's own registry
            # merges them and nothing here would see it.
            want = check_tag_prefix(rid)
            if not str(cid).startswith(f"{want}."):
                RUN.broken.append(
                    f"rule {rid}: django check id {cid} is not a `{want}.` tag — {id_grammar()}"
                )
            if is_template_id(rid):
                checks_src = (ROOT / "apps" / "core" / "checks.py").read_text()
                where = "apps/core/checks.py"
                found = str(cid) in checks_src
            else:
                # A product's checks live in the product's own app, so the
                # presence census reads every `checks.py` under `apps/` rather
                # than the template's one file.
                found = any(
                    str(cid) in p.read_text() for p in sorted(ROOT.glob("apps/*/checks.py"))
                )
                where = "any apps/*/checks.py"
            if not found:
                RUN.broken.append(f"rule {rid}: django check id {cid} not present in {where}")
        # every path a rule's SCOPE names must resolve on this
        # tree. A scope entry is read as a fact about today — "this file may
        # import the engine", "this tree may name the credential" — and rule
        # 33's own does_not_cover already declared it cannot tell whether an
        # allow-listed module still DESERVES to be. This is the sibling it was
        # missing: whether it EXISTS. Two of rule 33's five allow_import
        # entries named files no rung had written yet, so the statement a
        # reader was handed as true today described a tree that did not exist,
        # and nothing anywhere could say so. A forward-looking entry is now
        # added by the rung that lands the file, which keeps the allow-list a
        # diff rather than a discovery (the same discipline rule 11's
        # `extra_modules` comments record about themselves).
        for where, path in _scope_paths(rule.get("scope") or {}):
            if not (ROOT / path).exists():
                RUN.broken.append(
                    f"rule {rid}: scope {where} names {path}, which does not exist on this "
                    "tree — an allow-list entry is a fact about today, not a plan; add it in "
                    "the rung that writes the file"
                )
        # AND EVERY ENTRY SAYS WHY. The path check above asks whether an entry
        # names something real; this asks whether it carries the sentence a
        # reviewer can disagree with — one key, one floor, the valves' own.
        for problem in allow_list_reasons(rule):
            RUN.broken.append(f"rule {rid}: {problem}")


# --- planting --------------------------------------------------------------------


# --- plant placeholders: a fixture may not freeze the tree's state ------------
#
# THE INCIDENT (P7, the SRCH-FIX push). Rule 6's negative plants "one honest new
# leaf on top of the real one" into `apps/example/migrations/`, and all three of
# its moving parts were TYPED: the parent in the fixture, the number in
# `plant_at`, and the marker in its extra file. R-e landed
# `0011_widget_search_vector`, so the plant stopped being a successor and became
# a SECOND LEAF — the negative fired, the self-test went exit 2, and the push was
# blocked by a fixture rather than by the tree.
#
# THIS WAS THE FOURTH TIME. rules.yaml's own comment on that entry said so
# ("CORE-11 (0010) is the third rung to pay this"), and paying it a fifth time
# means every rung that touches `apps/example` — the designated search-adoption
# app, which will keep growing migrations — owes an edit to a file in `quality/`
# that has nothing to do with what it built. That is the collision the whole
# discovery discipline exists to avoid, pointed at the gate instead of at
# `config/`.
#
# THE FIX IS DERIVATION, the same answer the rest of this engine already gives:
# a fixture names what it wants and the resolver reads today's tree.
#
# {{leaf:<app>}} the app's current single migration leaf
# {{after:<app>:<slug>}} the next number after it, plus <slug> —
# `0011_widget_search_vector` -> `0012_neg_leaf`
#
# Substituted in BOTH `plant_at` and fixture CONTENT, because a plant that
# derived its parent but kept a typed filename would still fork the graph on the
# number alone. An unknown placeholder, or an app whose graph does not have
# exactly one leaf, is exit 2 (could-not-look) — never a silent literal.
PLACEHOLDER = re.compile(r"\{\{(leaf|after):([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_]+))?\}\}")

# : Resolved ONCE, against the unplanted tree, and cached. Deliberate: the
# : resolver reads the migration graph, and rule 6's canaries plant INTO that
# : graph — a resolver that re-read per plant would be reading a tree an earlier
# : plant had already moved. `selftest` primes it before the first plant, and
# : `tree_dirty_under_plants` (which runs first, and refuses a dirty tree) is what
# : makes "unplanted" a fact rather than a hope.
_RESOLVED: dict[str, str] = {}
_RESOLVED_PRIMED = False


def resolve_plant_text(text: str) -> str:
    """Every `{{...}}` in a plant_at or a fixture body, replaced from today's tree."""

    def one(match: re.Match[str]) -> str:
        kind, app_label, slug = match.group(1), match.group(2), match.group(3)
        leaf = _RESOLVED.get(app_label)
        if leaf is None:
            leaf = C.app_migration_leaf(ROOT, app_label)
            if leaf is None:
                RUN.broken.append(
                    f"plant placeholder {match.group(0)}: apps/{app_label} does not have "
                    "exactly one migration leaf on this tree, so a fixture cannot be "
                    "chained onto it. The self-test could not look — it has not passed"
                )
                return match.group(0)
            _RESOLVED[app_label] = leaf
        if kind == "leaf":
            return leaf
        number, _, _rest = leaf.partition("_")
        try:
            nxt = f"{int(number) + 1:04d}"
        except ValueError:
            RUN.broken.append(
                f"plant placeholder {match.group(0)}: the leaf {leaf!r} does not begin with "
                "a migration number, so there is no 'next' to derive"
            )
            return match.group(0)
        return f"{nxt}_{slug}" if slug else nxt

    return PLACEHOLDER.sub(one, text)


def prime_plant_resolution() -> None:
    """Read the tree's leaves once, before anything is planted into it."""
    global _RESOLVED_PRIMED
    if _RESOLVED_PRIMED:
        return
    _RESOLVED_PRIMED = True
    for f in plan_forms(RULES):
        resolve_plant_text(str(f.form["plant_at"]))
        fixture = f.home / f.form["fixture"]
        if fixture.is_file():
            resolve_plant_text(fixture.read_text())


#: THE PLANT VOCABULARY, CLOSED. What each `mode:` means, and the one question
#: each asks of the tree before it writes a byte:
#:
#:   create   a NEW file. The path must not exist — a plant is a creation, and
#:            a path the tree already holds is could-not-look, never an
#:            overwrite. On a product's tree the file standing there is the
#:            product's own (its barrel, its declared base), and writing over it
#:            both destroys what the form was about and silently changes what
#:            the form measures.
#:   append   the fixture on the end of the file (created empty if absent).
#:   replace  a DELIBERATE overwrite of a file the tree must already have; an
#:            absent path is could-not-look, never a creation.
#:   default  create only if absent — the tree's own file, when it has one,
#:            stands and is what the form is judged on (rule 60's declared base:
#:            the template's tree has none and the plant supplies `HEAD`; a
#:            product's tree has its own and keeps it).
#:   absent   the path is REMOVED for the duration of the plant (the fixture's
#:            bytes are not read); `restore()` writes the original back. The one
#:            form whose subject is a file NOT being there, on a tree that has it.
#:
#: Anything else is exit 2 at `consistency()` and a refusal at `Plant.put` —
#: an unknown mode is a plan nobody can read, never a silent `create`.
PLANT_MODES: tuple[str, ...] = ("create", "append", "replace", "default", "absent")

#: THE SHAPE A FORM NEEDS, declared on the form itself (`needs_shape:`), and a
#: closed vocabulary like `mode:`. A plant can add, replace or remove a FILE; it
#: cannot remove an environment variable or a git remote, so a form whose
#: subject is a tree with NO template base declared cannot be produced on a
#: tree that declares one through the `template` remote or `DJB_TEMPLATE_BASE`.
#: Such a form says so here, and the self-test asks the census's own judged
#: shape — under the plant — whether this tree IS that shape:
#:
#:   template  no template base declared (the census's `base none declared`):
#:             the template's own tree, and a product's only if every base
#:             reader it has is one a plant can take away.
#:
#: On a tree that is not the shape, the form is NOT PRODUCIBLE ON THIS SHAPE:
#: printed on the rule's line, subtracted from the floor exactly as a form
#: whose app this world lacks is, counted at the foot — never judged fired or
#: silent, and never a could-not-look. A judged shape the census could not give
#: is could-not-look (exit 2). An unknown word is exit 2 at `consistency()`.
NEEDS_SHAPES: tuple[str, ...] = ("template",)

#: THE TREE A FORM NEEDS TO BE CLEAN, declared on the form itself
#: (`needs_clean_tree:`), a closed vocabulary like `needs_shape:`. The dirty-tree
#: refusal the self-test already makes (`tree_dirty_under_plants`) asks only
#: about the PLANT paths; a form that plants a template BASE (`mode: default` at
#: `scripts/local/template-base`) makes the census judge every template-owned
#: path against that base, so an uncommitted edit ANYWHERE in the template's
#: territory reads as the form's own finding — true, and about your edit rather
#: than the form (a FALSE-POSITIVE a builder debugs). Such a form
#: says so here:
#:
#:   template-owned  no template-owned path outside the plants differs from
#:                   HEAD. Asked of the census's OWN classifier, with HEAD typed
#:                   as the base (`DJB_TEMPLATE_BASE=HEAD`), so "template-owned"
#:                   has one reader in this tree and not two.
#:
#: A tree that is not clean that way is COULD NOT LOOK on the rule's line, naming
#: the paths — never a lowering and never a fired negative. An unknown word is
#: exit 2 at `consistency()`.
NEEDS_CLEAN_TREES: tuple[str, ...] = ("template-owned",)


def plan_created_paths() -> set[str]:
    """Every path some form in the plan CREATES — the shapes this engine can produce.

    Read by `Plant.put`'s `absent` branch: a path a form plants is a path some
    tree carries (the product whose own file a `default` defers to), so an
    `absent` over it on a tree that lacks it is the template's shape, not a
    misspelling. Literal, not resolved: a `{{...}}` placeholder names a migration
    a plant writes, never a path an `absent` removes, and resolving here could
    append a placeholder refusal to `broken` from a question that asked none.
    """
    return {
        str(f.form["plant_at"])
        for f in plan_forms(RULES)
        if "plant_at" in f.form and f.form.get("mode") != "absent"
    }


#: The rule ids a narrowed self-test judges; empty on a whole run.
NARROWED: set[str] = set()


class Plant:
    """Plant fixture files into the real tree; restore exactly, whatever happens."""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes | None] = {}
        self.made_dirs: list[Path] = []
        #: The cause the rule line prints when a refusal has a sharper one than
        #: `plant refused: <path>`; '' for every refusal that does not.
        self.refusal = ""

    def _remember(self, target: Path) -> None:
        if target not in self.saved:
            self.saved[target] = target.read_bytes() if target.exists() else None

    def put(self, fixture: Path, plant_at: str, mode: str, *, rid: str | None = None) -> bool:
        """Plant one fixture. True when the plant is held; False when it was REFUSED.

        A refusal writes nothing, appends one `PLANT REFUSED` line to `broken`
        (could-not-look, exit 2) and leaves the caller to count the form as not
        judged — never as dead and never as silent. `rid` defaults to the
        fixture's own directory name, which is the rule id for every fixture
        home this engine has (`quality/{canary,negative}/<id>/`,
        `quality/local/{canary,negative}/<ns>-<n>/`).
        """
        rid = rid or fixture.parent.name
        rid_at = f"{rid} (outside the narrowed set)" if NARROWED and rid not in NARROWED else rid
        plant_at = resolve_plant_text(plant_at)
        target = ROOT / plant_at
        if mode not in PLANT_MODES:
            RUN.broken.append(
                f"rule {rid_at}: PLANT REFUSED — {fixture.name} at {plant_at} is declared "
                f"mode: {mode!r}, which is not one of {', '.join(PLANT_MODES)}; a plan "
                "nobody can read is could-not-look, never a silent create"
            )
            return False
        exists = target.exists()
        if mode == "create" and exists:
            RUN.broken.append(
                f"rule {rid_at}: PLANT REFUSED — {plant_at} already exists on this tree and "
                f"{fixture.name} is declared mode: create; a plant is a creation and an "
                "existing path is could-not-look, never an overwrite (mode: replace is the "
                "form that means to replace it)"
            )
            return False
        if mode == "replace" and not exists:
            RUN.broken.append(
                f"rule {rid_at}: PLANT REFUSED — {plant_at} does not exist on this tree and "
                f"{fixture.name} is declared mode: replace; a replace means a file this tree "
                "has, and an absent path is could-not-look, never a creation (mode: create is "
                "the form that means to create it)"
            )
            return False
        if mode == "default" and exists:
            # The tree's own file stands, untouched and unremembered: there is
            # nothing to restore because nothing was written.
            return True
        if mode == "absent" and not exists and plant_at not in plan_created_paths():
            # A PATH NO TREE CARRIES. An `absent` over a path this tree lacks is
            # legitimate only when some shape carries it — a product's, which
            # the plan's own forms produce by planting it (rule 60's template
            # base). A path this tree lacks AND no form plants is a misspelling
            # or a stale site, and removing nothing would read as a control that
            # held: could-not-look, never a silent no-op.
            self.refusal = (
                f"absent plant names a path this tree does not carry: {plant_at} — and no "
                "form in the plan plants it, so no shape could"
            )
            RUN.broken.append(
                f"rule {rid_at}: PLANT REFUSED — {fixture.name} is declared mode: absent at "
                f"{plant_at}, which this tree does not carry and no form in the plan plants; "
                "removing nothing proves nothing, so the form is could-not-look (a misspelled "
                "or stale plant_at)"
            )
            return False
        self._remember(target)
        if mode == "absent":
            if exists:
                target.unlink()
            return True
        parent = target.parent
        missing: list[Path] = []
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for d in reversed(missing):
            d.mkdir()
            self.made_dirs.append(d)
        content = resolve_plant_text(fixture.read_text())
        if mode == "append":
            base = target.read_text() if target.exists() else ""
            target.write_text(base + content)
        else:
            target.write_text(content)
        return True

    def scaffold_probe(self) -> None:
        self._remember(PROBE_DIR / "__init__.py")
        self._remember(PROBE_DIR / "apps.py")
        PROBE_DIR.mkdir(exist_ok=True)
        self.made_dirs.append(PROBE_DIR)
        (PROBE_DIR / "__init__.py").write_text("")
        (PROBE_DIR / "apps.py").write_text(PROBE_APPS_PY)

    def restore(self) -> None:
        for target, original in self.saved.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        for d in reversed(self.made_dirs):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        if PROBE_DIR.exists():
            shutil.rmtree(PROBE_DIR, ignore_errors=True)
        self.saved.clear()
        self.made_dirs.clear()


def plant_paths() -> list[str]:
    """Every path a plant can touch, RESOLVED — the dirty check reads these.

    Resolved rather than literal because `git status --porcelain -- <path>` on a
    `{{after:example:neg_leaf}}.py` matches nothing at all: the refusal that
    protects the tree would go on saying "clean" about a path it was no longer
    naming.
    """
    prime_plant_resolution()
    drawer = world_module().LOCAL_RULES_PATH
    paths: set[str] = {f"apps/{PROBE_APP}"}
    for f in plan_forms(RULES):
        at = resolve_plant_text(str(f.form["plant_at"]))
        if ROOT / at != drawer:
            paths.add(at)
        elif f.form["mode"] not in ("default", "absent"):
            RUN.broken.append(
                f"rule {f.rid}: {f.form['fixture']} plants the product's drawer {at} with "
                f"mode: {f.form['mode']}; the drawer is the product's, never a plant path, so"
                " it is planted only `default` (a declaration stands) or `absent` (restored"
                " byte for byte)"
            )
    return sorted(paths)


#: Short enough that no real fixture is excluded; long enough that a stub, a
#: blank line or a one-word file cannot match half the tree by accident.
MIN_FIXTURE_SIGNATURE = 20


def stale_plants() -> list[str]:
    """Files on this tree that ARE a fixture — the residue of a run that died.

    THE INCIDENT SHAPE, and it is the worst one this engine has: a self-test
    killed between plant and restore leaves its fixtures standing. The next run
    then reads planted wrongness as the product's own work — or, far worse,
    reads a planted NEGATIVE as a clean scan and reports green over a tree that
    is partly fixture. A gate that measures its own leftovers is not measuring
    anything, and nothing in its output says so.

    CLOSED QUESTION, AND DELIBERATELY THE NARROWEST TOTAL ONE: a plant target
    whose bytes ARE the fixture's bytes. Nobody writes a file identical to a
    planted violation by accident, and an ordinary edit under a plant path —
    which is most of `apps/` on any working day — is silent here. That is
    exactly why this can run on EVERY mode while the dirty-tree refusal below
    can only run inside the self-test: one asks whether a file changed, this
    asks whether a file IS a fixture.

    The scaffold app is the loudest member and needs no comparison at all: it
    exists only while a plant holds it, so finding it at rest is finding a run
    that never finished.
    """
    found: list[str] = []
    if PROBE_DIR.exists():
        found.append(
            f"apps/{PROBE_APP}/ — the self-test's scaffold app, which exists only while a "
            "plant is held. Finding it at rest is finding a run that never restored"
        )
    mark = len(RUN.broken)
    for f in plan_forms(RULES):
        e = f.form
        if e["mode"] == "absent":
            # An `absent` plant writes nothing, so it can leave no
            # fixture standing; the fixture's bytes are never read.
            continue
        fixture = f.home / e["fixture"]
        if not fixture.is_file():
            continue
        body = resolve_plant_text(fixture.read_text())
        if len(body.strip()) < MIN_FIXTURE_SIGNATURE:
            continue
        target = ROOT / resolve_plant_text(str(e["plant_at"]))
        if not target.is_file():
            continue
        try:
            text = target.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if text == body or (e["mode"] == "append" and text.endswith(body)):
            found.append(
                f"{target.relative_to(ROOT)} — the "
                f"{'canary' if f.kind == 'canaries' else 'negative'} "
                f"{e['fixture']} of rule {f.rid} is standing on the tree"
            )
    # Placeholder resolution reads the migration graph and can refuse; that
    # refusal belongs to the self-test, not to a preflight whose whole job is to
    # look at the tree before anything else does. Taken back rather than
    # surfaced here, so a preflight cannot invent a verdict of its own.
    del RUN.broken[mark:]
    return found


def refuse_stale_plants() -> None:
    """Exit 2 before anything measures a tree it would be measuring wrong.

    (ruled 2026-08-31): true of BOTH modes `main()` runs, not only `--selftest`. This
    function only appends to `broken`; the one `return` inside it is the
    "nothing stale" case. What used to make the header sentence a claim rather
    than a fact was `main()`'s own branch below it — `--selftest` already
    skipped its leg on `if not broken`, and plain scan mode called `live_scan`
    unconditionally, one `return`(-equivalent guard) short of the sentence
    above. Both modes now honour it.
    """
    stale = stale_plants()
    if not stale:
        return
    RUN.broken.append(
        "STALE PLANTS ON THE TREE — a self-test that did not reach its restore left these "
        "behind, and every leg after this line would be reading fixtures as the product's "
        "own code. A negative left standing is the dangerous half: it reports nothing and "
        "the run goes green over a tree that is partly planted. Remove them and run again "
        "(`git status --porcelain`, then `git checkout --` the tracked ones and delete the "
        "untracked ones):\n  " + "\n  ".join(stale)
    )


def tree_dirty_under_plants() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *plant_paths()],
        capture_output=True,
        text=True,
        check=False,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def tree_dirty_on_template_owned() -> tuple[list[str], str]:
    """Template-owned paths OUTSIDE the plants that differ from HEAD. (paths, could-not-look).

    `tree_dirty_under_plants`, widened — and only for a form that declares
    `needs_clean_tree: template-owned` (rule 60's base-planting forms). Those
    forms plant a base and make the census compare the WHOLE template-owned
    territory against it, so the plant paths are not the whole of what they
    read: an uncommitted edit to `scripts/db.sh` reads as the form's finding.

    ONE CLASSIFIER. "Template-owned" is the census's answer and nobody else's
    (`quality/djb/rituals/divergence.py`, through the publication bucket rules), so
    this asks the census itself with HEAD typed as the base — its tracked and
    untracked arms both — and reads its unnamed `divergence:` rows. A path the
    product's own architecture.md names is a decision the census already
    subtracts, so it cannot be misread and is not refused. Stdout to a file,
    never a pipe: the census refuses a pipe.
    """
    script = ROOT / JUDGED_SHAPE_CENSUS
    if not script.is_file():
        return [], f"{JUDGED_SHAPE_CENSUS} is not in this tree, so no path's owner could be read"
    env = {**os.environ, "DJB_TEMPLATE_BASE": "HEAD"}
    with tempfile.NamedTemporaryFile("w+", prefix="djb-clean-tree-", suffix=".log") as sink:
        proc = subprocess.run(
            [sys.executable, "-m", "quality.djb.rituals.divergence", "--if-declared"],
            cwd=ROOT,
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
        )
        sink.flush()
        sink.seek(0)
        report = sink.read()
    if proc.returncode not in (0, 1):
        return [], (
            f"the template-owned paths could not be read ({JUDGED_SHAPE_CENSUS} against HEAD "
            f"exited {proc.returncode})"
        )
    plants = plant_paths()
    found: list[str] = []
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped.startswith("divergence: "):
            continue
        body = stripped[len("divergence: ") :]
        if " · " not in body:
            continue  # the refusal's line-to-add, never a row (see rule 60's reader)
        path = body.split(" · ", 1)[0].strip()
        if not path or any(path == p or path.startswith(p.rstrip("/") + "/") for p in plants):
            continue
        if path not in found:
            found.append(path)
    return found, ""


from quality.engine.rules import (  # noqa: E402
    _scope_paths,
    allow_list_reasons,
    claimed_fixtures,
    duplicate_id_findings,
    entry_forms,
    fixture_census,
    fixture_dir_findings,
    frozen_declaration_problems,
    frozen_problems,
    local_plant_consistency,
    local_ratchet_consistency,
    plan_forms,
    plant_mode_findings,
    registry_floor_consistency,
    rule_seam_consistency,
    seam_consistency,
)
from quality.engine.run import _file_lines, resolve_check_problem  # noqa: E402
from quality.engine.world import (  # noqa: E402
    _FLOOR_PROBLEMS,
    _LOCAL_PROBLEMS,
    _LOCAL_RATCHET_PROBLEMS,
    _NAMESPACE_PROBLEMS,
    _PARTITION_PROBLEM,
    DJANGO_ID_TO_RULE,
    PROBE_APP,
    PROBE_APPS_PY,
    PROBE_DIR,
    RULES,
    RUN,
    TEMPLATE_CHECK_PREFIX,
    check_tag_prefix,
    fixture_bases,
    id_grammar,
    id_shape_problem,
    is_template_id,
    say,
    world_module,
)
