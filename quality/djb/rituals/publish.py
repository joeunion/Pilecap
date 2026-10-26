"""The publish: the template exported as a product inherits it — censused, verified, released."""

# Invariant: publication is a census by rule over `git ls-files`, never a hand list of paths.
# does-not-cover: an untracked load-bearing file — the census reads TRACKED paths only.
# does-not-cover: a skeleton's content quality — present and marked is all that is proven.
# does-not-cover: truth — `adr-census` and `dangling-docs` prove resolvability, never meaning.
# does-not-cover: the gate on the artifact — the fresh-clone drive runs it; nothing grades itself.
# does-not-cover: `scripts/archaeology_lib.sh`'s bucket rules and scan — run by subprocess.
# does-not-cover: `adr-census` is `scripts/docs_legs.sh::docs_adr_census`, run by subprocess.

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apps.core.roads import road
from quality.could_not_look import CouldNotLook
from quality.djb import ledger
from quality.djb.legs import dangling_docs as docs_legs
from quality.ratchet_debt import debts_at, machine_line, read_machine_line

#: The checkout this ritual publishes when run as the module: the one it lives in.
ROOT = Path(__file__).resolve().parents[3]
#: The R7 population: the product's own state, inherited as a skeleton and never as this record.
LEDGERS = (
    "north-star",
    "queue",
    "queue-detail",
    "readouts",
    "misses",
    "in-flight",
    "goal-posts",
    "design-agreements",
    "pilot-readiness",
    "rep-day",
    "threat-model",
)
MARKER = "<!-- worked example — replace with your product's first real entry -->"
#: R10: the committed skeletons, `<ledger>.md` each, consumed at export and never shipped.
SKELETONS = "docs/product/skeletons"
RESERVED_DESC = "**/local/**, *.local.md, or apps/conftest_local.py"
STAMP = ".publish-artifact"
#: The five-lens re-read reports a minor release looks for its candidate tree in.
REREADS = "docs/product/reports/*/critique-*-reread.md"
CRITIQUE_BRIEF = ".claude/skills/product-manager/references/critique-brief.md"
#: The files a version is written in; the identity masks it there and nowhere else.
VERSION_HOMES = ("TEMPLATE_VERSION", "pyproject.toml", "uv.lock", "CHANGELOG.md")
#: A hex token in a re-read's header: an identity is named by a prefix of seven or more.
TREE_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
RELEASE_NUMBERS = re.compile(r"(\d+)\.(\d+)\.(\d+)")
VERSION_SHAPE = re.compile(r"[0-9].*\.[0-9].*\.[0-9].*", re.DOTALL)
RELEASE_TAG_GLOB = "v[0-9]*.[0-9]*.[0-9]*"
LIBRARIES = ". scripts/archaeology_lib.sh || exit 2\n. scripts/docs_legs.sh || exit 2\n"
#: Every tracked path with the rule ids it matches, and every rule id with its bucket.
CENSUS_SH = (
    "for r in $(archaeology_rule_ids); do"
    ' printf "RULE\\t%s\\t%s\\n" "$r" "$(bucket_for_rule "$r")"; done\n'
    'git ls-files -z | while IFS= read -r -d "" p; do rules_for "$p" >/dev/null;'
    ' printf "PATH\\t%s\\t%s\\n" "$RULES_FOR" "$p"; done\n'
)
USAGE = (
    "publish.sh takes nothing, --census, --to <dir>, or --release <dir> (which runs"
    " ./scripts/check.sh --leg supply-chain on the source before its release commit)"
)
SUPPLY_CHAIN = ("./scripts/check.sh", "--leg", "supply-chain")
#: The proof a tag's tree carries before the tag exists (architecture.md, beside ADR gate-3).
PROOF_FLOW = ".github/workflows/proof-from-zero.yml"
PROOF_POLL_S, PROOF_POLLS = 10, 30
PIP_ROW = re.compile(r"^(\S+)\s+(\S+)\s+((?:GHSA|PYSEC|CVE)-[\w-]+)\s*(\S*)\s*$")
PNPM_ROW = re.compile(
    r"^\s+(?:info|low|moderate|high|critical)\s+(\S+)\s+\(vulnerable ([^)]*)\).*?"
    r"(GHSA-[\w-]+)"
)


class Refused(CouldNotLook):
    """Exit 2: its lines go to stderr as given, the first already carrying its `!!`."""

    def __init__(self, *lines: str) -> None:
        super().__init__(lines[0] if lines else "refused")
        self.lines = lines


class Printed(CouldNotLook):
    """Exit 2 whose sentences are already on stderr."""


def out(text: str = "") -> None:
    """One line on stdout, flushed before any child writes beside it."""
    print(text, flush=True)


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def indent(text: str, by: int = 5) -> list[str]:
    """`sed 's/^/     /'` over every line of `text`."""
    return [" " * by + line for line in text.splitlines()]


def git(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `cwd`, both streams captured."""
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)


def git_ok(*argv: str, cwd: Path | None = None) -> str | None:
    """`git <argv>`'s stdout without its trailing newline, or None when it exits non-zero."""
    done = git(*argv, cwd=cwd)
    return done.stdout.rstrip("\n") if done.returncode == 0 else None


def passthrough(argv: Sequence[str], cwd: Path | None = None) -> int:
    """`argv` on this process's streams, its exit returned."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        return subprocess.run(list(argv), cwd=cwd, check=False).returncode
    except OSError:
        return 127


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI: the exit status is the verdict."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        raise Refused(
            "!! publish.sh refuses pipes — run it bare or redirect to a file.",
            "   The exit status is the verdict, and a filter replaces it.",
        )


def tree_dirt(directory: Path) -> str:
    """`git status --porcelain` of the checkout at `directory`, empty when clean."""
    return git("status", "--porcelain", cwd=directory).stdout.rstrip("\n")


def release_tags(directory: Path) -> list[str]:
    """The release tags `directory` carries, newest first; the shape is the one recogniser."""
    done = git("-C", str(directory), "tag", "--list", "--sort=-v:refname", RELEASE_TAG_GLOB)
    return [t for t in done.stdout.splitlines() if t] if done.returncode == 0 else []


def is_repo_root(directory: Path) -> bool:
    """A repository ROOT, never a path inside one: git walks upwards otherwise."""
    return (directory / ".git").exists() and git(
        "-C", str(directory), "rev-parse", "--git-dir"
    ).returncode == 0


def c_sorted(paths: Sequence[str]) -> list[str]:
    """`LC_ALL=C sort`: byte order."""
    return sorted(paths, key=lambda p: p.encode())


def reserved(path: str) -> bool:
    """R0: a tracked path claiming a drawer name the product owns and the template never ships."""
    return (
        path.startswith("local/")
        or "/local/" in path
        or path.endswith(".local.md")
        or path == "apps/conftest_local.py"
    )


def library(root: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """`script` under bash, `root`'s two shell libraries sourced; stdout captured, stderr ours."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(
        ["bash", "-c", f"set -uo pipefail\n{LIBRARIES}{script}", "publish", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )


@dataclass
class Census:
    """Every tracked path in exactly one bucket, and the rule table it was placed by."""

    rules: list[tuple[str, str]] = field(default_factory=list)
    placed: dict[str, list[str]] = field(default_factory=dict)
    ship: list[str] = field(default_factory=list)
    trim: list[str] = field(default_factory=list)
    skeleton: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    total: int = 0


def census(root: Path) -> Census:
    """`rules_for` over `git ls-files`, by subprocess; `Printed` when the library could not run."""
    done = library(root, CENSUS_SH)
    if done.returncode != 0:
        raise Printed(f"the census library exited {done.returncode}")
    result = Census()
    buckets: dict[str, str] = {}
    lists = {
        "SHIP": result.ship,
        "TRIM": result.trim,
        "SKELETON": result.skeleton,
        "SKELETON-SOURCE": result.source,
    }
    for row in done.stdout.splitlines():
        kind, _, rest = row.partition("\t")
        if kind == "RULE":
            rule, _, bucket = rest.partition("\t")
            result.rules.append((rule, bucket))
            buckets[rule] = bucket
            continue
        hits_text, _, path = rest.partition("\t")
        hits = hits_text.split()
        result.total += 1
        if not hits:
            result.unplaced.append(f"unplaced      {path}")
            continue
        if len(hits) > 1:
            result.unplaced.append(f"placed twice  {path}  ({hits_text})")
            continue
        result.placed.setdefault(hits[0], []).append(path)
        target = lists.get(buckets.get(hits[0], ""))
        if target is not None:
            target.append(path)
    return result


def hash_objects(cwd: Path, paths: Sequence[Path]) -> list[str]:
    """`git hash-object` of each path from `cwd`, `missing` for a path that is not a file."""
    present = [p for p in paths if p.is_file()]
    done = subprocess.run(
        ["git", "hash-object", "--stdin-paths"],
        cwd=cwd,
        input="".join(f"{p}\n" for p in present),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise Refused(f"!! git hash-object could not read the files: {done.stderr.strip()}")
    hashes = iter(done.stdout.split())
    return [next(hashes) if p.is_file() else "missing" for p in paths]


FLAG = re.compile(r"--[a-z][a-z0-9-]+")
SCRIPT = re.compile(r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.sh")
COMMAND = re.compile(r"manage\.py +([a-z_]+)")
EXECS = re.compile(r'^exec .* -m ([A-Za-z_][A-Za-z0-9_.]*) "\$@"$', re.MULTILINE)


@dataclass
class Flags:
    """The release section's flag claims: the findings, the claims judged, the spans unjudged."""

    findings: list[str] = field(default_factory=list)
    claims: int = 0
    unresolved: int = 0


def section(text: str, version: str) -> list[str]:
    """The lines under `## [<version>]` up to the next `## [`; the header matched as a literal."""
    lines: list[str] = []
    on = False
    for line in text.split("\n")[: -1 if text.endswith("\n") else None]:
        if line.startswith(f"## [{version}]"):
            on = True
        elif on and line.startswith("## ["):
            break
        elif on:
            lines.append(line)
    return lines


def claim_rows(lines: list[str]) -> list[tuple[str, str, str, str]] | None:
    """One (kind, name, flag, span) per flag in every backticked span; None when unbalanced."""
    parts = "".join(f"{line}\n" for line in lines).split("`")
    if len(parts) % 2 == 0:
        return None
    rows: set[tuple[str, str, str, str]] = set()
    for raw in parts[1::2]:
        span = re.sub(r"[ \t\n]+", " ", raw).removeprefix(" ").removesuffix(" ")
        flags = FLAG.findall(span)
        if not flags:
            continue
        kind, name = "UNRESOLVED", "-"
        if script := SCRIPT.search(span):
            kind, name = "SCRIPT", script.group(0)
        elif command := COMMAND.search(span):
            kind, name = "CMD", command.group(1)
        rows.update((kind, name, flag, span) for flag in flags)
    return sorted(rows, key=lambda row: "\t".join(row).encode())


def literal_in(flag: str, path: Path) -> bool:
    """`grep -qF -- <flag> <path>`."""
    return flag.encode() in path.read_bytes()


def changelog_flags(root: Path, version: str, noun: str = "the artifact") -> Flags:
    """Each `<script> --flag` span of the `[version]` section judged against the script it names."""
    try:
        text = (root / "CHANGELOG.md").read_text(errors="replace")
    except OSError:
        raise Refused(
            f"!! changelog-flags: there is no readable CHANGELOG.md in {noun}",
            "   — the release's own reading material. Could-not-look, not a violation.",
        ) from None
    lines = section(text, version)
    if not lines:
        raise Refused(
            f"!! changelog-flags: {noun}'s CHANGELOG.md has no `## [{version}]` section",
            "   to read, so this leg looked at nothing. Could-not-look, not a violation —",
            "   an absent section is the `changelog` leg's finding, not this one's.",
        )
    rows = claim_rows(lines)
    if rows is None:
        raise Refused(
            f"!! changelog-flags: `## [{version}]` in {noun} has an ODD number of",
            "   backticks, so every code span after the break is mis-paired and this leg",
            "   would be reading prose as commands. Could-not-look, not a violation.",
        )
    flags = Flags()
    unjudged: set[str] = set()
    for kind, name, flag, span in rows:
        if kind == "SCRIPT":
            rel = name.removeprefix("./")
            if not rel.startswith(("scripts/", "deploy/")):
                unjudged.add(span)
                continue
            if not (root / rel).is_file():
                raise Refused(
                    f"!! changelog-flags: `## [{version}]` names {rel}, which is not in {noun}",
                    "   — the leg cannot read the script the claim is about. Could-not-look,",
                    "   not a violation.",
                )
            flags.claims += 1
            readers = [rel]
            if rel == "scripts/check.sh":
                if (root / "quality/djb/gate_args.py").is_file():
                    readers = ["quality/djb/gate_args.py"]
            elif execs := EXECS.search((root / rel).read_text(errors="replace")):
                module = execs.group(1).replace(".", "/") + ".py"
                if not (root / module).is_file():
                    raise Refused(
                        f"!! changelog-flags: {rel} execs {module}, which is not in {noun}",
                        "   — the leg cannot read the module the wrapper hands its flags to.",
                        "   Could-not-look, not a violation.",
                    )
                readers.append(module)
            if not any(literal_in(flag, root / reader) for reader in readers):
                flags.findings.append(
                    f"changelog-flags: {flag} is not a literal in {' nor in '.join(readers)}"
                    f" — claimed in `{span}`"
                )
        elif kind == "CMD":
            hits = sorted(
                p for p in root.glob(f"apps/*/management/commands/{name}.py") if p.is_file()
            )
            if not hits:
                unjudged.add(span)
                continue
            flags.claims += 1
            if not literal_in(flag, hits[0]):
                flags.findings.append(
                    f"changelog-flags: {flag} is not a literal in"
                    f" {hits[0].relative_to(root).as_posix()} — claimed in `{span}`"
                )
        else:
            unjudged.add(span)
    flags.unresolved = len(unjudged)
    return flags


@dataclass
class Args:
    """The command line: the mode, the scratch target and the published clone."""

    mode: str = "full"
    target: str = ""
    pub: str = ""


def parse(argv: Sequence[str]) -> Args:
    """Strict: a mistyped flag is exit 2, never a quietly different run."""
    args = Args()
    want_census = want_release = False
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--census":
            args.mode = "census"
            want_census = True
        elif word == "--to":
            if not rest:
                raise Refused("!! --to needs a directory")
            args.target = rest.pop(0)
        elif word == "--release":
            if not rest:
                raise Refused("!! --release needs the published repository's directory")
            args.mode = "release"
            want_release = True
            args.pub = rest.pop(0)
        else:
            raise Refused(f"!! unknown argument '{word}': {USAGE}")
    if want_census and want_release:
        raise Refused(
            "!! --census and --release are opposites: one exports nothing, the other",
            "   commits what was exported. Pick one.",
        )
    if args.mode == "census" and args.target:
        raise Refused("!! --census takes no target: it exports nothing")
    return args


def advisories(text: str) -> list[str]:
    """`<package> <version> <id> — fixed in <version>` per advisory row the leg printed."""
    found: list[str] = []
    for line in text.splitlines():
        if m := PIP_ROW.match(line.strip()):
            name, version, ident, fix = m.groups()
            said = f"fixed in {fix}" if fix else "no fixed version is published"
            found.append(f"{name} {version} {ident} — {said}")
        elif m := PNPM_ROW.match(line):
            module, vulnerable, ident = m.groups()
            found.append(f"{module} {ident} — fixed outside {vulnerable}")
    return found


#: The baseline's content excuses: a line pattern, and a secret value anchored as a token.
EXCUSE_FILES = "detect_secrets.filters.regex.should_exclude_file"
EXCUSE_LINES = "detect_secrets.filters.regex.should_exclude_line"
EXCUSE_VALUES = "detect_secrets.filters.regex.should_exclude_secret"


def _excuse_reader(kind: str, pattern: str) -> re.Pattern[str]:
    """The pattern as the scan applies it: a secret excuse matches a whole token."""
    if kind == EXCUSE_VALUES:
        return re.compile(rf"(?<!\w){pattern.removeprefix('^').removesuffix('$')}(?!\w)")
    return re.compile(pattern)


def drop_dead_excuses(baseline: dict[str, Any], root: Path, ships: Sequence[str]) -> int:
    """Drop each line or secret excuse no shipped, scanned file has a line for; the count."""
    used = baseline.get("filters_used") or []
    excluded = [
        re.compile(p) for f in used if f.get("path") == EXCUSE_FILES for p in f.get("pattern", [])
    ]
    texts: list[str] = []
    for rel in ships:
        if rel == ".secrets.baseline" or any(x.search(rel) for x in excluded):
            continue
        try:
            texts.append((root / rel).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
    dropped = 0
    for entry in used:
        kind = entry.get("path")
        if kind not in (EXCUSE_LINES, EXCUSE_VALUES):
            continue
        live = [
            p
            for p in entry.get("pattern", [])
            if any(_excuse_reader(kind, p).search(t) for t in texts)
        ]
        dropped += len(entry.get("pattern", [])) - len(live)
        entry["pattern"] = live
    return dropped


def mask_version(rel: str, text: str, version: str) -> str:
    """`text` with `version` replaced by `<version>` where `rel` writes it as the release's own."""
    v, mask = re.escape(version), "<version>"
    if rel == "TEMPLATE_VERSION":
        return f"{mask}\n" if text.strip() == version else text
    if rel in ("pyproject.toml", "uv.lock"):
        return re.sub(rf'^(name = "[^"]+"\nversion = )"{v}"$', rf'\1"{mask}"', text, flags=re.M)
    if rel == "CHANGELOG.md":
        text = re.sub(rf"^## \[{v}\]", f"## [{mask}]", text, flags=re.M)
        return re.sub(rf"^\[{v}\]: .*$", f"[{mask}]: <link>", text, flags=re.M)
    return text


def export_identity(root: Path, version: str) -> str:
    """The export's tracked files hashed, version homes masked: a cut and its release agree."""
    listed = git("-C", str(root), "ls-files", "-z").stdout.split("\0")
    digest = hashlib.sha256()
    for rel in sorted(p for p in listed if p):
        path = root / rel
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        if rel in VERSION_HOMES:
            data = mask_version(rel, data.decode("utf-8", "replace"), version).encode()
        digest.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()[:40]


def release_kind(before: str, version: str) -> str:
    """`minor` (a major counts as one), `patch`, or `pre-release` when the numbers are equal."""
    then, now = RELEASE_NUMBERS.match(before), RELEASE_NUMBERS.match(version)
    if then is None or now is None:
        return "minor"
    if then.groups()[:2] != now.groups()[:2]:
        return "minor"
    return "patch" if then.group(3) != now.group(3) else "pre-release"


def debt_step(remaining: int, kind: str) -> int:
    """The fall a release owes: max(5 % of the remaining sum, 2,000) per minor, one per patch."""
    if kind == "minor":
        need = max(-(-remaining * 5 // 100), 2000)
    else:
        need = 1 if kind == "patch" else 0
    return min(need, remaining)


def critique_rereads(root: Path, identity: str) -> list[str]:
    """The re-read reports whose header (the lines before its first `## `) names `identity`."""
    named: list[str] = []
    for path in sorted(root.glob(REREADS)):
        head: list[str] = []
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith("## "):
                break
            head.append(line)
        tokens = TREE_TOKEN.findall("\n".join(head))
        if identity and any(identity.startswith(t) for t in tokens):
            named.append(path.relative_to(root).as_posix())
    return named


class Publish:
    """One run: the census, the export, the verification legs, the release commit, the verdict."""

    def __init__(self, root: Path, args: Args) -> None:
        self.root = root
        self.args = args
        self.mode = args.mode
        self.steps = 7 if self.mode == "release" else 5
        self.violations = 0
        self.step_name = ""
        self.step_start = 0.0
        self.version = ""
        self.tag = ""
        self.src_sha = ""
        self.pub = Path()
        self.pub_tip = ""
        self.pub_branch = ""
        self.last_tag = ""
        self.identity = ""
        self.target = Path()
        self.tree = ""
        self.new = ""
        self.census = Census()
        self.section_present = False
        self.expected: list[str] = []

    # --- the printing -----------------------------------------------------------------------

    def step(self, name: str) -> None:
        """`steps.sh::step`: the previous step's wall, then `== <name>`."""
        if self.step_name:
            out(f"  ({self.step_name}: {time.monotonic() - self.step_start:.2f}s)")
        out()
        out(f"== {name}")
        self.step_name = name
        self.step_start = time.monotonic()

    def violation(self, text: str) -> None:
        """One content finding: counted, and printed under its `VIOLATION` tag."""
        self.violations += 1
        out(f"   VIOLATION  {text}")

    # --- the run ----------------------------------------------------------------------------

    def run(self) -> int:
        """Every step in order; the exit is the verdict."""
        self.source()
        out(f"== publish · {self.root}")
        out(f"   source     {git_ok('log', '-1', '--format=%h  %s', 'HEAD', cwd=self.root)}")
        if self.mode == "release":
            self.refuse_a_product()
            self.preflight()
        self.step(f"step 1/{self.steps} · the census — every tracked path in exactly one bucket")
        self.take_census()
        expected = c_sorted(self.census.ship + [f"docs/product/{n}.md" for n in LEDGERS])
        self.expected = expected
        if self.mode == "census":
            out()
            out(f"== CENSUS ONLY · nothing was exported · {len(expected)} paths would ship")
            return 0
        self.step(
            f"step 2/{self.steps} · export — the ship-set into a fresh init, no platform history"
        )
        self.export()
        self.step(
            f"step 3/{self.steps} · leg file-set — the artifact is exactly the census's ship-set"
        )
        self.file_set(expected)
        self.step(f"step 4/{self.steps} · the verification legs, against the ARTIFACT")
        self.byte_identity()
        self.adr_census()
        self.dangling_docs()
        self.current_state()
        self.archaeology()
        self.secrets()
        self.sdk()
        if self.mode == "release":
            self.changelog()
            self.changelog_flags()
            self.ratchets()
            self.critique()
            self.step(f"step 5/{self.steps} · the supply chain — {' '.join(SUPPLY_CHAIN)}")
            self.supply_chain()
            self.step(
                f"step 6/{self.steps} · the release commit — "
                "one squashed child of the published tip"
            )
            self.proof()
            self.release_commit()
        return self.verdict()

    def source(self) -> None:
        """The source is a clean commit, and its version reads as `<major>.<minor>.<patch>`."""
        if git("rev-parse", "--git-dir", cwd=self.root).returncode != 0:
            raise Refused("!! not a git checkout — the census reads git and nothing else")
        sha = git_ok("rev-parse", "HEAD", cwd=self.root)
        if sha is None:
            raise Refused("!! HEAD does not resolve — publish measures a commit")
        self.src_sha = sha
        dirt = tree_dirt(self.root)
        if dirt:
            raise Refused(
                "!! the working tree is dirty — publish measures a COMMIT, not a tree.",
                "   The idempotence claim (two runs, one exported tree hash) is only",
                "   falsifiable against a source anyone else can re-derive. Commit first.",
                *indent(dirt),
            )
        try:
            raw = (self.root / "TEMPLATE_VERSION").read_text()
        except OSError:
            raw = ""
        self.version = "".join(raw.split())
        if not VERSION_SHAPE.fullmatch(self.version):
            raise Refused(
                "!! TEMPLATE_VERSION does not read as <major>.<minor>.<patch>:",
                f'   "{self.version}" — the release tag is derived from it and a',
                "   derivation that cannot be read is a could-not-look, never a default.",
            )
        self.tag = f"v{self.version}"

    def refuse_a_product(self) -> None:
        """Release mode on a tree declaring a namespace: the ritual is the template's, refused."""
        from quality.djb import boundary

        drawer = self.root / boundary.DRAWER
        namespace = boundary.namespace_in(drawer.read_text() if drawer.is_file() else None)
        if namespace is None:
            return
        raise Refused(
            "!! --release is the template's own release ritual; this tree is the product "
            f"{namespace}.",
            f"   It waits on the template's proof from zero ({PROOF_FLOW}, which R14 trims",
            "   from every product) and on the five-lens re-reads under docs/product/reports/",
            "   (R8 trims them too) — docs/product/publication-manifest.md, R14 and R8.",
            "   A product's release road is deploy/release.sh. Nothing was exported or committed.",
        )

    def preflight(self) -> None:
        """Every refusal about the PUBLISHED repository, before anything is exported."""
        pub = Path(self.args.pub)
        self.pub = pub if pub.is_absolute() else self.root / pub
        p = str(self.pub)
        if not self.pub.is_dir():
            raise Refused(
                f"!! --release names no directory: {p}",
                "   It must be a CLONE of the published repository — the release commit is",
                "   a child of its tip.",
            )
        if git("-C", p, "rev-parse", "--git-dir").returncode != 0:
            raise Refused(f"!! --release target is not a git checkout: {p}")
        if git_ok("-C", p, "rev-parse", "--is-bare-repository") == "true":
            raise Refused(
                f"!! --release target is a BARE repository: {p}",
                "   The release lands on a branch and its working tree is left holding the",
                "   released content, so a bare clone has nowhere to put it.",
            )
        top = git_ok("-C", p, "rev-parse", "--show-toplevel") or ""
        if top != str(self.pub.resolve()):
            raise Refused(
                f"!! --release target is inside a checkout but is not its root: {p}",
                f"   sits under {top}.",
                "   git walks upwards, so releasing here would move a branch in a",
                "   repository nobody pointed this at.",
            )
        branch = git_ok("-C", p, "symbolic-ref", "-q", "--short", "HEAD")
        if branch is None:
            raise Refused(
                f"!! --release target has a detached HEAD: {p}",
                "   A release moves a branch. Check out the published branch first.",
            )
        self.pub_branch = branch
        dirt = tree_dirt(self.pub)
        if dirt:
            raise Refused(
                f"!! the --release target's working tree is dirty: {p}",
                "   The release commit REPLACES that tree with the exported one, so anything",
                "   uncommitted there is work this script would destroy. Nothing was touched.",
                *indent(dirt),
            )
        tip = git_ok("-C", p, "rev-parse", "HEAD")
        if tip is None:
            raise Refused(
                f"!! the --release target has no commits: {p}",
                "   A release is a CHILD of the published tip; there is no tip here.",
            )
        self.pub_tip = tip
        if git_ok("-C", p, "cat-file", "-t", tip) != "commit":
            raise Refused(f"!! the --release target's HEAD does not resolve to a commit: {tip}")
        tags = release_tags(self.pub)
        if not tags:
            raise Refused(
                f"!! the --release target carries no release tag at all: {p}",
                "   This mode's whole safety is that it builds on a KNOWN published release,",
                "   and with no tag there is nothing to compare the tip against — a guess",
                "   about what is already out there is the one thing this refuses to make.",
                "   If that tip IS a release, say so once and re-run:",
                f"     git -C {p} tag -a v<its version> -m 'v<its version>' {tip}",
            )
        self.last_tag = tags[0]
        last_sha = git_ok("-C", p, "rev-list", "-n", "1", tags[0]) or ""
        if last_sha != tip:
            raise Refused(
                "!! the --release target's tip is NOT its last release.",
                f"   tip                    {tip}",
                f"   last release           {last_sha}  ({tags[0]})",
                "   Somebody committed onto the published branch by hand, or the clone is",
                "   behind its remote. One squashed release commit per publish is the whole",
                "   contract; a release built on an unreleased tip would bury that commit",
                "   inside a release nobody can name. Fetch, or reconcile that commit first.",
            )
        if git("-C", p, "rev-parse", "-q", "--verify", f"refs/tags/{self.tag}").returncode == 0:
            raise Refused(
                f"!! {self.tag} already exists in {p}",
                "   A version is published once. Either this drop is already out, or",
                "   TEMPLATE_VERSION was not bumped for it — bump TEMPLATE_VERSION and give",
                "   CHANGELOG.md the matching section, then re-run. Retagging a released",
                "   version silently changes what a consumer already merged.",
            )
        out(f"   released   {p}")
        out(f"   branch     {self.pub_branch}")
        out(f"   tip        {tip}  ({tags[0]})")
        out(f"   releasing  {self.tag}")

    # --- step 1 -----------------------------------------------------------------------------

    def take_census(self) -> None:
        """R0 first, then every tracked path in one bucket, then the skeleton derivation."""
        tracked = git("ls-files", "-z", cwd=self.root).stdout.split("\0")
        hits = [p for p in tracked if p and reserved(p)]
        if hits:
            out("   R0   RESERVED         refused")
            out()
            raise Refused(
                "!! R0 · A RESERVED PATH IS TRACKED IN THIS TREE. The drawers belong to the",
                "   PRODUCT and the template never ships one — that is what lets a product",
                "   extend the system layer without a merge conflict, and it holds only for",
                f"   as long as no release claims the name. Reserved: {RESERVED_DESC}.",
                *(f"     {h}" for h in hits),
                "   Move it to a path the template owns, or stop tracking it. A release",
                "   cannot be re-cut, so a drawer that ships once is in every consumer's",
                "   history. Enforcement broken, not a violation.",
            )
        out(f"   R0   reserved        none tracked ({RESERVED_DESC})")
        found = census(self.root)
        self.census = found
        if found.total == 0:
            raise Refused(
                "!! the census saw no tracked files at all — this reader is looking at the",
                "   wrong tree, and that is a could-not-look, never an empty ship-list.",
            )
        for rule, bucket in found.rules:
            out(f"   {rule:<4} {bucket:<16} {len(found.placed.get(rule, [])):5d}")
        out("   ----------------------------------")
        for label, members in (
            ("SHIP", found.ship),
            ("SKELETON", found.skeleton),
            ("TRIM", found.trim),
            ("SKELETON-SOURCE", found.source),
        ):
            out(f"   {label:<21} {len(members):5d}")
        out(f"   {'tracked total':<21} {found.total:5d}")
        if found.unplaced:
            out()
            raise Refused(
                "!! THE CENSUS CANNOT PLACE EVERY TRACKED PATH. A file class this manifest",
                "   does not know about must fail loudly here — shipping it by accident and",
                "   trimming it silently are the same defect wearing different clothes.",
                "   Decide its bucket in docs/product/publication-manifest.md, then add the",
                "   rule to rules_for() above.",
                *(f"     {u}" for u in found.unplaced),
            )
        out("   every tracked path landed in exactly one bucket")
        self.skeletons()

    def skeletons(self) -> None:
        """Every R7 ledger substituted from a committed skeleton or already marked; no orphans."""
        out()
        out("   ledgers (R7) — substituted from docs/product/skeletons/, or already skeletal:")
        missing = 0
        for name in LEDGERS:
            live = f"docs/product/{name}.md"
            src = f"{SKELETONS}/{name}.md"
            if (self.root / src).is_file():
                out(f"     {name:<24} substituted from {src}")
                continue
            try:
                marked = MARKER in (self.root / live).read_text(errors="replace")
            except OSError:
                marked = False
            if marked:
                out(f"     {name:<24} already skeletal (carries the marker)")
            else:
                err(
                    f"     {name:<24} NEITHER: no {src}, and {live} carries no worked-example"
                    " marker"
                )
                missing += 1
        for path in self.census.source:
            base = path.rsplit("/", 1)[-1].removesuffix(".md")
            if base not in LEDGERS:
                err(f"     ORPHAN SKELETON: {path} names no ledger in the R7 population")
                missing += 1
        if missing:
            raise Refused(
                "!! the skeleton derivation does not close. Every R7 ledger is either",
                "   substituted from a committed skeleton or already carries the marker;",
                "   anything else would publish this platform's own state as a product's.",
            )

    # --- step 2 -----------------------------------------------------------------------------

    def default_target(self) -> Path:
        """Derived from the checkout, as `db.sh` derives a database name: no two collide."""
        digest = hashlib.sha256(str(self.root).encode()).hexdigest()[:8]
        branch = git_ok("rev-parse", "--abbrev-ref", "HEAD", cwd=self.root) or ""
        slug = re.sub(r"[^a-zA-Z0-9]", "-", f"{branch}\n")
        return Path(os.environ.get("TMPDIR") or "/tmp") / f"djb-publish-{slug}-{digest}"  # noqa: S108 — the TMPDIR fallback the shell rituals use too

    def export(self) -> None:
        """The ship-set into a fresh init: archive, trim, substitute, stamp, one commit, clean."""
        target = Path(self.args.target) if self.args.target else self.default_target()
        self.target = target if target.is_absolute() else self.root / target
        t = str(self.target)
        out(f"   target     {t}")
        if self.target.is_dir() and is_repo_root(self.target) and release_tags(self.target):
            raise Refused(
                "!! THE ROOT RE-CUT DOOR IS CLOSED, and this target is what closed it.",
                f"   {t} carries release tags, so it is the published repository — and a",
                "   published release is something a product has merged. Re-cutting the root",
                "   here would destroy the merge base every consumer shares with us: their",
                "   next pull would see the WHOLE template as new work and conflict with every",
                "   local patch they carry, which is the one cost the child-commit ruling of",
                "   2026-08-30 exists to make impossible.",
                "   Releases are forward commits from here on:",
                f"     ./scripts/publish.sh --release {t}",
                "   builds one squashed child of the published tip and tags it. The scratch",
                "   mode is untouched — a fresh or previously-stamped directory still exports",
                "   normally, which is how the verification drives run.",
            )
        if self.target.exists() or self.target.is_symlink():
            if not self.target.is_dir():
                raise Refused(f"!! target exists and is not a directory: {t}")
            if (self.target / STAMP).is_file():
                shutil.rmtree(self.target)
            elif not any(self.target.iterdir()):
                self.target.rmdir()
            else:
                raise Refused(
                    f"!! target is not empty and carries no {STAMP} stamp: {t}",
                    "   This script will not delete a directory it cannot prove it wrote.",
                )
        self.target.mkdir(parents=True, exist_ok=True)
        self.extract()
        for path in self.census.trim + self.census.source:
            (self.target / path).unlink(missing_ok=True)
        for name in LEDGERS:
            src = self.root / SKELETONS / f"{name}.md"
            if src.is_file():
                shutil.copyfile(src, self.target / "docs/product" / f"{name}.md")
        self.prune_empty()
        self.rederive_baseline()
        self.init_artifact()
        dirt = tree_dirt(self.target)
        if dirt:
            raise Refused(
                "!! the exported artifact's working tree is NOT clean. Everything the",
                "   census ships is committed and everything else is ignored — a third",
                "   state means the export left a file behind that its new owner would",
                "   inherit as unexplained dirt, and whose own publish.sh would then be",
                "   refused by the dirty-tree guard. Could-not-look, not a violation.",
                *indent(dirt),
            )
        self.tree = git_ok("-C", t, "rev-parse", "HEAD^{tree}") or ""
        self.identity = export_identity(self.target, self.version)
        files = git("-C", t, "ls-files").stdout.splitlines()
        out(f"   exported   {len(files)} files")
        out(f"   tree       {self.tree}")

    def rederive_baseline(self) -> None:
        """The artifact's `.secrets.baseline` over the artifact's own files: no entry for a trim."""
        path = self.target / ".secrets.baseline"
        if not path.is_file():
            return
        try:
            baseline = json.loads(path.read_text())
            results = baseline["results"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Refused(
                f"!! the artifact's .secrets.baseline does not read as a baseline: {exc}",
                "   A baseline this cannot read is a could-not-look, never a copy shipped unread.",
            ) from exc
        ships = set(self.expected)
        kept = {name: rows for name, rows in results.items() if name in ships}
        baseline["results"] = kept
        dead = drop_dead_excuses(baseline, self.target, sorted(ships))
        path.write_text(json.dumps(baseline, indent=2) + "\n")
        out(
            f"   baseline   .secrets.baseline over the artifact's own files"
            f" ({len(results) - len(kept)} entries for unshipped files dropped;"
            f" {dead} line/secret excuse(s) that excuse nothing shipped dropped)"
        )

    def extract(self) -> None:
        """`git archive` of the source commit unpacked into the target."""
        sys.stdout.flush()
        archive = subprocess.Popen(
            ["git", "archive", "--format=tar", self.src_sha], cwd=self.root, stdout=subprocess.PIPE
        )
        untar = subprocess.run(["tar", "-xf", "-"], cwd=self.target, stdin=archive.stdout)
        if archive.stdout is not None:
            archive.stdout.close()
        if archive.wait() != 0 or untar.returncode != 0:
            raise Refused(f"!! the export could not be unpacked into {self.target}")

    def prune_empty(self) -> None:
        """`find <target> -type d -empty -delete`: the directories the trim emptied."""
        for here, _dirs, _files in os.walk(self.target, topdown=False):
            path = Path(here)
            if path != self.target and not any(path.iterdir()):
                path.rmdir()

    def init_artifact(self) -> None:
        """One repository, one commit, the stamp on disk and ignored by `.git/info/exclude`."""
        (self.target / STAMP).write_text("")
        t = str(self.target)
        steps = (
            ["git", "init", "-q", "-b", "main"],
            [
                "git",
                "-c",
                "core.excludesFile=/dev/null",
                "add",
                "-f",
                "-A",
                "--",
                ".",
                f":(exclude){STAMP}",
            ],
            [
                "git",
                "-c",
                "user.name=publish",
                "-c",
                "user.email=publish@localhost",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                "Initial commit — Pilecap template",
                "--author=publish <publish@localhost>",
            ],
        )
        for number, argv in enumerate(steps):
            if passthrough(argv, cwd=self.target) != 0:
                raise Refused("!! the artifact repository could not be initialised — see above")
            if number == 0:
                info = Path(t) / ".git" / "info"
                info.mkdir(parents=True, exist_ok=True)
                with (info / "exclude").open("a") as handle:
                    handle.write(
                        f"# {STAMP} — written by scripts/publish.sh, which needs this file to\n"
                        "# recognise this directory as its own before rebuilding it.\n"
                        f"{STAMP}\n"
                    )

    # --- step 3 -----------------------------------------------------------------------------

    def file_set(self, expected: list[str]) -> None:
        """The artifact is exactly the census's ship-set, or the derivation is broken."""
        actual = c_sorted(git("-C", str(self.target), "ls-files").stdout.splitlines())
        if actual != expected:
            diff = difflib.unified_diff(expected, actual, "expected", "actual", lineterm="")
            raise Refused(
                "!! the artifact's file set is not the census's ship-set. The export and the",
                "   census disagree, which means one of them is not the derivation it claims",
                "   to be — a could-not-look, not a violation.",
                *(f"     {line}" for line in diff),
            )
        out(f"   ok — {len(expected)} paths, nothing added and nothing lost")

    # --- step 4 -----------------------------------------------------------------------------

    def byte_identity(self) -> None:
        """Invariant 1: everything the gate reads ships byte-identical."""
        out()
        out("-- byte-identity: quality/** and instruments.md ship verbatim")
        read = [
            p
            for p in self.census.ship
            if p.startswith("quality/") or p == "docs/product/instruments.md"
        ]
        if not read:
            raise Refused(
                "!! byte-identity had nothing to compare — the learning layer is not in the",
                "   ship-set at all, which is a broken derivation, not a clean run.",
            )
        source = hash_objects(self.root, [self.root / p for p in read])
        artifact = hash_objects(self.root, [self.target / p for p in read])
        bad = 0
        for path, a, b in zip(read, source, artifact, strict=True):
            if a != b:
                self.violation(f"byte-identity: {path}  source {a}  artifact {b}")
                bad += 1
        if not bad:
            out(f"   ok — {len(read)} gate-read files byte-identical to the source")

    def art_files(self, scratch: Path) -> Path:
        """The artifact's tracked files as a NUL list on disk: the set step 3 proved equal."""
        listing = scratch / "artfiles"
        listing.write_bytes(git("-C", str(self.target), "ls-files", "-z").stdout.encode())
        return listing

    def adr_census(self) -> None:
        """Invariant 2: every ADR id the artifact cites resolves to its file in the ADR log."""
        out()
        out("-- adr-census: every ADR id cited in the artifact resolves in the artifact")
        with tempfile.TemporaryDirectory(prefix="djb-publish-adr.") as scratch:
            here = Path(scratch)
            counts = here / "counts"
            done = library(
                self.root,
                'docs_adr_census "$1" "$2"; rc=$?\n'
                'printf "%s %s\\n" "$DOCS_ADR_SITES" "$DOCS_ADR_IDS" >"$3"; exit "$rc"',
                str(self.target),
                str(self.art_files(here)),
                str(counts),
            )
            if done.returncode == 2:
                raise Printed("adr-census could not look")
            bad = 0
            for line in done.stdout.splitlines():
                if line:
                    self.violation(line)
                    bad += 1
            sites, _, ids = counts.read_text().strip().partition(" ")
        out(f"   {sites} citation sites read · {ids} ids resolvable in the ADR directory")
        if not bad:
            out("   ok — no decision is lost at publish")

    def dangling_docs(self) -> None:
        """Invariant 2's sibling: every `docs/` pointer and repository path resolves in it."""
        out()
        out("-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it")
        files = git("-C", str(self.target), "ls-files", "-z").stdout.split("\0")
        try:
            scan = docs_legs.dangling_docs(
                self.target,
                files,
                "the artifact",
                self.census.trim + self.census.source,
                self.census.placed.get("R12", []),
            )
        except CouldNotLook as cannot:
            raise Refused(f"!! dangling-docs: {cannot}") from cannot
        for note in scan.notes:
            err(note)
        for line in scan.findings:
            self.violation(line)
        out(f"   {scan.sites} pointer sites read")
        if not scan.findings:
            out("   ok — every docs/ pointer in the artifact resolves inside it")

    def current_state(self) -> None:
        """ADR docs-1 over the ARTIFACT: its derived blocks are current, no page names the gone."""
        out()
        out("-- current-state: derived blocks current; no ledger id, trimmed path or passed future")
        for argv in (
            ["-m", "quality.docs_derived", "--root", str(self.target), "--check"],
            [str(ROOT / "scripts/current_state_census.py"), str(self.target), "--ship"],
        ):
            sys.stdout.flush()
            done = subprocess.run(
                [sys.executable, *argv],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                capture_output=True,
                text=True,
                check=False,
            )
            sys.stderr.write(done.stderr)
            if done.returncode == 2:
                raise Refused(f"!! current-state could not look: {' '.join(argv[:2])} exited 2")
            for line in done.stdout.splitlines():
                if done.returncode and line.strip() and not line.startswith("ok"):
                    self.violation(line.strip().removeprefix("VIOLATION").strip())
                elif line.strip():
                    out(f"   {line.strip()}")

    def archaeology(self) -> None:
        """Invariant 3: the platform's construction history is not in the product's tree."""
        out()
        out("-- archaeology-census: the platform's build history is not in the product's tree")
        read = len(self.census.ship)
        if not read:
            raise Refused(
                "!! archaeology-census had no ship-set to read. A tree nobody looked at is",
                "   not a clean tree — could-not-look, not a pass.",
            )
        done = library(self.root, 'archaeology_scan_tree "$1"', str(self.target))
        if done.returncode != 0:
            raise Printed("archaeology-census could not look")
        bad = 0
        for line in done.stdout.splitlines():
            if line:
                self.violation(line)
                bad += 1
        out(f"   {read} shipped files read · 6 violation classes")
        if not bad:
            out("   ok — no finding id, rung token, narrative instance, private name,")
            out("        former brand or deployment coordinate ships")

    def secrets(self) -> None:
        """Rule 23 over the ARTIFACT: the published tree is what a stranger clones."""
        out()
        out("-- secrets: detect-secrets over the WHOLE artifact vs its shipped baseline")
        own = self.root / ".venv/bin/detect-secrets-hook"
        hook = str(own) if os.access(own, os.X_OK) else shutil.which("detect-secrets-hook")
        if not hook:
            raise Refused(
                "!! detect-secrets-hook is not installed — the artifact was NOT scanned.",
                "   A tree nobody looked at is not a clean tree.",
                f"   Fix: run `uv sync` in {self.root} (it installs the hook into .venv/bin/),",
                "   then re-run this script.",
            )
        if not (self.target / ".secrets.baseline").is_file():
            raise Refused(
                "!! the artifact carries no .secrets.baseline — the scan has nothing to",
                "   compare against, and every finding would be new. Could-not-look.",
            )
        files = git("-C", str(self.target), "ls-files", "-z").stdout
        sys.stdout.flush()
        sys.stderr.flush()
        rc = subprocess.run(
            ["xargs", "-0", hook, "--baseline", ".secrets.baseline"],
            cwd=self.target,
            input=files,
            text=True,
            check=False,
        ).returncode
        if rc == 0:
            out("   ok — no unbaselined secret in the published tree")
        else:
            self.violation(f"secrets: detect-secrets exited {rc} over the artifact (output above)")

    def sdk(self) -> None:
        """The source's surface and `### SDK` are derived; the ARTIFACT's docs/sdk/ is current."""
        out()
        out("-- sdk: the surface and docs/sdk/ regenerate; the CHANGELOG's ### SDK is derived")
        if not (self.root / "quality/sdk_surface.json").is_file():
            out("   SKIPPED — this source carries no quality/sdk_surface.json")
            return
        from quality.djb.cli import fast_environ

        named = fast_environ(self.root)
        for argv in (
            ["--surface", "--check"],
            ["--changelog", "--check"],
            ["--reference", "--check"],
        ):
            sys.stdout.flush()
            rc = subprocess.run(
                [sys.executable, "-m", "quality.sdk", *argv],
                cwd=self.root,
                env={**named, "PYTHONPATH": str(self.root)},
                check=False,
            ).returncode
            if rc != 0:
                self.violation(f"sdk: python -m quality.sdk {' '.join(argv)} exited {rc} (above)")
        out(f"   the reference regenerated inside the artifact, {self.target}:")
        sys.stdout.flush()
        rc = subprocess.run(
            ["bash", "-c", '. scripts/db.sh >/dev/null && exec "$0" -m quality.sdk "$@"']
            + [sys.executable, "--reference", "--check"],
            cwd=self.target,
            env={**os.environ, "PYTHONPATH": str(self.target)},
            check=False,
        ).returncode
        if rc != 0:
            self.violation(
                f"sdk: the artifact's docs/sdk/ is STALE — python -m quality.sdk --reference "
                f"--check exited {rc} inside it (above); a product's loop would red on it"
            )

    def changelog(self) -> None:
        """Release mode: the artifact's CHANGELOG carries the section this tag names."""
        out()
        out("-- changelog: the artifact's CHANGELOG.md carries this release's section")
        try:
            art_version = "".join((self.target / "TEMPLATE_VERSION").read_text().split())
        except OSError:
            art_version = ""
        if art_version != self.version:
            raise Refused(
                "!! the artifact's TEMPLATE_VERSION is not the source's:",
                f'   source "{self.version}"  artifact "{art_version}"',
                "   R6 ships that file verbatim, so a disagreement means the export is not",
                "   the derivation it claims to be. Could-not-look, not a violation.",
            )
        try:
            lines = (self.target / "CHANGELOG.md").read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        header = re.compile(rf"^## \[{self.version}\]")
        if any(header.match(line) for line in lines):
            out(f"   ok — ## [{self.version}] is in the published CHANGELOG.md")
            self.section_present = True
        else:
            self.violation(
                f"changelog: the artifact's CHANGELOG.md has no `## [{self.version}]` section"
                f" — {self.tag} would ship with nothing to read"
            )

    def changelog_flags(self) -> None:
        """Release mode: every `<script> --flag` the section names is a literal in that script."""
        out()
        out("-- changelog-flags: every <script> --flag the release section names exists")
        if not self.section_present:
            out("   SKIPPED — there is no section to read, and the leg above is that finding.")
            return
        flags = changelog_flags(self.target, self.version)
        for line in flags.findings:
            self.violation(line)
        out(f"   {flags.claims} claim(s) checked · {flags.unresolved} unresolved flag spans")
        if not flags.findings:
            out("   ok — every flag the section names is a literal in the script it names")

    def ratchets(self) -> None:
        """Release mode: the `debt:` floors at the candidate fell from the last release's line."""
        out()
        out("-- ratchets: the recorded debt fell since the last release, by the step")
        try:
            debts = debts_at(self.target)
            text = (self.target / "CHANGELOG.md").read_text(errors="replace")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise Refused(f"!! ratchets: the artifact's floors do not read: {exc}") from exc
        if not debts:
            out("   no rule in the artifact declares `debt:` — there is no ratchet to step")
            return
        measured = {rid: d.lines for rid, d in debts.items()}
        line = machine_line(debts)
        carried = read_machine_line("\n".join(section(text, self.version)))
        if carried != measured:
            raise Refused(
                f"!! ratchets: `## [{self.version}]` does not carry the candidate's debt line.",
                f"   measured  {line}",
                f"   carried   {carried if carried is not None else 'none'}",
                "   Paste the measured line into the section — it is the next release's baseline.",
            )
        out(f"   {line}")
        before_version = self.last_tag.removeprefix("v")
        before = read_machine_line("\n".join(section(text, before_version)))
        if before is None:
            out(f"   {self.last_tag} recorded no ratchet-debt line: this one is the first baseline")
            return
        kind = release_kind(before_version, self.version)
        was, now = sum(before.values()), sum(measured.values())
        need = debt_step(was, kind)
        moves = ", ".join(f"{rid} {before.get(rid, 0)}→{n}" for rid, n in measured.items())
        if was - now < need:
            raise Refused(
                f"!! the ratchets did not fall since {self.last_tag}: {moves}",
                f"   a {kind} release owes the summed floors ({was}) a fall of at least {need}",
                "   — max(5 % of the remaining sum, 2,000 lines) per minor, one line per patch —",
                f"   and they fell by {was - now}. Pay the debt down and lower the floors by",
                "   their printed lines; nothing was committed or tagged.",
            )
        out(f"   ok — {moves}: fell {was - now}, the {kind} step is {need}")

    def critique(self) -> None:
        """Release mode: a MINOR ships after a re-read naming this tree; unreached on a product."""
        out()
        out("-- critique: a minor ships after the five-lens re-read of THIS export")
        named = critique_rereads(self.root, self.identity)
        short = self.identity[:12]
        if named:
            out(f"   ok — {', '.join(named)} names the candidate's identity {short}")
            return
        kind = release_kind(self.last_tag.removeprefix("v"), self.version)
        if kind != "minor":
            out(
                f"   advisory — no re-read names the candidate's identity {short}; a {kind} "
                f"ships without one ({CRITIQUE_BRIEF})"
            )
            return
        self.violation(
            f"critique: no {REREADS} names the candidate's identity {self.identity} (its tree "
            f"with the version homes masked) in its header — a minor ships after the five-lens "
            f"re-read of this export or of a cut differing only in its version ({CRITIQUE_BRIEF})"
        )

    # --- step 5 (release): the supply chain, on the source ---------------------------------

    def supply_chain(self) -> None:
        """The supply-chain leg on the source: each advisory is a violation naming its fix."""
        out("   the world's advisory feed as of this minute: one published after it is not seen")
        with tempfile.TemporaryFile() as sink:
            sys.stdout.flush()
            try:
                rc = subprocess.run(
                    list(SUPPLY_CHAIN), cwd=self.root, stdout=sink, stderr=sink, check=False
                ).returncode
            except OSError as exc:
                raise Refused(
                    f"!! {SUPPLY_CHAIN[0]} could not be started on the source: {exc}",
                    "   Nothing was committed. Could-not-look, not a violation.",
                ) from None
            sink.seek(0)
            text = sink.read().decode(errors="replace")
        for line in indent(text):
            out(line)
        if rc == 0:
            out("   ok — the supply-chain leg is green on the source")
            return
        if rc != 1:
            raise Refused(
                f"!! the supply-chain leg exited {rc} on the source — it could not look.",
                "   Nothing was committed. Could-not-look, not a violation.",
            )
        found = advisories(text)
        for line in found or ["the leg is red and named no advisory row — its lines are above"]:
            self.violation(f"supply-chain: {line}")
        out("   the next commit is a lock bump or a declared exception — never this publish")

    # --- step 6 (release): the proof from zero, of the export, before the commit ------------

    def proof(self) -> None:
        """A green proof of the export's tree, dispatched if none exists; unreached on a product."""
        out("-- proof: the tag's tree is proven from zero before the tag exists")
        if not (self.root / PROOF_FLOW).is_file():
            raise Refused(
                f"!! this source carries no {PROOF_FLOW} — there is no proof to wait on,"
                " so nothing is tagged.",
                f"   remedy: restore {PROOF_FLOW} from the template, commit it, and re-run.",
                "   Nothing was committed.",
            )
        line, run = ledger.proof_consult(self.root, self.tree)
        if not run and "could not look" not in line:
            out(f"   {line}")
            self.dispatch_proof()
            line, run = ledger.proof_consult(self.root, self.tree)
        if "could not look" in line:
            raise Refused(
                f"!! {line}", "   Nothing was committed. Could-not-look, not a violation."
            )
        if run:
            out(f"   ok — {line}")
            return
        self.violation(
            f"proof: the export tree {self.tree[:12]} of the source {self.src_sha[:12]} has no"
            f" green proof from zero ({line})"
            " — nothing is tagged until it does"
        )

    def proof_runs(self) -> set[str]:
        done = subprocess.run(
            ["gh", "run", "list", "--workflow", Path(PROOF_FLOW).name, "--event"]
            + ["workflow_dispatch", "--limit", "20", "--json", "databaseId"]
            + ["--jq", ".[].databaseId"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise Refused(
                f"!! gh run list for {PROOF_FLOW} exited {done.returncode}: {done.stderr.strip()}",
                "   Nothing was committed. Could-not-look, not a violation.",
            )
        return {w for w in done.stdout.split() if w.isdigit()}

    def on_origin(self) -> None:
        """The source commit is on origin, or `Refused` before a dispatch waits for nothing."""
        done = subprocess.run(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{self.src_sha}", "--jq", ".sha"],
            cwd=self.root,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if done.returncode != 0 or done.stdout.strip() != self.src_sha:
            raise Refused(
                f"!! the source {self.src_sha[:12]} is not on origin ({done.stderr.strip()}),"
                " so a proof dispatched at it would never run.",
                "   remedy: push the source commit, then re-run. Nothing was committed.",
            )

    def dispatch_proof(self) -> None:
        """`gh workflow run` on the source commit, then `gh run watch` its run to the end."""
        self.on_origin()
        before = self.proof_runs()
        flow = Path(PROOF_FLOW).name
        if passthrough(["gh", "workflow", "run", flow, "-f", f"ref={self.src_sha}"], self.root):
            raise Refused(
                f"!! gh workflow run {flow} -f ref={self.src_sha} was refused.",
                "   Nothing was committed. Could-not-look, not a violation.",
            )
        for _ in range(PROOF_POLLS):
            new = self.proof_runs() - before
            if new:
                break
            time.sleep(PROOF_POLL_S)
        else:
            raise Refused(
                f"!! the dispatched {flow} run did not appear in {PROOF_POLLS} looks.",
                "   Nothing was committed. Could-not-look, not a violation.",
            )
        run = str(max(int(r) for r in new))
        out(f"   dispatched — waiting on run {run}; its record, not its exit, is the verdict")
        passthrough(["gh", "run", "watch", run, "--exit-status", "--interval", "60"], self.root)

    # --- step 6 (release) and the verdict ---------------------------------------------------

    def release_commit(self) -> None:
        """One squashed child of the published tip whose tree IS the census-verified tree."""
        p = str(self.pub)
        if self.violations:
            out(
                f"   SKIPPED — {self.violations} violation(s) above. Nothing was committed, nothing"
            )
            out(f"   was tagged, and {p} is exactly as this run found it.")
            return
        ref = f"refs/publish/import-{os.getpid()}"

        def drop_ref() -> None:
            git("-C", p, "update-ref", "-d", ref)

        if passthrough(
            ["git", "-C", p, "fetch", "--no-tags", "-q", str(self.target), f"+HEAD:{ref}"]
        ):
            raise Refused(
                f"!! the artifact's objects could not be fetched into {p}.",
                "   Nothing was committed. Could-not-look, not a violation.",
            )
        if git("-C", p, "cat-file", "-e", f"{self.tree}^{{tree}}").returncode != 0:
            drop_ref()
            raise Refused(
                f"!! the census-verified tree {self.tree} is not in {p} after the fetch.",
                "   The release commit would have to be built from something else, and",
                "   something else is precisely what this mode exists to refuse.",
            )
        who = git_ok("-C", p, "config", "user.name") or ""
        mail = git_ok("-C", p, "config", "user.email") or ""
        if who and mail:
            out(f"   identity   {who} <{mail}>  (the published clone's own)")
        else:
            who, mail = "publish", "publish@localhost"
            out(f"   identity   {who} <{mail}>  (this clone configures none)")
        message = (
            f"Pilecap {self.tag}\n\n"
            f"The template's system layer at {self.tag}, as one squashed commit: this\n"
            "release carries the whole tree, not a delta.\n\n"
            f"What changed and whether you want it: CHANGELOG.md, section [{self.version}].\n\n"
            f"Merging {self.tag} into a product brings it up to date from ANY earlier\n"
            "release — the chain is linear, so intermediates cost nothing and\n"
            "need not be merged one at a time.\n"
        )
        ident = ["-c", f"user.name={who}", "-c", f"user.email={mail}"]
        made = subprocess.run(
            [
                "git",
                "-C",
                p,
                *ident,
                "-c",
                "commit.gpgsign=false",
                "commit-tree",
                self.tree,
                "-p",
                self.pub_tip,
            ],
            input=message,
            stdout=subprocess.PIPE,
            text=True,
            check=False,
        )
        if made.returncode != 0:
            drop_ref()
            raise Refused(f"!! git commit-tree failed in {p} — nothing was tagged.")
        self.new = made.stdout.strip()
        new_tree = git_ok("-C", p, "rev-parse", f"{self.new}^{{tree}}") or ""
        out(f"   census tree  {self.tree}")
        out(f"   commit tree  {new_tree}")
        if new_tree != self.tree:
            drop_ref()
            raise Refused(
                "!! the release commit's tree is NOT the census-verified tree.",
                f"   census {self.tree}",
                f"   commit {new_tree}",
                "   The commit was written and is unreferenced; no branch moved and no",
                "   tag was created. Enforcement broken, not a violation.",
            )
        out("   equal — the release commit ships exactly what the census verified")
        tagged = passthrough(
            [
                "git",
                "-C",
                p,
                *ident,
                "-c",
                "tag.gpgsign=false",
                "tag",
                "-a",
                self.tag,
                "-m",
                f"Pilecap {self.tag}",
                self.new,
            ]
        )
        if tagged:
            drop_ref()
            raise Refused(
                f"!! the tag {self.tag} could not be written in {p} — the commit exists",
                f"   ({self.new}) and no branch was moved. Reconcile by hand.",
            )
        drop_ref()
        if passthrough(["git", "-C", p, "reset", "-q", "--hard", self.new]):
            raise Refused(
                f"!! {self.pub_branch} could not be moved to {self.new} in {p} — the commit"
                " and the",
                f"   tag {self.tag} both exist. Reconcile by hand.",
            )
        dirt = tree_dirt(self.pub)
        if dirt:
            raise Refused(
                f"!! {p} is not clean after the release commit — the released tree and",
                "   its working tree disagree, which is this instrument failing to leave",
                "   its own output in the state it promises.",
                *indent(dirt),
            )
        out(f"   parent     {self.pub_tip}")
        out(f"   commit     {self.new}")
        out(f"   tag        {self.tag}")
        out(f"   branch     {self.pub_branch} moved, working tree clean")
        out()
        out("   Nothing has left this machine. Push when you mean it:")
        out(f"     git -C {p} push origin {self.pub_branch} {self.tag}")

    def verdict(self) -> int:
        """0 clean · 1 the artifact was built and found wanting."""
        self.step(f"step {self.steps}/{self.steps} · the verdict")
        out(f"   artifact   {self.target}")
        out(f"   source     {self.src_sha}")
        out(f"   tree       {self.tree}")
        out(f"   identity   {self.identity} (the tree, version homes masked: a re-read names it)")
        if self.mode == "release" and not self.violations:
            out(f"   released   {self.tag}  ->  {self.new}  (child of {self.pub_tip})")
        if self.violations:
            out()
            out(
                f"== {self.violations} VIOLATION(S) — the artifact was built and is NOT"
                " publishable."
            )
            out("   Each line above names the id or the path and the file that cites it.")
            return 1
        out()
        out("== CLEAN · re-run and compare the tree line: it is the idempotence claim.")
        return 0


@road("publish", example="quality/tests/test_publish.py::test_the_clean_fixture_publishes")
def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`publish [--census | --to <dir> | --release <dir>]`: 0 clean · 1 violations · 2."""
    try:
        refuse_if_piped()
        args = parse(list(sys.argv[1:] if argv is None else argv))
        return Publish(root.resolve(), args).run()
    except Refused as refused:
        for line in refused.lines:
            err(line)
        return 2
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! COULD NOT LOOK: {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
