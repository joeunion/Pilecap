"""Rule 84: one road per job, and the copied shapes counted."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, _py_files, _read

# --- rule 84: one road per job, and the copied shapes counted -------------------

#: Shell files that ARE the refusal road and the drive harness, so a helper
#: defined in them is the road rather than a copy of it.
_EXIT2_ROADS = frozenset({"scripts/gate_refuse.sh", "scripts/tests/drive_preamble.sh"})
#: The one module whose reason floor is the road the others copy. It imports
#: nothing, so a runner in a world with no `apps/` can read it; the engine
#: re-exports it as `quality.gate.MIN_REASON`, which is not a second literal.
_REASON_ROAD = "quality/reason_floor.py"
#: The setting a link to our own host was built from before every link had a
#: surface. Read anywhere under `apps/` but the module carrying the
#: `absolute_url` road, it is a link that lands on the settings' host whoever
#: it is for (house rule 85's bypass, counted here).
_HAND_URL = "PUBLIC_BASE_URL"
#: The setting's name as a whole word: `PUBLIC_BASE_URL_SETTING` names it and reads nothing.
_HAND_URL_RE = re.compile(rf"\b{_HAND_URL}\b")
#: The job whose road is the one legal reader of `_HAND_URL`.
_URL_JOB = "absolute_url"
_SHELL_FN_RE = re.compile(
    r"^(?P<indent>\s*)(?:function\s+)?(?P<name>[A-Za-z_][\w:-]*)\s*\(\)\s*\{?\s*(?:#.*)?$"
)
_EXIT2_RE = re.compile(r"\bexit 2\b")
_BANG_RE = re.compile(r"\b(?:echo|printf)\s+(?:-[a-zA-Z]+\s+)*[\"']?!!")


_HEREDOC_RE = re.compile(r"(?<![<(])<<(?!<)(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")


def _heredoc_lines(lines: list[str]) -> set[int]:
    """0-based indices of every heredoc's text and terminator: another script's words."""
    inside: set[int] = set()
    index = 0
    while index < len(lines):
        match = _HEREDOC_RE.search(lines[index])
        index += 1
        if not match or lines[index - 1].lstrip().startswith("#"):
            continue
        if "((" in lines[index - 1][: match.start()]:
            continue
        strip_tabs, word = match.group(1) == "-", match.group(3)
        while index < len(lines):
            inside.add(index)
            end = lines[index].lstrip("\t") if strip_tabs else lines[index]
            index += 1
            if end == word:
                break
    return inside


def _shell_functions(lines: list[str]) -> list[tuple[str, int, list[str]]]:
    """(name, line, body) for each `name() {` closing at its own indent; heredoc text skipped."""
    out: list[tuple[str, int, list[str]]] = []
    heredoc = _heredoc_lines(lines)
    for index, text in enumerate(lines):
        match = _SHELL_FN_RE.match(text)
        if not match or index in heredoc:
            continue
        close = match.group("indent") + "}"
        body: list[str] = []
        for offset, later in enumerate(lines[index + 1 :], index + 1):
            if offset in heredoc:
                continue
            if later.startswith(close) and later[len(close) :].strip()[:1] in (
                "",
                ">",
                "|",
                "&",
                "2",
                "1",
                ";",
            ):
                break
            body.append(later)
        out.append((match.group("name"), index + 1, body))
    return out


def _calls_named(node: ast.AST, names: set[str]) -> set[str]:
    """The names in `names` this function body calls, not descending into nested defs."""
    seen: set[str] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in names:
                seen.add(name)
        stack.extend(ast.iter_child_nodes(child))
    return seen


def road_uniqueness(root: Path, rule: dict) -> CheckResult:
    """Rule 84 — one road per job, and the unregistered copies counted by FORM.

    ONE FUNCTION, TWO FINDING KINDS. Every class below is a closed question over
    a population the tree derives; `--explain 84` prints this docstring's
    grammar through the rule's remedies.

    second_road — the markers `quality.roads.census` reads, grouped by job. The
      first marker of a job stands (the platform's over a product's, then the
      lexically first path); every OTHER marker of that job is a finding unless
      the contiguous comment block directly above it carries `rule-84: <reason>`
      — a comment line, never a docstring — which the engine's one override
      reader honours with its reason floor. Recorded at zero. Judged over the
      UNCONDITIONAL markers only: a conditional one is the next class's.
    conditional_road — a marker the census read somewhere a road cannot stand:
      not at module level and not on a definition directly inside a
      module-level class — under an `if` (`TYPE_CHECKING` included), `try`,
      `with`, `for`, `while` or `match`, or inside a function. A road is
      unconditional: the finding names the enclosing statement. A conditional
      marker beside an unconditional one for the same job is this class ONLY:
      the unconditional one stands, and no `second_road` is read for the pair.
      Recorded at zero, and like `second_road` never a backlog a product records.
    private_twin — a module-level function whose name is `_`-led and not a
      dunder, defined in two or more APPS (`apps/<label>/`, non-test,
      non-migration modules). One finding per app beyond the first (by label)
      that defines the name, at that app's first definition — so a fourteenth
      copy raises the count and moving one copy to its road lowers it.
    exit2_helper — a shell function (under `scripts/`, `scripts/tests/`,
      `deploy/`) whose body carries both `exit 2` and an `echo`/`printf` whose
      text begins `!!`, outside the two files that ARE the road
      (`scripts/gate_refuse.sh`, `scripts/tests/drive_preamble.sh`). A body ends
      at the first `}` at the definition's own indentation; a heredoc's text is
      neither a definition nor a body line.
    discovery_loop — a Python function under `apps/`, `config/`, `quality/`
      (non-test) whose own body — nested definitions excluded — calls both
      `get_app_configs()` and `find_spec(`.
    reason_literal — a module-level assignment (plain or annotated) whose target
      name ends `REASON` and whose value is an integer literal, under `apps/` or
      `quality/`, outside `quality/reason_floor.py` — the one floor every valve
      imports (the engine re-exports it; a copy imports it from there).
    hand_url — a line under `apps/` (non-test, non-migration `.py`) that names
      `PUBLIC_BASE_URL`, outside the module carrying the `absolute_url` road's
      marker — prose included, because a line that teaches the bare read is
      where the next copy comes from. `config/` owns the value and is not read.
    """
    from quality import roads

    out = CheckResult()
    for key in ("markers_read", "roads_py", "roads_sh", "census_read"):
        out.targets_matched[key] = 0
    try:
        markers = roads.census(root)
    except (roads.CensusError, Exception) as error:  # could-not-look, never a clean census
        out.hit(
            "quality/roads.py",
            0,
            f"the road census could not read this tree ({error}) — a census nobody could read "
            "is not a tree with one road per job; the census_read floor says so as exit 2",
            klass="census",
        )
        markers = []
    else:
        out.count("census_read")
    out.count("markers_read", len(markers))
    out.count("roads_py", sum(1 for m in markers if m.carrier == "py"))
    out.count("roads_sh", sum(1 for m in markers if m.carrier == "sh"))

    # A ROAD IS UNCONDITIONAL. A marker under a block or inside a function is
    # one import may or may not produce — the census reads it, the door cannot
    # prove it, and a `TYPE_CHECKING` guard makes it a road only to a reader.
    unconditional: list[roads.Marker] = []
    for marker in markers:
        if marker.enclosure is None:
            unconditional.append(marker)
            continue
        out.hit(
            marker.path,
            marker.line,
            f"a road is unconditional and module-level: the marker for {marker.job!r} "
            f"({marker.where}) sits inside {marker.enclosure}. Move the marked definition "
            "to module level (or directly inside a module-level class), or remove the marker",
            klass="conditional_road",
        )

    standing = roads.standing(unconditional)
    # EVERY marker but the one that stands is reported, valved or not: the
    # engine's one override reader (`apply_overrides`) suppresses a valved one
    # with a reason of at least MIN_REASON and turns a bare one into its own
    # finding — the same law, the same census, as every other valve.
    for marker in unconditional:
        first = standing[marker.job]
        if marker is first:
            continue
        out.hit(
            marker.path,
            marker.line,
            f"a second road for the job {marker.job!r}: {marker.where} "
            f"({marker.path}:{marker.line}) beside {first.where} "
            f"({first.path}:{first.line}), which stands. Call the one that stands and "
            "delete this marker, or keep this road and declare it with `rule-84: "
            "<why yours stays>` on the comment line directly above its marker",
            klass="second_road",
        )

    # private_twin
    by_name: dict[str, dict[str, tuple[str, int]]] = {}
    apps = {app.name for app in _app_dirs(root)}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        app = Path(rel).parts[1] if len(Path(rel).parts) > 2 else ""
        if app not in apps:
            continue
        out.count("app_modules_read")
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if not name.startswith("_") or (name.startswith("__") and name.endswith("__")):
                continue
            sites = by_name.setdefault(name, {})
            if app not in sites:
                sites[app] = (rel, node.lineno)
    for name, sites in sorted(by_name.items()):
        if len(sites) < 2:
            continue
        labels = sorted(sites)
        for app in labels[1:]:
            rel, line = sites[app]
            out.hit(
                rel,
                line,
                f"{name} is defined in {len(labels)} apps ({', '.join(labels)}) — one job with "
                f"{len(labels)} private copies; move the body to the road its job names "
                "(`manage.py roads <job>`), or mark the survivor as the road if the job has none",
                klass="private_twin",
            )

    # exit2_helper
    for path in _py_files(root, "scripts", "scripts/tests", "deploy", suffixes=(".sh",)):
        rel = str(path.relative_to(root))
        if rel in _EXIT2_ROADS:
            continue
        out.count("shell_files_read")
        for name, line, body in _shell_functions(_read(path).splitlines()):
            text = "\n".join(body)
            if _EXIT2_RE.search(text) and any(_BANG_RE.search(b) for b in body):
                out.hit(
                    rel,
                    line,
                    f"{name}() is a private could-not-look helper (`!!` and `exit 2`) — call "
                    "`gate_refuse` (`manage.py roads could_not_look`) or the drive preamble's "
                    "helper instead of carrying a copy",
                    klass="exit2_helper",
                )

    # discovery_loop and reason_literal
    for path in _py_files(root, "apps", "config", "quality"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _calls_named(node, {"get_app_configs", "find_spec"}) == {
                    "get_app_configs",
                    "find_spec",
                }:
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} walks the app registry for a module of its own "
                        "(`get_app_configs()` and `find_spec(`) — call `core.discovery.declared` "
                        "(`manage.py roads discover`)",
                        klass="discovery_loop",
                    )
        if rel == _REASON_ROAD or not (rel.startswith("apps/") or rel.startswith("quality/")):
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            value = node.value
            if not (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
            ):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith("REASON"):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{target.id} = {value.value} is a private copy of the valve's reason "
                        "floor — import `quality.reason_floor.MIN_REASON` "
                        "(`manage.py roads valve`)",
                        klass="reason_literal",
                    )

    # hand_url — the seam's own module is found by its marker, never typed.
    url_road = standing.get(_URL_JOB)
    seam = url_road.path if url_road is not None else None
    for path in _py_files(root, "apps"):
        rel = str(path.relative_to(root))
        if rel == seam:
            continue
        out.count("url_modules_read")
        for number, text in enumerate(_read(path).splitlines(), start=1):
            if _HAND_URL_RE.search(text):
                out.hit(
                    rel,
                    number,
                    f"`{_HAND_URL}` is named outside the URL seam — a link built from it lands "
                    "on the settings' host whoever it is for; build it with "
                    "`absolute_url(path=..., surface=surface_for_role(<role>))` "
                    f"(`manage.py roads {_URL_JOB}`)",
                    klass="hand_url",
                )
    return out
