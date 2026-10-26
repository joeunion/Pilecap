"""Frozen: a recorded number that may only fall."""

from __future__ import annotations

import ast
import re
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

import yaml

from quality import check_v1
from quality import checks as C
from quality import worlds as W
from quality.could_not_look import CouldNotLook
from quality.engine._hub import ROOT
from quality.reason_floor import MIN_REASON

# --- frozen: a recorded number that may only fall --------------------------------

#: The stamp a paste line writes beside its number.
_RECORDED_AT = re.compile(r"#\s*recorded-at\s+([0-9a-fA-F]{4,40})\b")
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def declared_namespace(doc: Mapping[str, object] | None = None) -> str | None:
    """The `rule_id_namespace:` a drawer declares; None on a template; empty refuses (gate-5)."""
    if doc is None:
        doc = world_module().LOCAL_DOC
    if "rule_id_namespace" in doc and not str(doc["rule_id_namespace"] or "").strip():
        raise CouldNotLook("rule_id_namespace: is declared with no value — name the namespace")
    return str(doc.get("rule_id_namespace") or "").strip() or None


def identity_shape_in(text: str | None) -> str | None:
    """The raw `identity_shape:` a drawer's text declares; None when absent or empty."""
    if text is None:
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CouldNotLook(f"quality/local/rules.yaml could not be read as YAML: {exc}") from exc
    raw = doc.get("identity_shape") if isinstance(doc, Mapping) else None
    return str(raw or "").strip() or None


def frozen_file(rule_id: str, klass: str) -> str:
    """The file a frozen class's number is written in; a drawer rule's `ratchets:` is the drawer."""
    home = ratchet_home(rule_id, klass)
    if home == "quality/rules.yaml" and is_local_rule(rule_id):
        return "quality/local/rules.yaml"
    return home


def _yaml_child(node: yaml.Node | None, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if str(key_node.value) == key:
            return key_node, value_node
    return None


def _yaml_path(node: yaml.Node | None, *keys: str) -> tuple[yaml.Node, yaml.Node] | None:
    pair: tuple[yaml.Node, yaml.Node] | None = None
    for key in keys:
        pair = _yaml_child(node, key)
        if pair is None:
            return None
        node = pair[1]
    return pair


def _yaml_number(pair: tuple[yaml.Node, yaml.Node] | None) -> tuple[int, int] | None:
    if pair is None:
        return None
    try:
        return int(pair[1].value), pair[0].start_mark.line + 1
    except (TypeError, ValueError):
        return None


def recorded_number(text: str, home: str, rule_id: str, klass: str) -> tuple[int, int] | None:
    """`(number, line)` of one class's entry in one home's text; None when no entry is written.

    The homes: an app's `AppConfig.ratchet_floors`, `quality/ratchet_floors.yaml`, the drawer's
    top-level `ratchets:`, and a rule's own `ratchets:` in a rules file.
    """
    rid, klass = str(rule_id), str(klass)
    if home.endswith("/apps.py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        config = C._app_config_class(tree)
        node = C._app_floors_node(config) if config is not None else None
        if not isinstance(node, ast.Dict):
            return None
        wanted = f"{rid}.{klass.partition('.')[2]}"
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == wanted:
                try:
                    return int(ast.literal_eval(value)), key.lineno
                except (ValueError, TypeError):
                    return None
        return None
    try:
        document = yaml.compose(text, Loader=_YAML_LOADER)
    except yaml.YAMLError:
        return None
    if home == C.MEMBER_FLOORS_FILE:
        return _yaml_number(_yaml_path(document, rid, klass))
    if (rid, klass) in DRAWER_RATCHET_CLASSES:
        return _yaml_number(_yaml_path(document, "ratchets", rid, klass))
    rules = _yaml_child(document, "rules")
    if rules is None or not isinstance(rules[1], yaml.SequenceNode):
        return None
    for item in rules[1].value:
        found_id = _yaml_child(item, "id")
        if found_id is not None and str(found_id[1].value) == rid:
            return _yaml_number(_yaml_path(item, "ratchets", klass))
    return None


_TEXT_AT: dict[tuple[str, str, str], str | None] = {}


def _git_at(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """One git command in `root`; CouldNotLook when git itself cannot run."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *argv], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CouldNotLook(f"git {argv[0]} ({error})") from None


def text_at(ref: str, home: str, root: Path | None = None) -> str | None:
    """`home`'s bytes at `ref`; None when absent there; CouldNotLook on an unreadable ref."""
    root = ROOT if root is None else root
    key = (str(root), ref, home)
    if key in _TEXT_AT:
        return _TEXT_AT[key]
    if _git_at(root, "cat-file", "-e", f"{ref}^{{commit}}").returncode != 0:
        raise CouldNotLook(ref)
    shown = _git_at(root, "show", f"{ref}:{home}")
    _TEXT_AT[key] = shown.stdout if shown.returncode == 0 else None
    return _TEXT_AT[key]


class FrozenBase(NamedTuple):
    """The commits a frozen number is compared against, HEAD first, and their printed label."""

    refs: tuple[str, ...]
    label: str


#: The trunks whose fold bases are read; a local `main` counts only when HEAD is not its tip.
FROZEN_TRUNKS = (("refs/remotes/origin/main", "origin/main"), ("refs/heads/main", "main"))


def frozen_base(root: Path | None = None) -> FrozenBase:
    """HEAD and each resolving trunk's fold base; none before a commit; or CouldNotLook."""
    root = ROOT if root is None else root
    if _git_at(root, "rev-parse", "--git-dir").returncode != 0:
        raise CouldNotLook(f"{root} is not a git repository")

    def tip(name: str) -> str | None:
        found = _git_at(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
        return (found.stdout.strip() or None) if found.returncode == 0 else None

    head = tip("HEAD")
    if head is None:
        return FrozenBase((), "none (no commit yet)")
    forks: dict[str, list[str]] = {}
    for ref, name in FROZEN_TRUNKS:
        trunk = tip(ref)
        if trunk is None or (name == "main" and trunk == head):
            continue
        fork = _git_at(root, "merge-base", "HEAD", ref)
        sha = fork.stdout.strip()
        if fork.returncode != 0 or not sha:
            why = fork.stderr.strip() or "no common ancestor — a shallow history"
            raise CouldNotLook(f"merge-base HEAD {name}: {why}")
        forks.setdefault(sha, []).append(name)
    if not forks:
        return FrozenBase((head,), f"{head[:7]} (HEAD only)")
    label = ", ".join(f"{sha[:7]} ({', '.join(names)})" for sha, names in forks.items())
    return FrozenBase((head, *(sha for sha in forks if sha != head)), label)


def frozen_base_suffix() -> str:
    """The standing section's ` · base …` suffix for this checkout."""
    try:
        return f" · base {frozen_base().label}"
    except CouldNotLook as error:
        return f" · base unreadable ({error})"


#: The files every rule's `frozen:` list is read from.
FROZEN_LIST_HOMES = ("quality/rules.yaml", "quality/local/rules.yaml")


def _tree_text(home: str) -> str | None:
    """This checkout's working-tree bytes of `home`; None when absent."""
    try:
        return (ROOT / home).read_text(encoding="utf-8")
    except OSError:
        return None


def frozen_lists_at(ref: str, root: Path | None = None) -> dict[str, frozenset[str]]:
    """Every rule's `frozen:` list in the two rules files at `ref`; CouldNotLook if unreadable."""
    lists: dict[str, frozenset[str]] = {}
    for home in FROZEN_LIST_HOMES:
        text = text_at(ref, home, root)
        try:
            document = yaml.load(text, Loader=_YAML_LOADER) if text else None  # noqa: S506 — _YAML_LOADER is (C)SafeLoader, line 25
        except yaml.YAMLError:
            document = None
        rules = document.get("rules") if isinstance(document, dict) else None
        for rule in rules if isinstance(rules, list) else ():
            if isinstance(rule, dict) and rule.get("frozen"):
                lists[str(rule.get("id"))] = frozen_classes(rule)
    return lists


def frozen_judgement(
    rule_id: str, klass: str, home: str, now: int, then: int | None, ref: str
) -> str | None:
    """The refusal for a frozen number that rose, or a line that arrived, since `ref`; else None."""
    if then is None:
        return (
            f"rule {rule_id}: frozen class {klass!r} is recorded at {now} in {home}, and {ref} "
            "records no line for it — a frozen class's line never arrives or returns (its zero "
            f"state has no number); delete the line and fix the findings (`--explain {rule_id}`)"
        )
    if now > then:
        return (
            f"rule {rule_id}: frozen class {klass!r} is recorded at {now} in {home}, above the "
            f"{then} it held at {ref} — a frozen number may only fall; restore {then} or lower "
            f"it (`--explain {rule_id}`)"
        )
    return None


def frozen_declaration_problems(rule: dict) -> list[str]:
    """`frozen:` is a non-empty list of classes the rule records, remedies or counts per member."""
    rid = str(rule.get("id"))
    declared = rule.get("frozen")
    if declared is None:
        return []
    if (
        not isinstance(declared, list)
        or not declared
        or not all(isinstance(k, str) and k.strip() for k in declared)
    ):
        return [
            f"rule {rid}: `frozen:` is {declared!r} — a non-empty list of the finding classes "
            "whose recorded number may only fall"
        ]
    known = {str(k) for key in ("ratchets", "remedies") for k in (rule.get(key) or {})}
    known |= {str(k) for k in (rule.get("member_classes") or ())}
    return [
        f"rule {rid}: `frozen:` names {klass!r}, which the rule neither records, remedies nor "
        "counts per member — a freeze on nothing"
        for klass in declared
        if klass not in known
    ]


def frozen_entries() -> list[tuple[str, str, str, int, str]]:
    """Every frozen class's entry: `(rule, class, home, number, ref)`; ref its stamp, else HEAD."""
    out: list[tuple[str, str, str, int, str]] = []
    texts: dict[str, list[str]] = {}
    for rule in RULES:
        rid = str(rule["id"])
        if not frozen_classes(rule):
            continue
        for klass in sorted(str(k) for k in (rule.get("ratchets") or {})):
            if not is_frozen(rule, klass):
                continue
            home = frozen_file(rid, klass)
            if home not in texts:
                try:
                    texts[home] = (ROOT / home).read_text(encoding="utf-8").splitlines()
                except OSError:
                    texts[home] = []
            entry = recorded_number("\n".join(texts[home]), home, rid, klass)
            if entry is None:
                continue
            number, line = entry
            stamp = _RECORDED_AT.search(texts[home][line - 1]) if line <= len(texts[home]) else None
            out.append((rid, klass, home, number, stamp.group(1) if stamp else "HEAD"))
    return out


def frozen_departures(
    tree: dict[str, frozenset[str]], ref: str, label: str, root: Path | None = None
) -> list[str]:
    """Every class in a `frozen:` list at `ref` that this tree's list no longer names."""
    return [
        f"rule {rid}: class {klass!r} is in `frozen:` at {label} and not in this tree's — a "
        f"class may join `frozen:` and never leave it; restore it (`--explain {rid}`)"
        for rid, then in sorted(frozen_lists_at(ref, root).items())
        for klass in sorted(then - tree.get(rid, frozenset()))
    ]


def frozen_problems(
    root: Path | None = None,
    entries: list[tuple[str, str, str, int, str]] | None = None,
    lists: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """Every rise, arrival or departure against HEAD and each fold base, or a stamp alone."""
    entries = frozen_entries() if entries is None else entries
    derived = lists is None
    if lists is None:
        lists = {str(r["id"]): frozen_classes(r) for r in RULES if frozen_classes(r)}
    try:
        base = frozen_base(root)
    except CouldNotLook as error:
        return [
            f"FROZEN COULD NOT LOOK — the base every frozen number is compared against: `{error}`; "
            "a frozen number nobody can compare is never a pass"
        ]
    labels = {
        sha: ("HEAD" if i == 0 else f"the fold base {sha[:12]}") for i, sha in enumerate(base.refs)
    }
    problems: list[str] = []
    for sha in base.refs:
        try:
            if (
                derived
                and root is None
                and all(text_at(sha, h) == _tree_text(h) for h in FROZEN_LIST_HOMES)
            ):
                continue
            problems.extend(frozen_departures(lists, sha, labels[sha], root))
        except CouldNotLook as error:
            problems.append(f"FROZEN COULD NOT LOOK — `frozen:` lists at `{error}`")
    for rid, klass, home, number, stamp in entries:
        refs = base.refs if stamp == "HEAD" else (stamp,)
        for ref in refs:
            try:
                before_text = text_at(ref, home, root)
            except CouldNotLook as error:
                problems.append(
                    f"FROZEN COULD NOT LOOK — rule {rid}: {home} records frozen class {klass!r} "
                    f"at {number} against `{error}`, which this checkout's history cannot read; a "
                    "frozen number nobody can compare is never a pass"
                )
                break
            before = (
                recorded_number(before_text, home, rid, klass) if before_text is not None else None
            )
            why = frozen_judgement(
                rid, klass, home, number, before[0] if before else None, labels.get(ref, ref)
            )
            if why:
                problems.append(why)
                break
    return problems


# --- consistency -----------------------------------------------------------------


def _scope_paths(node: object, trail: tuple[str, ...] = ()) -> Iterator[tuple[str, str]]:
    """Every `path:` a rule's scope names, with the key trail that names it.

    Walked structurally rather than by a list of known keys, so a rule that
    invents a new allow-list shape is covered on the day it is written.
    """
    if isinstance(node, dict):
        value = node.get("path")
        if isinstance(value, str) and value.strip():
            yield ".".join(trail) or "scope", value.strip()
        for key, child in node.items():
            if key != "path":
                yield from _scope_paths(child, (*trail, str(key)))
    elif isinstance(node, list):
        for child in node:
            yield from _scope_paths(child, trail)


#: The lists whose entries are WORDS, not exemptions — bare strings by design,
#: each with why. Every other list in a rule's `scope:` (and every top-level
#: allow-list a runner reads, `ALLOW_LIST_KEYS`) is a list of entries, and an
#: entry carries `reason:` at the reason floor.
BARE_LISTS: dict[str, str] = {
    "service_verbs": (
        "a lexicon: the verbs a service may open with — each word is its own claim, and the "
        "list grows by a visible diff (house rule 16)"
    ),
    "standard_http_headers": (
        "a vocabulary: the HTTP standard's own header names, which no one in this tree chose"
    ),
    "exempt_apps": (
        "HELD as bare labels: `apps/core/checks.py` (rule 11's django half) reads each entry as "
        "a string, so the reason slot waits for that reader; the reason sits in the comment "
        "above each label"
    ),
    "field_exemptions": (
        "HELD as bare `app.Model.field` strings: `apps/core/checks.py` (rule 15's django half) "
        "reads each entry as a string, so the reason slot waits for that reader; the reason "
        "sits in the comment above each field"
    ),
}
#: The top-level allow-lists a runner reads from its own rule's declaration.
ALLOW_LIST_KEYS = ("allow_registries", "exporters")


def allow_list_entries(rule: dict) -> Iterator[tuple[str, object]]:
    """(the list's key, one entry) for every allow-list a rule declares."""
    for key, value in (rule.get("scope") or {}).items():
        if isinstance(value, list):
            for entry in value:
                yield str(key), entry
    for key in ALLOW_LIST_KEYS:
        for entry in rule.get(key) or []:
            yield key, entry


def allow_list_reasons(rule: dict) -> list[str]:
    """Why each of this rule's allow-list entries fails the reason floor; empty when none does.

    ONE ENTRY SHAPE: an entry names what it admits (`path`, `app`, `label`,
    `model`, `service`, `registry`, `action`, … and `function`) and says why in
    ONE key, `reason`, at `MIN_REASON` — the floor every comment valve is held
    to. A bare string is an entry with no reason slot, refused unless its list
    is a declared word list (`BARE_LISTS`).
    """
    out: list[str] = []
    for key, entry in allow_list_entries(rule):
        if isinstance(entry, dict):
            reason = " ".join(str(entry.get("reason") or "").split())
            if len(reason) < MIN_REASON:
                named = next((str(v) for k, v in entry.items() if k != "reason"), "?")
                out.append(
                    f"`{key}` entry {named!r} carries "
                    + (f"the reason {reason!r}" if reason else "no `reason:`")
                    + f" — an allow-list entry says why in `reason:`, at least {MIN_REASON} "
                    "characters, the floor every valve is held to"
                )
        elif key not in BARE_LISTS:
            out.append(
                f"`{key}` holds the bare entry {entry!r} — an allow-list entry is a mapping "
                "naming what it admits and its `reason:`; a list of words is declared in "
                "the engine's `BARE_LISTS` with why"
            )
    return out


def allow_list_census() -> list[str]:
    """The standing lines for the yaml half of the valves: every allow-list entry, counted."""
    entries = lists = bare = 0
    seen: set[tuple[str, str]] = set()
    for rule in RULES:
        for key, entry in allow_list_entries(rule):
            entries += 1
            seen.add((str(rule["id"]), key))
            if not isinstance(entry, dict):
                bare += 1
    lists = len(seen)
    return [
        f"allow-lists (standing): {entries} entries in {lists} lists — {entries - bare} with a "
        f"reason, {bare} words in declared word lists"
    ]


def registry_floor_consistency(rule: dict) -> None:
    """A floor over a registry an optional app feeds must say what it counts.

    `probed_paths: 11` is a fact about eleven executed registry entries — and
    six of rule 35's twenty-one entries are the worked example's. Take the
    worked example out and the same number is a fact about a world that no
    longer exists, so the floor reads as a broken gate rather than as a smaller
    tree. The repair is not a lower number (that would lower it for everybody);
    it is a DECLARED BASIS, from which the expectation is derived per run.

    Required only where it bites: a registry with no optional-app member feeds
    no world-dependent number, and taxing it would be a rule about nothing. The
    day such a member arrives, this refuses — which is the day the floor
    actually became world-dependent.
    """
    rid = str(rule["id"])
    registry = rule.get("registry") or []
    declared = rule.get("registry_floors") or {}
    floors = rule.get("floors") or {}
    if not registry:
        if declared:
            RUN.broken.append(f"rule {rid}: registry_floors declared with no registry to feed them")
        return
    for key, basis in declared.items():
        if str(basis) not in W.REGISTRY_BASES:
            RUN.broken.append(
                f"rule {rid}: registry_floors {key!r} names basis {basis!r}, which is not "
                f"one of {', '.join(sorted(W.REGISTRY_BASES))}"
            )
        if key not in floors:
            RUN.broken.append(
                f"rule {rid}: registry_floors names {key!r}, which is not one of this "
                "rule's floors — a derivation for a number nobody reads"
            )
    if not any(W.registry_entry_app(e) in OPTIONAL_APPS for e in registry):
        return
    for key in floors:
        if key not in declared:
            RUN.broken.append(
                f"rule {rid}: floor {key!r} is pinned to {floors[key]} over a registry an "
                f"OPTIONAL app feeds ({', '.join(sorted(OPTIONAL_APPS))}) and does not say "
                "what it counts. Declare `registry_floors: {"
                f"{key}: <basis>"
                "}` so the expectation is derived from the apps this deployment "
                f"actually holds — one of {', '.join(sorted(W.REGISTRY_BASES))}; `opaque` "
                "is the honest answer where the registry cannot count it, and carries its "
                "reason on the rule"
            )


def seam_consistency() -> None:
    """The scope-kind declarations, and the seam's own recorded population.

    The seam is held to the grammar it enforces on everything else: a declared
    blind spot and a recorded self-test population, refused when missing rather
    than defaulted. A default here would be the exact defect the key exists to
    end — a plan that quietly loses a canary and keeps printing a total.
    """
    for name, kind in SCOPE_KINDS.items():
        if not isinstance(kind, dict):
            RUN.broken.append(f"scope kind {name!r}: not a declaration")
            continue
        for key in ("roots", "suffixes"):
            value = kind.get(key)
            if not isinstance(value, list) or not value:
                RUN.broken.append(f"scope kind {name!r}: {key} is {value!r}, not a non-empty list")
        for suffix in kind.get("suffixes") or []:
            if not str(suffix).startswith("."):
                RUN.broken.append(
                    f"scope kind {name!r}: suffix {suffix!r} does not start with a dot"
                )
        if not str(kind.get("comment", "")).strip():
            RUN.broken.append(
                f"scope kind {name!r}: no comment token — a kind whose valve syntax is "
                "unknown is a kind whose overrides cannot be found, and an override nobody "
                "can find is an exemption nobody can count"
            )
    # THE SIGNATURE CENSUS, both directions. A form whose expected signature the
    # code can no longer emit is the quietest failure an assertion corpus has:
    # it matches nothing, reports nothing, and reads as "stayed silent" forever.
    # So the refusal classes are declared, derived from the protocol module's own
    # source, and demanded of the canary table — a class cannot be renamed
    # without its canary, and cannot exist without one.
    emitted = check_v1.emitted_refusal_classes()
    for missing in sorted(check_v1.REFUSAL_CLASSES - emitted):
        RUN.broken.append(
            f"the seam declares the refusal class {missing!r}, which quality/check_v1.py no "
            "longer raises — a canary expecting it would match nothing and read as silence"
        )
    for undeclared in sorted(emitted - check_v1.REFUSAL_CLASSES):
        RUN.broken.append(
            f"quality/check_v1.py raises the refusal class {undeclared!r}, which is not in "
            "REFUSAL_CLASSES — a way to be unbelievable that nothing is obliged to prove"
        )
    canaried = {want for _label, _rule, want in _seam_canaries()}
    for unproven in sorted(check_v1.REFUSAL_CLASSES - canaried):
        RUN.broken.append(
            f"the refusal class {unproven!r} has no seam canary — a branch of the protocol "
            "nobody can show fires is a branch nobody can show works"
        )
    declared = SEAM.get("selftest_floor")
    if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
        RUN.broken.append(
            "the seam has no selftest_floor — record how many runner-protocol canary forms "
            "and negatives the plan holds, so a plan that quietly loses one is exit 2"
        )
    else:
        for kind_name, count in declared.items():
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                RUN.broken.append(
                    f"the seam's selftest_floor {kind_name!r} is {count!r}, not a count"
                )
    unseen = require_blind_spot(SEAM, who="the seam")
    if unseen:
        RUN.broken.append(unseen)


def rule_seam_consistency(rule: dict) -> None:
    """A rule's kind, runner and tree declarations — shape only, never existence.

    `needs_tree` is deliberately NOT resolved against the filesystem, and that
    is the one place this differs from the scope-path assertion below it. A
    scope allow-list is a fact about today; a `needs_tree` is a statement about
    a tree a product may or may not have grown, and refusing the absent case
    would refuse the template's own steady state.
    """
    rid = str(rule["id"])
    kind = rule.get("kind")
    named = kind if isinstance(kind, list) else [kind]
    if isinstance(kind, list) and not kind:
        RUN.broken.append(f"rule {rid}: kind is an empty list — name the scope kinds it runs in")
    for one in named:
        if one is not None and not isinstance(one, dict) and str(one) not in SCOPE_KINDS:
            RUN.broken.append(
                f"rule {rid}: kind {one!r} is not one of the declared scope kinds "
                f"({', '.join(sorted(SCOPE_KINDS)) or 'none'})"
            )
    wanted = rule.get("needs_tree")
    if wanted is not None:
        if not isinstance(wanted, str) or not wanted.strip():
            RUN.broken.append(f"rule {rid}: needs_tree is {wanted!r}, not a path")
        else:
            # (ruled 2026-08-31): a non-empty string is not yet a PATH — an absolute
            # one, or one carrying `..`, could name something this checkout
            # does not own, which is exactly the shape `check_v1._refuse_outside_roots`
            # already refuses on the runner's OWN findings. `needs_tree` gets
            # the identical refusal rather than a second, looser one.
            candidate = Path(wanted)
            if candidate.is_absolute() or ".." in candidate.parts:
                RUN.broken.append(
                    f"rule {rid}: needs_tree is {wanted!r}, not a path RELATIVE to the "
                    "checkout root — an absolute path or a `..` segment could name something "
                    "this tree does not own"
                )
    runner = rule.get("runner")
    if runner is None:
        return
    if not isinstance(runner, dict):
        RUN.broken.append(f"rule {rid}: runner is {runner!r}, not a declaration")
        return
    argv = runner.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        RUN.broken.append(f"rule {rid}: runner argv is {argv!r}, not a non-empty list of strings")
    if "timeout" in runner:
        try:
            if int(runner["timeout"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            RUN.broken.append(f"rule {rid}: runner timeout is {runner['timeout']!r}, not seconds")
    if not W.kind_roots(rule, SCOPE_KINDS):
        RUN.broken.append(
            f"rule {rid}: a runner rule whose kind declares no roots can report about "
            "anywhere, which makes its scope whatever the instrument feels like"
        )
    if rule.get("needs_tree") is None and W.needs_tree(rule, SCOPE_KINDS) is None:
        RUN.broken.append(
            f"rule {rid}: a runner rule declares `needs_tree` — either on itself or on its "
            "kind — because a checkout without the tree must skip and say so rather than "
            "run an instrument at nothing"
        )


# --- the declaration's own census: one id per rule, one claimant per fixture -----
#
# Two failures of the DECLARATION rather than of the tree, and both arrive by
# the same route: a product merges a template release and the two rule sets are
# appended into one file. An id both sequences minted collides; a fixture
# directory both sequences numbered merges two rules' files into one directory.
# The first was already exit 2 with three words and no way forward; the second
# was not seen at all.


def _entry_descriptor(rule: dict, position: int) -> str:
    """How a reader tells two entries with one id apart, without a diff.

    The position in `quality/rules.yaml`'s own `rules:` list and the first
    words of the statement: enough for a product to say at a glance which of
    the two colliding entries is the one it wrote.
    """
    statement = " ".join(str(rule.get("statement") or "").split())
    if len(statement) > 70:
        statement = statement[:67] + "..."
    if rule.get("check"):
        mechanism = f"check {rule['check']}"
    elif rule.get("django_check_ids"):
        mechanism = "django checks " + ",".join(str(c) for c in rule["django_check_ids"])
    elif rule.get("runner"):
        mechanism = "a runner"
    elif rule.get("diff"):
        mechanism = "a diff rule"
    else:
        mechanism = "no mechanism"
    return f"entry #{position} in `rules:` ({mechanism}) — {statement or '(no statement)'}"


def duplicate_id_findings(rules: list[dict]) -> list[str]:
    """Two entries declaring one id, and what the holder of the red does next.

    THE REMEDY IS THE POINT. A bare `duplicate id` is true and unactionable:
    the reader cannot see WHICH two entries collided, does not know that the
    two also now share one canary directory, one negative directory and one
    valve number, and has no way to know which of the two is supposed to move.
    Every one of those is knowable here, so every one of them is said here.
    """
    seen: dict[str, tuple[int, dict]] = {}
    lines: list[str] = []
    for position, rule in enumerate(rules, start=1):
        rid = str(rule["id"])
        first = seen.get(rid)
        if first is None:
            seen[rid] = (position, rule)
            continue
        lines.append(
            f"rule {rid}: duplicate id — two entries in quality/rules.yaml declare it. "
            f"THE COLLISION: {_entry_descriptor(first[1], first[0])} AND "
            f"{_entry_descriptor(rule, position)}. They share more than the id: one canary "
            f"directory (quality/canary/{rid}/), one negative directory "
            f"(quality/negative/{rid}/) and one valve number, so a fold has merged two "
            f"rules' fixtures as well as their ids. REMEDY: only the template mints integer "
            f"ids, so the entry that moves is the product's. The namespace grammar is LIVE "
            f"on this tree ({GATE5_CITE}): declare "
            f"`rule_id_namespace: <ns>` once, top-level in quality/local/rules.yaml, beside "
            f"`template_rule_ids_through: <n>`, rename the product's entry to `<ns>-<n>`, "
            f"`git mv` both of its fixture directories to that id, rewrite its valve "
            f"comments to `# rule-<ns>-<n>:` and its check tag to `<ns>.Wnnn`. After that a "
            f"fold cannot collide at all. Do NOT renumber it to another integer: the "
            f"integers are the template's to mint and the next release takes the one you "
            f"picked."
        )
    return lines


def fixture_files_on_disk() -> list[Path]:
    """Every file under the two fixture trees, in one sorted list.

    `__pycache__` and `.DS_Store` are skipped because neither can be tracked
    (both are in `.gitignore`), so neither is a file anybody declared or can
    delete meaningfully — the census is about the tree git carries.
    """
    found: list[Path] = []
    for _kind, base in fixture_trees():
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.name == ".DS_Store":
                continue
            found.append(path)
    return found


def entry_forms(entry: dict) -> list[dict]:
    """One plan entry's planted forms: the entry itself, then each of its `extra_files`."""
    return [entry, *(entry.get("extra_files") or [])]


class PlanForm(NamedTuple):
    """One planted form: the rule, the plan list it is in, its entry, the form and its home."""

    rule: dict
    rid: str
    kind: str
    entry: dict
    form: dict
    home: Path


def plan_forms(rules: list[dict]) -> list[PlanForm]:
    """Every planted form of every canary and negative the rules plan, in plan order.

    The one walk of the plan — each entry, then its extra files — that the
    censuses below project from, so "the plan's forms" is one population.
    """
    out: list[PlanForm] = []
    for rule in rules:
        rid = str(rule.get("id", "?"))
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for form in entry_forms(entry):
                    out.append(PlanForm(rule, rid, kind, entry, form, fixture_home(kind, rid)))
    return out


def claimed_fixtures(rules: list[dict]) -> set[Path]:
    """Every fixture path some entry of some rule names, extra files included."""
    claimed: set[Path] = set(ENGINE_FIXTURES)
    for f in plan_forms(rules):
        claimed.add(f.home / str(f.form["fixture"]))
    return claimed


def orphan_fixture_findings(rules: list[dict], on_disk: list[Path]) -> list[str]:
    """A fixture file no entry claims — the mirror of the missing-fixture refusal.

    `consistency()` has always refused a fixture a rule NAMES and the tree does
    not have. This is the other direction, and it is the one a fold produces: a
    file sitting in `quality/canary/<n>/` or `quality/negative/<n>/` that no
    entry anywhere names. Nothing plants it, so nothing proves anything with
    it, and it reads to every later reader as coverage the self-test has — the
    most expensive kind of wrong, because it is wrong in the direction of
    confidence. It is exit 2 rather than a violation for the same reason a dead
    canary is: the failure is in the enforcement's own plan, not in the code
    under it.
    """
    claimed = claimed_fixtures(rules)
    ids = {str(rule["id"]) for rule in rules}
    lines: list[str] = []
    for path in on_disk:
        if path in claimed:
            continue
        base = NEGATIVE_DIR
        for _tree_kind, tree in fixture_trees():
            if tree in path.parents:
                base = tree
                break
        # THE DIRECTORY IS NAMED FROM THE TREE IT WAS FOUND IN, never from the
        # template's spelling: a drawer fixture reported as living under
        # `quality/canary/` sends its reader to a path that does not exist.
        here = base.relative_to(ROOT)
        drawer = base.is_relative_to(world_module().LOCAL_DIR)
        home = "quality/local/rules.yaml" if drawer else "quality/rules.yaml"
        parts = path.relative_to(base).parts
        rid = parts[0] if len(parts) > 1 else None
        if rid is None:
            nearest = (
                f"it sits directly in {here}/, which belongs to no rule at all — "
                f"every fixture lives under {here}/<rule id>/"
            )
        elif rid not in ids:
            nearest = (
                f"its directory {here}/{rid}/ is named for rule {rid}, and no rule "
                f"{rid} exists in {home}"
            )
        else:
            nearest = (
                f"rule {rid} is the nearest rule — no entry of rule {rid} claims it, in "
                f"`canaries:`, in `negatives:` or in any `extra_files:`"
            )
        lines.append(
            f"orphan fixture {path.relative_to(ROOT)}: {nearest}. A fixture no entry names "
            f"is planted by nothing and demonstrates nothing, and it reads as coverage this "
            f"self-test does not have. Either CLAIM it — add it to that rule's plan and raise "
            f"the rule's `selftest_floor` in the same diff — or, if a leg of quality/engine/ "
            f"plants it by path rather than through the plan, declare it in "
            f"ENGINE_FIXTURES — or DELETE it. After a template "
            f"fold this is usually two rules' fixtures merged into one directory by a "
            f"colliding id; fix the id first and the files follow it."
        )
    return lines


def engine_fixture_findings(engine: dict[Path, str]) -> list[str]:
    """An engine-planted fixture the tree does not have.

    The mirror of the orphan census, for the claims that live in this module
    rather than in `quality/rules.yaml`. It is the guard that turns "somebody
    deleted a fixture nothing in the plan named" from a `FileNotFoundError`
    halfway through a self-test into a refusal that says which leg breaks and
    why the file is there.
    """
    return [
        f"engine fixture {path.relative_to(ROOT)} is declared in ENGINE_FIXTURES and is not "
        f"on this tree: {why}. Restore the file, or delete the declaration in the same diff "
        "as the leg that reads it"
        for path, why in engine.items()
        if not path.is_file()
    ]


def fixture_census() -> None:
    """The orphan census over the real fixture trees, with its own floor.

    THE FLOOR IS HALF THE CENSUS. A walk that found nothing would report no
    orphans and read exactly like a clean tree, which is the green-because-empty
    shape every floor in this engine exists to refuse — so an empty walk, or a
    plan that claims no fixtures at all, is itself exit 2.
    """
    on_disk = fixture_files_on_disk()
    claimed = claimed_fixtures(RULES)
    if not on_disk or not claimed:
        RUN.broken.append(
            f"the orphan-fixture census looked at {len(on_disk)} file(s) under "
            f"quality/canary and quality/negative against {len(claimed)} claimed by "
            "quality/rules.yaml — one of the two is empty, so the census would report a "
            "clean tree whatever the tree held. That is could-not-look, not clean"
        )
        return
    RUN.broken.extend(engine_fixture_findings(ENGINE_FIXTURES))
    RUN.broken.extend(orphan_fixture_findings(RULES, on_disk))


def engine_fixture_dirs(engine: dict[Path, str] | None = None) -> set[str]:
    """The fixture DIRECTORY names `ENGINE_FIXTURES` claims, for the dir census.

    THE HALF `claimed_fixtures` COULD NOT REACH. That function claims engine
    fixtures BY PATH, so the FILE census is satisfied; the DIRECTORY census
    builds `claimed` out of rule ids alone, so a directory the engine plants
    into — one whose name is not any rule's id — is "a fixture directory no
    rule claims", exit 2, and NOTHING a reader declares can clear it. The
    template has never met it only because its one engine fixture happens to
    sit inside rule 50's directory; the first consumer's `read_census`
    partition fixtures do not, and their tree was exit 2 whatever they wrote.

    The name is the FIRST segment under the fixture tree, not `path.parent.name`
    — an engine fixture nested two deep belongs to the directory at the top of
    that tree, which is the thing the census iterates.
    """
    names: set[str] = set()
    for path in ENGINE_FIXTURES if engine is None else engine:
        for _kind, base in fixture_trees():
            if base in path.parents:
                names.add(path.relative_to(base).parts[0])
                break
        else:
            names.add(path.parent.name)
    return names


def fixture_dir_findings(
    bases: tuple[tuple[str, Path], ...] | None = None,
    claimed: set[str] | None = None,
    namespace: str | None = ...,  # type: ignore[assignment]
) -> list[str]:
    """Every directory under `quality/{canary,negative}/` is claimed by a rule.

    THE HALF A FILE CENSUS CANNOT SEE. A fold that merged two rules numbered
    `54` merged their fixture DIRECTORIES too, and the tree that came out had
    one `quality/canary/54/` holding two plans and no complaint from anything.
    A directory no rule id claims is therefore exit 2 — could-not-look, not a
    smaller census — and where its name carries a namespace this tree has not
    declared, the refusal says so, because that is the shape a half-finished
    adoption leaves behind (a `git mv` done and the key not written, or the key
    written and one directory missed).

    IT OVERLAPS `orphan_fixture_findings` DELIBERATELY, and the overlap is one
    line per unclaimed directory rather than a second census: that one answers
    "this FILE is planted by nothing", which is a symptom, and this one answers
    "this DIRECTORY belongs to no rule", which is the cause and the only half
    that can see an EMPTY unclaimed directory or say which namespace the name
    is under. Both are exit 2, so the extra line costs a reader nothing and
    saves them the inference.
    """
    if bases is None:
        bases = fixture_trees()
    if claimed is None:
        claimed = {str(rule["id"]) for rule in RULES} | engine_fixture_dirs()
    if namespace is ...:
        namespace = world_module().RULE_ID_NAMESPACE
    found: list[str] = []
    for kind, base in bases:
        try:
            here = str(base.relative_to(ROOT))
        except ValueError:
            here = f"quality/{kind}"
        if not base.is_dir():
            found.append(
                f"{here}/ is not a directory — the fixture tree the self-test plants "
                "from is gone, and every plan that reads from it would skip in silence"
            )
            continue
        for entry in sorted(base.iterdir()):
            name = entry.name
            if name in claimed:
                continue
            if not entry.is_dir():
                found.append(
                    f"{here}/{name}: a loose file at the top of the fixture tree — "
                    f"fixtures live in `{here}/<rule id>/` and nothing plants this"
                )
                continue
            prefix = name.rsplit("-", 1)[0] if "-" in name else None
            if prefix is not None and prefix != namespace:
                found.append(
                    f"{here}/{name}/: a fixture directory under the namespace "
                    f"{prefix!r}, which this tree has not claimed — {id_grammar(namespace)}"
                )
                continue
            found.append(
                f"{here}/{name}/: a fixture directory no rule claims — every "
                "directory here is one rule's id, and an unclaimed one is a plan that "
                "plants nothing or a rule that was renamed and left its fixtures behind"
            )
    return found


def local_ratchet_consistency() -> None:
    """A drawer ratchet names a PRODUCT app, never one inside the partition.

    THE DIRECTION IS THE POINT. The drawer exists so a product's own backlog
    has somewhere to stand; it is not a second dial on the template's. A class
    naming an app in `quality/partition.yaml`'s `platform_apps` would raise a
    TEMPLATE rule's ceiling from a file the template never reads and no fold
    ever shows a reviewer — the quietest way there is to widen a rule.
    """
    raw = LOCAL_DOC.get("ratchets")
    if not isinstance(raw, dict) or not raw:
        return
    if PLATFORM_APPS is None:
        RUN.broken.append(
            _PARTITION_PROBLEM
            + " — and the drawer's `ratchets:` cannot be judged either: which classes are "
            "the template's to move is exactly the question that file answers"
        )
        return
    platform = PLATFORM_APPS
    app_dirs = (
        {d.name for d in (ROOT / "apps").iterdir() if d.is_dir()}
        if (ROOT / "apps").is_dir()
        else set()
    )
    for rid, classes in raw.items():
        if not isinstance(classes, dict):
            continue
        for klass in classes:
            name = str(klass)
            # A CLASS IS `<app>` OR `<app>.<kind>` — rules 54 and 55 key theirs
            # the second way (`core.role-value`), so a check that only read the
            # whole string would let `core.role-value: 12` through and the
            # drawer would be raising a platform ceiling after all.
            app_part = name.split(".", 1)[0]
            if name in platform or app_part in platform:
                RUN.broken.append(
                    f"quality/local/rules.yaml: `ratchets:` rule {rid} records class {name!r}, "
                    f"whose app {app_part!r} is inside quality/partition.yaml's "
                    "`platform_apps`. The "
                    "drawer records a PRODUCT's backlog; a platform app's ceiling is the "
                    "template's to move, in a diff a reviewer reads. "
                    f"Record {name!r} in quality/rules.yaml, or record the class of the "
                    "product app whose findings these really are"
                )
            elif is_local_rule(str(rid)) and app_dirs and app_part not in app_dirs:
                # DRAWER RULES ONLY. A class on a TEMPLATE rule whose app is not
                # on the tree is refused outright by `_merge_local_ratchets`; a
                # drawer rule's own classes need not be apps at all, so the most
                # this can honestly be is a line in case it is a typo.
                RUN.notes.append(
                    f"quality/local/rules.yaml ratchet: rule {rid} class {name!r} is not an "
                    "app on this tree — legal on a rule of your own (a class need not be an "
                    "app), said out loud in case it is a typo for one"
                )


def local_plant_consistency() -> None:
    """A drawer rule's fixtures plant into a PRODUCT app, or `apps/example`.

    PLANT PORTABILITY. A canary is planted THROUGH THE REAL SCOPE, into
    the real tree — so a product rule whose canary plants into `apps/core` is a
    product writing a fixture into a template-owned app, and the next fold
    either loses it or conflicts on it. `apps/example` is the one platform app
    a product's plant may use: it is the worked example every clone carries and
    the template's own canaries already plant there, so a product with no app
    of its own yet still has somewhere to demonstrate from.
    """
    if not world_module().LOCAL_RULE_IDS:
        return
    if PLATFORM_APPS is None:
        RUN.broken.append(
            _PARTITION_PROBLEM
            + " — and a drawer rule's plant sites cannot be judged either: which apps the "
            "template owns is exactly the question that file answers"
        )
        return
    platform = PLATFORM_APPS
    allowed_platform = {"example"}
    for f in plan_forms([rule for rule in RULES if is_local_rule(str(rule["id"]))]):
        singular = "canary" if f.kind == "canaries" else "negative"
        target = str(f.form.get("plant_at") or "")
        parts = target.split("/")
        if len(parts) < 2 or parts[0] != "apps" or "{{" in parts[1]:
            continue
        app = parts[1]
        if app in platform and app not in allowed_platform:
            RUN.broken.append(
                f"rule {f.rid}: {singular} {f.form.get('fixture')} plants at {target}, "
                f"inside the platform app {app!r} (quality/partition.yaml "
                "`platform_apps`). A drawer rule plants into one of YOUR apps, or "
                "into apps/example — the template owns the rest, and a fixture a "
                "fold overwrites is a canary that stops firing without a diff "
                "(plant portability, ADR gate-5's drawer)"
            )


def plant_mode_findings(rules: list[dict]) -> list[str]:
    """Every plant in the plan speaks the closed `PLANT_MODES` vocabulary.

    An unknown mode is exit 2 here, before anything is planted, naming the rule,
    the fixture and the word — rather than a form that quietly behaved as
    whichever branch of `Plant.put` its misspelling fell into. The same for a
    form's `needs_shape:` against `NEEDS_SHAPES`: an unknown shape, one written
    on an extra file, or one on a `via: django` form (judged in a batch, where
    no single form's shape can be asked) is refused here, never ignored.
    """
    out: list[str] = []
    for rule in rules:
        rid = str(rule.get("id", "?"))
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for e in entry_forms(entry):
                    mode = e.get("mode")
                    if mode not in PLANT_MODES:
                        out.append(
                            f"rule {rid}: {'canary' if kind == 'canaries' else 'negative'} "
                            f"{e.get('fixture')} at {e.get('plant_at')} declares mode: {mode!r}, "
                            f"which is not one of {', '.join(PLANT_MODES)} — the plant vocabulary "
                            "is closed, and a word this engine cannot read is a plan it cannot run"
                        )
                noun = "canary" if kind == "canaries" else "negative"
                if "needs_shape" in entry and entry.get("needs_shape") not in NEEDS_SHAPES:
                    out.append(
                        f"rule {rid}: {noun} {entry.get('fixture')} declares needs_shape: "
                        f"{entry.get('needs_shape')!r}, which is not one of "
                        f"{', '.join(NEEDS_SHAPES)} — the shape vocabulary is closed, and a "
                        "shape this engine cannot judge is a form it cannot run"
                    )
                if "needs_shape" in entry and entry.get("via") == "django":
                    out.append(
                        f"rule {rid}: {noun} {entry.get('fixture')} declares needs_shape on a "
                        "`via: django` form — those are planted and judged in one batch, so no "
                        "single form's shape can be asked; the key would be read by nothing"
                    )
                for extra in entry.get("extra_files") or []:
                    if "needs_shape" in extra:
                        out.append(
                            f"rule {rid}: {noun} {entry.get('fixture')}'s extra file "
                            f"{extra.get('fixture')} declares needs_shape — the shape is a "
                            "property of the FORM, declared on the form, and a key an extra "
                            "file carries is read by nothing"
                        )
                # A CANARY NEVER DECLARES A SHAPE. The lowering `needs_shape`
                # buys is a form subtracted from the floor on a tree that is not
                # its shape; a canary so lowered is a red nobody asked for, and
                # the rule could go blind on every product while its line still
                # read `ok`. A shape-bound subject is a NEGATIVE's (rule 60's
                # skip clause) — a canary that needs one is a rule that needs a
                # second canary, not a quieter first one.
                if kind == "canaries" and "needs_shape" in entry:
                    out.append(
                        f"rule {rid}: canary {entry.get('fixture')} declares needs_shape — a "
                        "canary lowered on a shape is a rule that can go blind on that shape "
                        "with its line still reading ok; only a negative may declare the shape "
                        "it needs"
                    )
                # THE CLEAN TREE A FORM NEEDS is the same kind of declaration
                # and is held to the same three refusals: a closed word, on the
                # form and never on an extra file, and never on a batched form.
                # Unlike a shape it LOWERS nothing — a tree that is not clean is
                # could-not-look — so a canary may declare it.
                if "needs_clean_tree" in entry and (
                    entry.get("needs_clean_tree") not in NEEDS_CLEAN_TREES
                ):
                    out.append(
                        f"rule {rid}: {noun} {entry.get('fixture')} declares needs_clean_tree: "
                        f"{entry.get('needs_clean_tree')!r}, which is not one of "
                        f"{', '.join(NEEDS_CLEAN_TREES)} — the vocabulary is closed, and a "
                        "tree this engine cannot ask about is a form it cannot run"
                    )
                if "needs_clean_tree" in entry and entry.get("via") == "django":
                    out.append(
                        f"rule {rid}: {noun} {entry.get('fixture')} declares needs_clean_tree "
                        "on a `via: django` form — those are planted and judged in one batch, "
                        "so no single form can be held back; the key would be read by nothing"
                    )
                for extra in entry.get("extra_files") or []:
                    if "needs_clean_tree" in extra:
                        out.append(
                            f"rule {rid}: {noun} {entry.get('fixture')}'s extra file "
                            f"{extra.get('fixture')} declares needs_clean_tree — it is a "
                            "property of the FORM, declared on the form, and a key an extra "
                            "file carries is read by nothing"
                        )
    return out


from quality.engine.plants import (  # noqa: E402
    NEEDS_CLEAN_TREES,
    NEEDS_SHAPES,
    PLANT_MODES,
    require_blind_spot,
)
from quality.engine.selftest import _seam_canaries  # noqa: E402
from quality.engine.world import (  # noqa: E402
    _PARTITION_PROBLEM,
    DRAWER_RATCHET_CLASSES,
    ENGINE_FIXTURES,
    GATE5_CITE,
    LOCAL_DOC,
    NEGATIVE_DIR,
    OPTIONAL_APPS,
    PLATFORM_APPS,
    RULES,
    RUN,
    SCOPE_KINDS,
    SEAM,
    fixture_home,
    fixture_trees,
    frozen_classes,
    id_grammar,
    is_frozen,
    is_local_rule,
    ratchet_home,
    world_module,
)
