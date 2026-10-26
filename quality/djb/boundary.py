"""The layer boundary: on a product's tree the platform is read-only to its commits (rule 95)."""

# Invariant: one classifier — `divergence.rules_for` + `ownership_of`; no path list of its own.
# does-not-cover: a merge commit — its members were judged at their own commits.

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from quality.could_not_look import CouldNotLook
from quality.djb.ledger import Refused, Sanction
from quality.djb.rituals import divergence as D
from quality.djb.rituals.fold import DERIVED_PATHS, SUBJECT_PREFIX

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = "DJB_LAYER_SANCTION"
TRAILER = "Layer-Sanction"
HOOK_JUDGED = "DJB_LAYER_HOOK_JUDGED"
DRAWER = "quality/local/rules.yaml"
STACK_RULES = frozenset({"R3", "R4"})
STACK = frozenset(
    p for p in D.SHARED_EXACT if STACK_RULES & set(D.rule_ids(p)) and p not in DERIVED_PATHS
)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
TEMPLATE_NOOP = "layer: template tree — nothing frozen"
MERGE_NOOP = "layer: a merge commit — its members were judged at their own commits"
PLATFORM_REFUSAL = (
    "{path} is the platform's; it arrives by release fold (scripts/pm_fold.sh), never by a"
    " product commit — a divergence needs DJB_LAYER_SANCTION and its divergence: line (rule 60);"
    " a product's territory is its own apps, frontend/ and their derived files"
    " (docs/sdk/the-one-path.md)"
)
STACK_REFUSAL = (
    "{path} is the stack's (dependencies and services); a product commit changes it only under"
    ' DJB_LAYER_SANCTION="<who>: <why>", recorded as its Layer-Sanction: trailer'
)
REMOVAL_REFUSAL = (
    "this commit removes rule_id_namespace from quality/local/rules.yaml — the declaration is what"
    " makes this tree a product, and a product does not stop being one by commit"
)


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `root`, both streams captured; the hook's `GIT_INDEX_FILE` is inherited."""
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)


def classify(path: str, platform: Sequence[str]) -> str:
    """`platform`, `stack` or `product`, through the one classifier rule 60 and publish share."""
    ownership = D.ownership_of(path, D.rules_for([path])[path], platform)
    if ownership == "template":
        return "platform"
    if ownership == "shared" and (path in STACK or D.shared_by_glob(path)):
        return "stack"
    return "product"


def namespace_in(text: str | None) -> str | None:
    """The namespace a drawer's text declares, through the engine's one reader; None when absent."""
    if text is None:
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CouldNotLook(f"{DRAWER} could not be read as YAML: {exc}") from exc
    from quality.engine.rules import declared_namespace

    if doc is not None and not isinstance(doc, Mapping):
        raise CouldNotLook(
            f"{DRAWER} is not a mapping — `rule_id_namespace: <ns>` is one key of one"
        )
    return declared_namespace(doc or {})


def blob(root: Path, spec: str) -> str | None:
    """`git show <spec>`'s text, or None when that object has no such path."""
    shown = git(root, "show", spec)
    return shown.stdout if shown.returncode == 0 else None


def head(root: Path) -> str:
    """HEAD's sha, or the empty tree before the first commit."""
    found = git(root, "rev-parse", "-q", "--verify", "HEAD^{commit}")
    return found.stdout.strip() if found.returncode == 0 else EMPTY_TREE


def staged(root: Path) -> list[str]:
    """The paths this commit changes against HEAD, deletions included, renames as two paths."""
    done = git(root, "diff", "--cached", "--name-only", "--no-renames", "-z", head(root))
    if done.returncode != 0:
        raise CouldNotLook(f"git could not list the staged set: {done.stderr.strip()}")
    return [p for p in done.stdout.split("\0") if p]


def pending(root: Path) -> list[str]:
    """The working tree's changes against HEAD plus untracked-not-ignored: the next commit's set."""
    changed = git(root, "diff", "--name-only", "--no-renames", "-z", head(root))
    others = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if changed.returncode != 0 or others.returncode != 0:
        raise CouldNotLook("git could not list the working tree's changes")
    return sorted({p for p in (changed.stdout + others.stdout).split("\0") if p})


def merging(root: Path) -> bool:
    """A merge is in progress in this checkout."""
    return git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0


def sanction(environ: Mapping[str, str]) -> Sanction | None:
    """The typed `DJB_LAYER_SANCTION`, checked by the gate's grammar; None when unset or empty."""
    value = environ.get(VARIABLE, "")
    if not value:
        return None
    return Sanction.typed(value, VARIABLE, "<who>: <why>")


@dataclass
class Verdict:
    refusals: list[str] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)


def judge(
    paths: Iterable[str], platform: Sequence[str], typed: Sanction | None, named: set[str]
) -> Verdict:
    """Platform paths need the sanction and a `divergence:` line; stack paths need the sanction."""
    verdict = Verdict()
    for path in paths:
        kind = classify(path, platform)
        if kind == "platform":
            if typed is not None and path in named:
                verdict.admitted.append(path)
            else:
                verdict.refusals.append(PLATFORM_REFUSAL.format(path=path))
        elif kind == "stack":
            if typed is not None:
                verdict.admitted.append(path)
            else:
                verdict.refusals.append(STACK_REFUSAL.format(path=path))
    return verdict


def pre_commit(root: Path, environ: Mapping[str, str]) -> int:
    """The hook's step: exit 1 naming each frozen path, else 0; a printed no-op on a template."""
    before = namespace_in(blob(root, f"HEAD:{DRAWER}"))
    after = namespace_in(blob(root, f":{DRAWER}"))
    if before and not after:
        print(f"!! layer: {REMOVAL_REFUSAL}", file=sys.stderr)
        return 1
    if not after:
        print(TEMPLATE_NOOP)
        return 0
    if merging(root):
        print(MERGE_NOOP)
        return 0
    typed = sanction(environ)
    paths = staged(root)
    verdict = judge(paths, D.platform_apps(root), typed, D.named_divergences(root))
    for refusal in verdict.refusals:
        print(f"!! layer: {refusal}", file=sys.stderr)
    if verdict.refusals:
        return 1
    if verdict.admitted and typed is not None:
        print(f"layer: sanctioned by {typed.who}: {typed.reason} — {', '.join(verdict.admitted)}")
    else:
        print(f"layer: {len(paths)} staged path(s) in namespace {after}, none frozen")
    return 0


def commit_msg(root: Path, environ: Mapping[str, str], message: str) -> int:
    """Write the `Layer-Sanction:` trailer onto a sanctioned commit that touches a frozen path."""
    if not namespace_in(blob(root, f":{DRAWER}")) or merging(root):
        return 0
    typed = sanction(environ)
    if typed is None:
        return 0
    verdict = judge(staged(root), D.platform_apps(root), typed, D.named_divergences(root))
    if not verdict.admitted:
        return 0
    value = f"{TRAILER}: {typed.who}: {typed.reason}"
    done = git(
        root,
        "interpret-trailers",
        "--in-place",
        "--if-exists",
        "addIfDifferent",
        "--trailer",
        value,
        message,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"git interpret-trailers could not write {TRAILER}: {done.stderr}")
    print(f"layer: {value}")
    return 0


@dataclass
class Commit:
    sha: str
    subject: str
    sanctions: list[str]
    paths: list[str]


def commits_since(root: Path, base: str) -> list[Commit]:
    """Every non-merge commit in `base..HEAD`, with its trailer and its paths."""
    fmt = f"%x00%H%x1f%s%x1f%(trailers:key={TRAILER},valueonly,separator=%x1e)%x1f"
    done = git(
        root,
        "log",
        "--no-merges",
        "--no-renames",
        "--name-only",
        f"--format={fmt}",
        f"{base}..HEAD",
    )
    if done.returncode != 0:
        raise CouldNotLook(f"git log {base}..HEAD failed: {done.stderr.strip()}")
    found: list[Commit] = []
    for record in done.stdout.split("\0"):
        if not record.strip():
            continue
        sha, subject, trailers, names = record.split("\x1f", 3)
        sanctions = [t.strip() for t in trailers.split("\x1e") if t.strip()]
        found.append(Commit(sha, subject, sanctions, [n for n in names.splitlines() if n]))
    return found


def census(root: Path, environ: Mapping[str, str]) -> int:
    """Rule 95's body: exit 1 naming every unsanctioned frozen commit or pending path, 2 blind."""
    from quality.engine.rules import declared_namespace

    platform = D.platform_apps(root)
    kinds = [classify(p, platform) for p in D.seen_paths(root)]
    print(f"census: platform_paths={kinds.count('platform')} stack_paths={kinds.count('stack')}")
    if not declared_namespace():
        print(f"{TEMPLATE_NOOP} (rule 95 judges a tree that declares rule_id_namespace)")
        return 0
    judged: list[Commit] = []
    unsanctioned = 0
    base = D.declare_base(root, dict(environ))
    if base is None:
        print("layer: no template base declared — the history half is not judged")
    elif not D.resolves(root, base.ref):
        raise CouldNotLook(f"the declared base {base.ref} (from {base.source}) does not resolve")
    else:
        judged = commits_since(root, base.ref)
        for commit in judged:
            frozen = [p for p in commit.paths if classify(p, platform) != "product"]
            if not frozen or commit.sanctions or commit.subject.startswith(SUBJECT_PREFIX):
                continue
            unsanctioned += 1
            print(
                f"unsanctioned: {commit.sha} · {frozen[0]} · {len(frozen)} path(s) ·"
                f" {commit.subject}"
            )
    refusals: list[str] = []
    if not merging(root):
        # Invariant: no sanction is read here, so a banked verdict depends on the tree alone.
        at_hook = set(staged(root)) if environ.get(HOOK_JUDGED) == "1" else set()
        paths = [p for p in pending(root) if p not in at_hook]
        refusals = judge(paths, platform, None, set()).refusals
    for refusal in refusals:
        print(f"pending: {refusal.split(' ', 1)[0]} · {refusal}")
    print(f"census: commits={len(judged)} unsanctioned={unsanctioned} pending={len(refusals)}")
    return 1 if unsanctioned or refusals else 0


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`pre-commit`, `commit-msg <file>` or `--census`; an unknown word or a blind read is 2."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ["pre-commit"]:
            return pre_commit(root, os.environ)
        if len(args) == 2 and args[0] == "commit-msg":
            return commit_msg(root, os.environ, args[1])
        if args == ["--census"]:
            return census(root, os.environ)
    except Refused as exc:
        print(f"!! layer: {exc}", file=sys.stderr)
        return 2
    except CouldNotLook as exc:
        print(f"!! layer: COULD NOT LOOK — {exc}", file=sys.stderr)
        return 2
    print(
        "!! quality.djb.boundary takes pre-commit, commit-msg <file> or --census", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
