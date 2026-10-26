"""The PM's push roads: a pm/* branch opened as an auto-merging pull request, its verdict banked."""

# does-not-cover: a real forge — `--pr`'s push and `--ci-verdict`'s `gh` are driven over scratch.
# does-not-cover: the pre-push hook's judgement — `quality.djb.cli hook pre-push` owns the wall.
# does-not-cover: what the fold commits — `ledger.bank_arm` runs it; this road re-reads HEAD after.

from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from apps.core.roads import road
from quality.could_not_look import CouldNotLook
from quality.djb import env as djb_env
from quality.djb import ledger
from quality.djb.legs import sdk_reference
from quality.djb.rituals.verify_start import Died, Printed, err, indented, out

NOTHING_PUSHED = "Nothing was pinned and nothing was pushed."
#: The branch prefix a train branch carries: the one namespace `--pr` pushes.
PR_BRANCH_PREFIX = "pm/"
#: The typo belt under `--on-boxes`; the derived floor is checked again after the fold.
ON_BOXES_FLOOR = 5
LIFTED_WITH_VALUE = {
    "--on-boxes": "pm_push: --on-boxes takes a box count: ./scripts/pm_push.sh --bank --on-boxes 8",
    "--leak-proof": (
        "pm_push: --leak-proof takes a source, nightly or acceptance:"
        " ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof nightly"
    ),
}
#: The name the refusals tell the operator to run, as the shell's `$0` read under its drive.
SELF = "./scripts/pm_push.sh"
PROOF_OPTIONS = ("--out", "--seed", "--workers", "--where", "--run", "--attempt")
USAGE = """\
Push a pm/* train for its pull request's CI run, or bank a verdict. The PM's push path.

  ./scripts/pm_push.sh --bank       # bank a verdict for this tree FIRST, then push
  ./scripts/pm_push.sh --bank --on-boxes 8
                                    # the same verdict, measured on 8 verifier boxes
                                    # instead of on this laptop: one unit of the gate
                                    # per box, every shard's verdict fetched, ONE
                                    # composed row banked for the post-fold tree.
  ./scripts/pm_push.sh --pr         # push THIS pm/* branch with NO local verdict, open
                                    # its pull request and set auto-merge (a merge
                                    # commit): its CI run is the measurement and
                                    # GitHub merges it on green
  ./scripts/pm_push.sh --ci-verdict [<run id>]
                                    # read the run that measured HEAD's tree and bank
                                    # the ci: row the pre-push wall honours
  ./scripts/pm_push.sh --ci-verdict --merge <sha>
                                    # bank main's push run of that merge commit, from
                                    # any checkout (a pull request whose last run was
                                    # the loop lane is vouched for by main's run)
  ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof nightly
                                    # the shards at one pass, the second whole pass
                                    # read from the latest nightly (report-only);
                                    # `acceptance` (the default) launches the box
  ./scripts/pm_push.sh --proof [--out D] [--seed S] [--workers N]
                                    # the leak proof itself, HERE: the suite twice
                                    # under one seed, the map, leak_proof.txt
"""
NO_FOLD_ALONE = """\
pm_push: --no-fold is only meaningful with --bank or --pr, and this is neither.
   The fold runs at the BANK: it regenerates the derived files and commits them
   BEFORE the gate measures the tree, so that the verdict vouches for the tree
   the push carries. No other mode regenerates anything,
   so there is nothing here for --no-fold to skip.
   Accepting it silently would be a flag that did nothing with no line printed.
   scripts/pm_merge.sh refuses the same combination (it has no --pr)."""
ON_BOXES_ALONE = """\
pm_push: --on-boxes is only meaningful with --bank, and this is not a --bank run.
   --on-boxes says WHERE the bank's full gate runs: one unit of it per verifier
   box instead of every unit on this laptop. No other mode measures anything
   here, so there is nothing for --on-boxes to place.
   Accepting it silently would be a flag that did nothing with no line printed.
   The form is: ./scripts/pm_push.sh --bank --on-boxes {n}"""
LEAK_PROOF_ALONE = """\
pm_push: --leak-proof is only meaningful with --bank --on-boxes N, and this is not one.
   It says where the sharded bank's second whole pass comes from — the
   acceptance box it launches, or the latest nightly's record. Anywhere else
   there is no one-pass suite for a proof to stand behind.
   The form is: ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof {source}"""
NOTHING_LAUNCHED = "   Nothing was folded, nothing was launched and nothing was pushed."
BELOW_FLOOR = (
    """\
pm_push: --on-boxes {n} is below the floor of {floor}.
   THE RULE: one `--leg` per box, N = 3 + P + S over the gate's own units —
   the indivisible units one box each, pytest-x2 split P ways and selftest S
   ways. Below {floor} at least one unit would have NO box, and a bank
   that silently dropped a unit is a green that vouches for less than it says.
   ./scripts/check.sh --list-legs names the units; the floor this run would
   derive from that listing is checked again after the fold.
"""
    + NOTHING_LAUNCHED
)
PR_OFF_TRAIN = """\
pm_push: --pr pushes a TRAIN branch, and this checkout is on '{branch}'.
   Only a {prefix}* branch rides the CI road: its pull request's run is the
   measurement, and main is reached by that pull request's auto-merge on
   green, never by this push. Make the train branch first: git switch -c {prefix}<train>"""
PR_NOTHING = "Nothing was written and nothing was pushed."
#: The one push road a pull request rides (CI-THIRD-1 1.4): each push is one full measure.
PR_ONCE = (
    "push once at `--fast` green with main folded in; a push whose only change is the fold is"
    " honoured, a push that brings main's commits is measured"
)
RETIRED = """\
pm_push: the pin-and-push road to main is retired: main moves by a pull request's merge.
   GitHub merges a pm/* branch's pull request when its required checks are green,
   and the pre-push wall refuses a push to main it holds no verdict for. From the
   train branch: ./scripts/pm_push.sh --pr"""
#: The forge's merge method for every pull request `--pr` opens (the ruleset allows merges).
MERGE_METHOD = "--merge"
#: The CI run's jobs an active ruleset on main must require before `--pr` arms auto-merge.
REQUIRED_CHECKS = ("verdict", "gate-verdict")
#: The ruleset the owner posts once, before the first `--pr`; `--pr` names it when one is missing.
RULESET_FILE = "deploy/ruleset.json"


def _env(name: str, default: str) -> str:
    """`${name:-default}`: an empty value reads as unset, as the shell read it."""
    return os.environ.get(name) or default


@dataclass
class Args:
    """What the operator typed, after the lifted flags and the one mode word."""

    mode: str = ""
    no_fold: bool = False
    on_boxes: str = ""
    leak_proof: str = ""
    ci_run: str = ""
    merge: str = ""
    proof: dict[str, str] | None = None


def _lift(argv: list[str]) -> tuple[list[str], Args]:
    """`--no-fold`, `--on-boxes N` and `--leak-proof S` taken out before anything counts."""
    args = Args()
    rest: list[str] = []
    i = 0
    while i < len(argv):
        word = argv[i]
        if word == "--no-fold":
            args.no_fold = True
        elif word in LIFTED_WITH_VALUE:
            if i + 1 >= len(argv):
                raise Died(NOTHING_PUSHED, LIFTED_WITH_VALUE[word])
            i += 1
            if word == "--on-boxes":
                args.on_boxes = argv[i]
            else:
                args.leak_proof = argv[i]
        else:
            rest.append(word)
        i += 1
    return rest, args


def _mode(rest: list[str], args: Args) -> list[str]:
    """The mode word and its own arguments; no mode word leaves `args.mode` empty."""
    head = rest[0] if rest else ""
    if head == "--bank":
        if len(rest) != 1:
            raise Died(
                NOTHING_PUSHED,
                "pm_push: --bank measures THIS checkout's tree, so it pushes THIS checkout's"
                f" HEAD and takes no commit argument. Got: {' '.join(rest)}",
            )
        args.mode = "bank"
    elif head == "--pr":
        if len(rest) != 1:
            raise Died(
                NOTHING_PUSHED,
                "pm_push: --pr pushes THIS checkout's train branch, so it takes no commit"
                f" argument. Got: {' '.join(rest)}",
            )
        args.mode = "pr"
    elif head == "--ci-verdict":
        words = rest[1:]
        if "--merge" in words:
            at = words.index("--merge")
            if at + 1 >= len(words) or not _hexish(words[at + 1]):
                raise Died(
                    NOTHING_PUSHED,
                    "pm_push: --ci-verdict --merge takes the merge commit's sha (7 to 40 hex):"
                    " ./scripts/pm_push.sh --ci-verdict --merge <sha>",
                )
            args.merge = words[at + 1]
            words = words[:at] + words[at + 2 :]
        if len(words) > 1:
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: --ci-verdict takes at most one run id. Got: {' '.join(rest)}",
            )
        run = words[0] if words else ""
        if run and not (run.isascii() and run.isdigit() and run[0] != "0"):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: --ci-verdict takes a run id (a decimal, as gh prints it); got '{run}'.",
            )
        args.mode, args.ci_run = "ci-verdict", run
        return [head]
    elif head == "--proof":
        args.mode, args.proof = "proof", _proof_options(rest[1:])
        return [head]
    elif head in ("-h", "--help"):
        args.mode = "help"
    elif head.startswith("-") and head != "--dry-run":
        raise Died(NOTHING_PUSHED, f"pm_push: unknown flag {head}. Run {SELF} --help.")
    return rest


def _hexish(word: str) -> bool:
    """A commit name as an operator types one: 7 to 40 lowercase hex."""
    return 7 <= len(word) <= 40 and all(c in "0123456789abcdef" for c in word)


def _proof_options(words: list[str]) -> dict[str, str]:
    """`--proof`'s own options: each takes a value, and nothing else is one."""
    found = {"--where": "acceptance", "--run": "0", "--attempt": "0"}
    i = 0
    while i < len(words):
        word = words[i]
        if word not in PROOF_OPTIONS:
            raise Died(
                NOTHING_PUSHED,
                "pm_push: --proof takes --out, --seed, --workers, --where, --run and --attempt;"
                f" got '{word}'.",
            )
        if i + 1 >= len(words):
            raise Died(NOTHING_PUSHED, f"pm_push: --proof {word} takes a value.")
        found[word] = words[i + 1]
        i += 2
    return found


def parse(argv: Sequence[str]) -> Args:
    """The argument arm: every refusal here costs nothing and comes before any fold or box."""
    rest, args = _lift(list(argv))
    rest = _mode(rest, args)
    if args.mode == "help":
        return args
    if args.no_fold and args.mode not in ("bank", "pr"):
        raise Died(NOTHING_PUSHED, NO_FOLD_ALONE)
    if args.on_boxes and args.mode != "bank":
        raise Died(NOTHING_PUSHED, ON_BOXES_ALONE.format(n=args.on_boxes))
    if args.leak_proof:
        if args.mode != "bank" or not args.on_boxes:
            raise Died(NOTHING_PUSHED, LEAK_PROOF_ALONE.format(source=args.leak_proof))
        if args.leak_proof not in ("nightly", "acceptance"):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: --leak-proof takes nightly or acceptance, got '{args.leak_proof}'.\n"
                + NOTHING_LAUNCHED,
            )
    # deleted: the bare, `<sha>` and `--dry-run` arm that pinned pm-push and pushed main (MQ2.1)
    # pin: quality/tests/test_push.py::test_the_pin_and_push_road_to_main_is_retired
    if not args.mode:
        raise Died(NOTHING_PUSHED, RETIRED)
    if args.on_boxes:
        if not (args.on_boxes.isascii() and args.on_boxes.isdigit()):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: --on-boxes takes a whole number of boxes, got '{args.on_boxes}'.\n"
                + NOTHING_LAUNCHED,
            )
        if int(args.on_boxes) < ON_BOXES_FLOOR:
            raise Died(NOTHING_PUSHED, BELOW_FLOOR.format(n=args.on_boxes, floor=ON_BOXES_FLOOR))
    return args


# --- git, from wherever the operator stands; never a `cd` -------------------------------------


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git -C <root> <argv>`, both streams captured."""
    return subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, text=True, check=False
    )


def dirt(root: Path) -> str:
    """`git status --porcelain` of `root`: empty when the checkout is clean."""
    return git(root, "status", "--porcelain").stdout


def show_status(root: Path) -> None:
    """`git status --short` on stderr, as the refusal that names a dirty tree prints it."""
    err(git(root, "status", "--short").stdout.rstrip("\n"))


def head(root: Path, rev: str = "HEAD") -> str:
    """`rev` resolved to a full commit sha in `root`, or ''."""
    done = git(root, "rev-parse", "--verify", f"{rev}^{{commit}}")
    return done.stdout.strip() if done.returncode == 0 else ""


def push_run(where: Path, remote: str, refspec: str, *, intent: bool = False) -> int:
    """The one push, through the pre-push wall; its exit is git's."""
    env = dict(os.environ)
    if intent:
        env["DJB_PUSH_INTENT"] = "ci"
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(
        ["git", "-C", str(where), "push", remote, refspec], env=env, check=False
    ).returncode


def short(root: Path, rev: str) -> str:
    """`git rev-parse --short <rev>` in `root`, or ''."""
    done = git(root, "rev-parse", "--short", rev)
    return done.stdout.strip() if done.returncode == 0 else ""


def require_current_reference(root: Path) -> None:
    """Exit 2 naming each stale `docs/sdk/` page with the leg's line, before any gate or push."""
    if not (root / sdk_reference.HOME).is_dir():
        out(f"pm_push: no {sdk_reference.HOME}/ in this tree — there is no reference to check")
        return
    rc, stale, text = sdk_reference.check(root)
    if rc == 0:
        out(f"pm_push: {sdk_reference.HOME}/ is current")
        return
    if rc == 1 and stale:
        for line in stale:
            err(f"!! {line}")
        err(f"   {NOTHING_PUSHED}")
        raise Printed(stale[0])
    err(text.rstrip("\n"))
    raise Died(
        NOTHING_PUSHED,
        f"pm_push: {sdk_reference.HOME}/ could not be checked against its derivation — see above",
    )


# --- --pr: the train branch, pushed on an intent ---------------------------------------------


def _dirty_refusal(root: Path, headline: str, *lines: str) -> Printed:
    """A dirty tree named with its status, then `lines`: the exit-2 sentences, already printed."""
    err(f"!! {headline}")
    show_status(root)
    for line in lines:
        err(f"   {line}")
    return Printed(headline)


def pr(root: Path, args: Args) -> int:
    """`--pr`: exit 2 on each of its refusals before the intent row; else push and open it."""
    remote = _env("DJB_PUSH_REMOTE", "origin")
    target = _env("DJB_PUSH_BRANCH", "main")
    branch = git(root, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    if not (branch.startswith(PR_BRANCH_PREFIX) and branch != PR_BRANCH_PREFIX):
        raise Died(
            NOTHING_PUSHED,
            PR_OFF_TRAIN.format(branch=branch or "a detached HEAD", prefix=PR_BRANCH_PREFIX),
        )
    if dirt(root):
        raise _dirty_refusal(
            root,
            f"pm_push --pr: {root} has uncommitted changes.",
            "The intent row names the tree CI is about to measure, and a dirty tree is",
            "bytes no commit carries. Commit or stash first.",
            "Nothing was folded, nothing was written and nothing was pushed.",
        )
    with contextlib.chdir(root):
        rc = ledger.bank_arm(root, who="pm_push --pr", no_fold=args.no_fold, nothing=PR_NOTHING)
    if rc != 0:
        return rc
    sha = head(root)
    if not sha:
        raise Died(NOTHING_PUSHED, "pm_push: could not re-read HEAD after the fold")
    if dirt(root):
        raise _dirty_refusal(
            root,
            f"pm_push --pr: the fold left {root} dirty.",
            "Nothing was written and nothing was pushed.",
        )
    require_current_reference(root)
    try:
        tree = ledger.measured_tree(root)
    except (ledger.Mismatch, OSError):
        raise Died(
            NOTHING_PUSHED,
            f"pm_push: the measured tree of {root} could not be read — the intent row would"
            " name nothing",
        ) from None
    listed = git(root, "ls-remote", remote, f"refs/heads/{branch}")
    remote_sha = (
        listed.stdout.split()[0] if listed.returncode == 0 and listed.stdout.split() else ""
    )
    subject = pr_title(root, f"{remote}/{target}", sha)
    if remote_sha and remote_sha == sha:
        out(f"pm_push --pr: {remote}/{branch} is already at {sha} — nothing to push.")
        out("  No intent row was written and no push was made (so no hook and no gate ran).")
        return open_pull_request(root, branch, target, subject, tree)
    sanction = ledger.Sanction("ci", "pm_push", f"the pull request's run measures {branch}")
    out(
        f"pm_push --pr: pushing {branch} to {remote} with NO local verdict — its pull request's"
        " CI run is the measurement"
    )
    out(f"  branch        {branch}")
    out(f"  commit        {sha}  {subject}")
    out(f"  tree          {tree} (measured)")
    out(f"  road          {PR_ONCE}")
    try:
        ledger.intent_record(root, tree=tree, commit=sha, branch=branch, sanction=sanction)
    except (ledger.Refused, ledger.Mismatch, OSError):
        raise Died(
            NOTHING_PUSHED,
            "pm_push: the intent row could not be written — a push nobody can account for is"
            " not a push this script makes",
        ) from None
    out(f"  intent        v1 {tree} intent run=pending (the verdict ledger)")
    out(f"pm_push: pushing {sha} -> {remote}/{branch}")
    pushed = push_run(root, remote, f"{sha}:refs/heads/{branch}", intent=True)
    if pushed != 0:
        err(f"!! pm_push --pr: git push exited {pushed}; no pull request was opened.")
        return pushed
    return open_pull_request(root, branch, target, subject, tree)


#: Subjects a pull request is never named after: the fold's own commits and a docs-only claim.
UNTITLED = ("fold:", "Merge ")


def pr_title(root: Path, base: str, sha: str) -> str:
    """The pull request's title: the branch's last commit since `base` that is no fold or docs."""
    listed = git(root, "log", "--no-merges", "--format=%s", f"{base}..{sha}")
    for subject in listed.stdout.splitlines() if listed.returncode == 0 else ():
        if subject and not subject.startswith(UNTITLED) and "[docs-only]" not in subject:
            return subject
    return git(root, "log", "-1", "--format=%s", sha).stdout.strip()


def _forge(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`gh <argv>` in `root`, both streams captured; a missing `gh` is exit 127."""
    try:
        return subprocess.run(
            ["gh", *argv],
            cwd=root,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["gh", *argv], 127, "", str(exc))


def _forge_refused(act: str, done: subprocess.CompletedProcess[str], branch: str) -> Printed:
    """Exit 2 after the push: the branch stands on the remote and a re-run of `--pr` finishes."""
    said = (done.stderr or done.stdout).strip().splitlines()
    err(f"!! pm_push --pr: `{act}` refused (exit {done.returncode}): {said[-1] if said else ''}")
    err(f"   the branch IS pushed ({branch}); nothing merges until this is done.")
    err("   Re-run ./scripts/pm_push.sh --pr: the push is skipped and the forge asked again.")
    return Printed(act)


def _open_pull_request_of(root: Path, branch: str) -> subprocess.CompletedProcess[str]:
    """`gh pr list` of the branch's OPEN pull request: `<number> <url>`, or empty when none is."""
    shape = '.[] | "\\(.number) \\(.url)"'
    listing = ("pr", "list", "--head", branch, "--state", "open", "--json", "number,url")
    return _forge(root, *listing, "--jq", shape)


def _required_checks_passed(root: Path, number: str) -> str:
    """`<check>: <url>` for every `REQUIRED_CHECKS` the rollup answers SUCCESS, or empty."""
    shape = (
        '.statusCheckRollup[] | "\\(.name // .context) \\(.conclusion // .state)'
        ' \\(.detailsUrl // .targetUrl // "")"'
    )
    seen = _forge(root, "pr", "view", number, "--json", "statusCheckRollup", "--jq", shape)
    rollup: dict[str, list[tuple[str, str]]] = {}
    for line in seen.stdout.splitlines() if seen.returncode == 0 else ():
        name, conclusion, url = (line.split() + ["", "", ""])[:3]
        rollup.setdefault(name, []).append((conclusion, url))
    passed = []
    for check in REQUIRED_CHECKS:
        runs = rollup.get(check, [])
        if not runs or any(conclusion != "SUCCESS" for conclusion, _ in runs):
            return ""
        passed.append(f"{check}: {runs[-1][1] or '?'}")
    return ", ".join(passed)


def _auto_merge_armed(root: Path, number: str, branch: str) -> str | None:
    """The `mergeStateStatus` of an armed OPEN pull request, None for a vouched merge, or exit 2."""
    shape = '"\\(.state) \\(.autoMergeRequest != null) \\(.mergeStateStatus)"'
    fields = "autoMergeRequest,state,mergeStateStatus"
    seen = _forge(root, "pr", "view", number, "--json", fields, "--jq", shape)
    if seen.returncode != 0:
        raise _forge_refused(f"gh pr view {number}", seen, branch)
    state, armed, status = (seen.stdout.split() + ["?", "?", "?"])[:3]
    if state == "OPEN" and armed == "true":
        return status
    if state == "MERGED" and (passed := _required_checks_passed(root, number)):
        out(
            f"pm_push --pr: pull request #{number} merged at once — its required checks had"
            f" already passed ({passed})"
        )
        return None
    if state == "MERGED":
        happened = f"pull request #{number} MERGED at once, without a CI verdict"
    else:
        happened = f"auto-merge was NOT armed on pull request #{number} (state {state})"
    err(f"!! pm_push --pr: {happened} (mergeStateStatus {status}).")
    err("   `gh pr merge --auto` merges immediately when nothing requires a check: the")
    err("   ruleset that requires the CI run on main must be active before --pr is used.")
    raise Printed(happened)


def missing_checks(rules: object) -> list[str]:
    """The `REQUIRED_CHECKS` no `required_status_checks` rule in `rules` names, in their order."""
    named: set[str] = set()
    for rule in rules if isinstance(rules, list) else ():
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            parameters = rule.get("parameters") or {}
            for check in parameters.get("required_status_checks") or ():
                if isinstance(check, dict):
                    named.add(str(check.get("context", "")))
    return [check for check in REQUIRED_CHECKS if check not in named]


def _checks_required(root: Path, number: str, branch: str, target: str) -> None:
    """Main's active rules require both CI checks, or exit 2 with the pull request left open."""
    seen = _forge(root, "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    if seen.returncode != 0 or not seen.stdout.strip():
        raise _forge_refused("gh repo view", seen, branch)
    repo = seen.stdout.strip()
    act = f"gh api repos/{repo}/rules/branches/{target}"
    rules = _forge(root, "api", f"repos/{repo}/rules/branches/{target}")
    if rules.returncode != 0:
        raise _forge_refused(act, rules, branch)
    try:
        missing = missing_checks(json.loads(rules.stdout))
    except ValueError:
        err(f"!! pm_push --pr: `{act}` answered no JSON: {rules.stdout.strip()[:200]}")
        raise Printed(act) from None
    if not missing:
        return
    headline = f"{target} requires no CI verdict, so pull request #{number} is OPEN and NOT merged"
    err(f"!! pm_push --pr: {headline} (missing: {', '.join(missing)}).")
    err(f"   No active ruleset on {target} requires the checks {' and '.join(REQUIRED_CHECKS)},")
    err("   and `gh pr merge --auto` merges at once when nothing requires a check.")
    err("   The owner's one-time lines, in order, before the first --pr:")
    err(f"     gh repo edit {repo} --enable-auto-merge")
    err(f"     gh api -X POST repos/{repo}/rulesets --input {RULESET_FILE}")
    err("   Then re-run ./scripts/pm_push.sh --pr: the push is skipped and the merge armed.")
    raise Printed(headline)


def open_pull_request(root: Path, branch: str, target: str, subject: str, tree: str) -> int:
    """The branch's OPEN pull request found or opened, then auto-merge armed and read back; 0/2."""
    found = _open_pull_request_of(root, branch)
    if found.returncode != 0:
        raise _forge_refused("gh pr list", found, branch)
    if not found.stdout.strip():
        body = (
            f"Opened by `./scripts/pm_push.sh --pr`: tree {tree} (measured). This run is the"
            " measurement; GitHub merges on green (auto-merge, a merge commit)."
        )
        made = _forge(
            root,
            "pr",
            "create",
            "--base",
            target,
            "--head",
            branch,
            "--title",
            subject,
            "--body",
            body,
        )
        if made.returncode != 0:
            raise _forge_refused("gh pr create", made, branch)
        found = _open_pull_request_of(root, branch)
    number, _, url = found.stdout.strip().partition(" ")
    if found.returncode != 0 or not number.isdigit():
        raise _forge_refused("gh pr list", found, branch)
    _checks_required(root, number, branch, target)
    act = f"gh pr merge {number} --auto {MERGE_METHOD}"
    merged = _forge(root, "pr", "merge", number, "--auto", MERGE_METHOD)
    if merged.returncode != 0:
        raise _forge_refused(act, merged, branch)
    status = _auto_merge_armed(root, number, branch)
    if status is None:
        out("  next          on that main, ./scripts/pm_push.sh --ci-verdict")
        return 0
    out(f"pm_push --pr: pr=#{number} {url} auto-merge=on (merge commit)")
    if status == "BEHIND":
        out(
            f"pr #{number} is BEHIND {target} (strict checks): merge origin/{target} into this"
            " branch and run --pr again"
        )
    out(
        f"  next          GitHub merges into {target} when the required checks are green;"
        " then, on that main,"
    )
    out("                ./scripts/pm_push.sh --ci-verdict   (banks the row the wall honours)")
    return 0


# --- --ci-verdict: the PR run's record read, judged and banked -------------------------------


def _ci_refuse(why: str, *, stands: bool = False) -> Printed:
    """Exit 2 with no row (or the one that could not be removed): the footer is true either way."""
    err(f"!! pm_push --ci-verdict: THE CI RECORD CANNOT BE BANKED: {why}")
    if stands:
        err("   A REFUSED ROW STANDS in the ledger (named above) and nothing was pushed.")
    else:
        err("   No row was written and nothing was pushed. A reader that could not")
    err("   vouch for the record banks nothing (exit 2).")
    return Printed(why)


#: The runs `--ci-verdict` asks the consult for: a pull request's, and a push run of HEAD itself.
CI_VERDICT_EVENTS = ("pull_request", "push")


def _consulted_run(root: Path) -> str:
    """The run that measured HEAD's tree, found by `ledger.ci_consult`, or exit 2 naming why not."""
    sha = head(root)
    line, run = ledger.ci_consult(root, sha, CI_VERDICT_EVENTS)
    out(f"  {line}")
    if not run:
        why = f"no run is honoured for HEAD {sha[:12]} — {line.removeprefix('consult: ')}."
        raise _ci_refuse(_with_merge_road(root, why))
    out(f"  run      {run} (the run that measured {sha[:12]}'s tree)")
    return run


#: The judge's sentence for a lane that vouches for no tree (`ledger.ci_judge`).
NARROW_LANES = ("ran the loop lane", "ran the docs lane")


def _with_merge_road(root: Path, why: str) -> str:
    """`why`, plus the road that banks the merge when the pull request's run was a narrow lane."""
    lane = next((said.split()[2] for said in NARROW_LANES if said in why), "")
    if not lane:
        return why
    seen = _forge(root, "pr", "view", "--json", "state,mergeCommit", "--jq", _MERGE_SHAPE)
    state, _, merge = seen.stdout.strip().partition(" ")
    if seen.returncode != 0 or state != "MERGED" or not merge:
        return (
            f"{why} The pull request's last run was the {lane} lane, and it has not merged"
            f" (state {state or '<unread>'}): once it has, main's push run measures the merge"
            " in full — ./scripts/pm_push.sh --ci-verdict --merge <its merge commit>."
        )
    run = _push_run_of(root, merge) or "<none completed yet>"
    return (
        f"{why} bank from main's push run {run} at {merge} — the PR's last run was the {lane}"
        f" lane: ./scripts/pm_push.sh --ci-verdict --merge {merge}"
    )


#: `gh pr view`'s answer, one line: `<STATE> <merge commit oid or nothing>`.
_MERGE_SHAPE = '"\\(.state) \\(.mergeCommit.oid // "")"'


def _push_run_of(root: Path, sha: str) -> str:
    """The newest completed push run of the CI workflow for `sha`, or "" when there is none."""
    workflow = djb_env.read("DJB_CI_WORKFLOW") or "ci.yml"
    seen = _forge(
        root,
        "api",
        f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs?event=push"
        f"&status=completed&head_sha={sha}",
        "--jq",
        ".workflow_runs[].id",
    )
    runs = [int(r) for r in seen.stdout.split() if r.isdigit() and r[0] != "0"]
    return str(max(runs)) if seen.returncode == 0 and runs else ""


@contextlib.contextmanager
def _detached_at(root: Path, sha: str) -> Iterator[Path]:
    """A throwaway detached checkout of `sha`, sharing `root`'s ledger and interpreter."""
    scratch = Path(tempfile.mkdtemp(prefix="djb-ci-merge."))
    where = scratch / "at"
    added = git(root, "worktree", "add", "-q", "--detach", str(where), sha)
    if added.returncode != 0:
        shutil.rmtree(scratch, ignore_errors=True)
        raise _ci_refuse(
            f"a detached checkout of {sha[:12]} could not be made ({added.stderr.strip()})."
        )
    venv = root / ".venv"
    if venv.exists():
        (where / ".venv").symlink_to(venv)
    try:
        yield where
    finally:
        git(root, "worktree", "remove", "--force", str(where))
        shutil.rmtree(scratch, ignore_errors=True)


def _take_back(path: Path, before: int, tree: str, proof: str) -> Printed:
    """The refused row removed by position and content, or said to stand; exit 2 either way."""
    try:
        with path.open("rb") as ledger_file:
            ledger_file.seek(before)
            added = ledger_file.read().decode(errors="replace").rstrip("\n")
    except OSError:
        added = ""
    if "\n" in added:
        added = "<more than one line>"
    if added.startswith(f"{ledger.SCHEMA} {tree} full ") and added.endswith(f" leak-proof={proof}"):
        rewrite = path.with_name(f"{path.name}.rewrite.{os.getpid()}")
        try:
            with path.open("rb") as ledger_file:
                rewrite.write_bytes(ledger_file.read(before))
            os.replace(rewrite, path)
        except OSError:
            rewrite.unlink(missing_ok=True)
            return _ci_refuse(
                "the row was written, gate_ledger_lookup refuses it, and it could not be removed"
                f" from {path} — it STANDS there as its tree's newest row; remove that last line"
                " by hand.",
                stands=True,
            )
        return _ci_refuse(
            "the row was written and gate_ledger_lookup refuses it (its note is above) — the row"
            " was REMOVED, and the ledger holds exactly what it held before this run."
        )
    return _ci_refuse(
        "the row was written and gate_ledger_lookup refuses it, and the ledger's tail past this"
        f" run's write is not exactly that one row ({added[:120]}) — nothing was removed; the"
        f" refused row STANDS in {path}.",
        stands=True,
    )


def ci_verdict(root: Path, args: Args) -> int:
    """`--ci-verdict [<run>] [--merge <sha>]`: 0 with one honoured `ci:` row, or 2, no row."""
    if shutil.which("gh") is None:
        raise _ci_refuse(
            "no `gh` on PATH — the record is a workflow artifact and `gh` is its one reader."
        )
    try:
        sink = Path(tempfile.mkdtemp(prefix="djb-ci-verdict."))
    except OSError:
        raise _ci_refuse("could not make a directory to download the record into.") from None
    out(f"pm_push --ci-verdict: reading the CI run's {ledger.CI_ARTIFACT} record (logs: {sink})")
    run = args.ci_run
    if args.merge:
        known = git(root, "rev-parse", "-q", "--verify", f"{args.merge}^{{commit}}")
        sha = known.stdout.strip()
        if known.returncode != 0 or not sha:
            raise _ci_refuse(f"merge commit {args.merge} is not in this checkout — fetch it first.")
        out(f"  merge    {sha} (main's push run vouches for it, in a detached checkout)")
        if not run:
            run = _push_run_of(root, sha)
            if not run:
                raise _ci_refuse(
                    f"no completed push run of the CI workflow for merge commit {sha[:12]}."
                )
        out(f"  run      {run}")
        with _detached_at(root, sha) as where:
            return _bank_run(where, run, sink)
    if run:
        out(f"  run      {run} (given)")
    else:
        run = _consulted_run(root)
    return _bank_run(root, run, sink)


def _bank_run(root: Path, run: str, sink: Path) -> int:
    """`run`'s record judged against `root`'s HEAD and banked as one `ci:` row; 0, or exit 2."""
    rc, attempt = ledger.ci_fetch(root, run, sink)
    if rc != 0:
        raise _ci_refuse(f"{attempt}.")
    out(f"  attempt  {attempt} (the latest; its artifact is {ledger.ci_artifact_name(attempt)})")
    record = (sink / f"record-{run}" / ledger.CI_RECORD).read_text(errors="replace")
    line = next((ln for ln in record.splitlines() if ln.strip()), "")
    out(f"  record   {line or '<empty>'}")
    listing = sink / "listlegs.tsv"
    with listing.open("w") as listed:
        subprocess.run(
            ["./scripts/check.sh", "--list-legs"],
            cwd=root,
            stdout=listed,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    if listing.stat().st_size == 0:
        raise _ci_refuse(
            "./scripts/check.sh --list-legs would not answer — the record's units cannot be read"
            " without it."
        )
    try:
        expanded = ledger.ci_judge(root, line, run, attempt, listing.read_text())
    except ledger.Refused as exc:
        raise _ci_refuse(_with_merge_road(root, f"{exc}.")) from None
    try:
        rec = ledger.ci_parse(line)
    except ledger.Refused as exc:
        raise _ci_refuse(
            f"the record parsed in the judge and not here ({exc}) — the two readers disagree."
        ) from None
    sha = head(root)
    try:
        merged = ledger.measured_tree_of(root, "HEAD")
    except ledger.Mismatch:
        merged = ""
    if rec.tree != merged:
        raise _ci_refuse(
            f"run {run} measured tree {rec.tree[:12]} and HEAD {sha[:12]} holds the merged tree"
            f" {merged[:12] or '<unreadable>'} — the run never measured the tree this line of"
            " history holds (a merge over a moved main: update the pull request and let its run"
            " measure again)"
        )
    merge = f" merge={sha[:12]}" if sha != rec.commit else ""
    try:
        sanction = ledger.Sanction(
            "ci-verdict",
            "pm_push",
            f"run={run} attempt={attempt} commit={rec.commit[:12]}{merge} shards={rec.shards}",
        ).check()
    except ledger.Refused:
        raise _ci_refuse("the row's sanction would not set — nothing was written.") from None
    proof = f"ci:{run} rc=0"
    try:
        path = ledger.ledger_path(root)
    except (ledger.Refused, ledger.Mismatch):
        raise _ci_refuse(
            "the verdict ledger's path would not resolve — there is nowhere to write the row."
        ) from None
    before = path.stat().st_size if path.is_file() else 0
    try:
        ledger.record_full(
            root, tree=rec.tree, legs=expanded, caller="pm-bank", sanction=sanction, proof=proof
        )
    except (ledger.Refused, ledger.Mismatch, OSError):
        raise _ci_refuse(
            "the verdict ledger could not be written — a green nobody can read is not a verdict."
        ) from None
    if ledger.consult(root, rec.tree) is None:
        raise _take_back(path, before, rec.tree, proof)
    out(f"pm_push --ci-verdict: verdict banked for tree {rec.tree}")
    out(f"  caller=pm-bank sanction={sanction.field().removeprefix('sanction=')}")
    out(f"  legs={expanded}")
    out(f"  leak-proof={proof} (the second whole pass is the nightly's)")
    out("  the pre-push wall honours this tree; main itself moves only by a pull request's merge")
    return 0


# --- --bank's push: pm-push pinned to the commit, then pushed (R10 retires it) ---------------


def pm_push_worktree(root: Path) -> Path:
    """The worktree named `DJB_PUSH_WORKTREE` (`pm-push`), asked of git, clean; else exit 2."""
    name = _env("DJB_PUSH_WORKTREE", "pm-push")
    found = ""
    for line in git(root, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree ") and Path(line[len("worktree ") :]).name == name:
            found = line[len("worktree ") :]
    if not found:
        raise Died(
            NOTHING_PUSHED,
            f"pm_push: no worktree named '{name}' in git worktree list. Create one (git worktree"
            f" add --detach .claude/worktrees/{name}) or name another with DJB_PUSH_WORKTREE.",
        )
    where = Path(found)
    if not where.is_dir():
        raise Died(
            NOTHING_PUSHED, f"pm_push: git worktree list names {found}, which is not a directory"
        )
    if dirt(where):
        raise _dirty_refusal(
            where,
            f"pm_push: {where} has uncommitted changes.",
            "Pinning it would throw them away. Deal with them first; this script",
            "will not decide that for you.",
        )
    return where


def pin_and_push(root: Path, pm_push: Path, sha: str) -> int:
    """The range and the intended tip printed together, pm-push pinned, then git's push."""
    remote = _env("DJB_PUSH_REMOTE", "origin")
    target = _env("DJB_PUSH_BRANCH", "main")
    name = _env("DJB_PUSH_WORKTREE", "pm-push")
    subject = git(root, "log", "-1", "--format=%s", sha).stdout.strip()
    out(f"pm_push: pinning {name} and pushing to {remote}/{target}")
    out(f"  checkout      {root}")
    out(f"  pm-push       {pm_push}")
    out(f"  was at        {short(pm_push, 'HEAD') or '(unknown)'}")
    out(f"  INTENDED TIP  {short(root, sha)}  {subject}")
    git(root, "fetch", "-q", remote, target)
    tip = git(root, "rev-parse", "--verify", "--quiet", f"{remote}/{target}").stdout.strip()
    if tip:
        counted = git(root, "rev-list", "--count", f"{tip}..{sha}")
        count = counted.stdout.strip() if counted.returncode == 0 else "?"
        out(f"  RANGE         {short(root, tip)}..{short(root, sha)}  ({count} commit(s))")
        if count == "0":
            out(f"  note: nothing to push — {remote}/{target} already has this commit.")
        if git(root, "merge-base", "--is-ancestor", tip, sha).returncode != 0:
            err(f"  !! NOT A FAST-FORWARD: {remote}/{target} is not an ancestor of this commit.")
            err("     The push below will be REFUSED unless somebody forces it. That refusal")
            err("     is the correct outcome of pushing a tip you did not mean.")
    else:
        out(f"  RANGE         {remote}/{target} not known locally — pushing a new branch")
    sys.stdout.flush()
    pinned = subprocess.run(
        ["git", "-C", str(pm_push), "checkout", "-q", "--detach", sha], check=False
    )
    if pinned.returncode != 0:
        raise Died(NOTHING_PUSHED, f"pm_push: could not pin {pm_push} to {sha}")
    out(f"  pinned        {short(pm_push, 'HEAD')}")
    out(f"pm_push: pushing {sha} -> {remote}/{target}")
    return push_run(pm_push, remote, f"{sha}:refs/heads/{target}")


# --- --bank: the fold, the docs-only road, then one of the two arms -----------------------------

BANK_NOTHING = "Nothing was banked, nothing was pinned and nothing was pushed."
LIES = """\
pm_push --bank: a commit says [docs-only] and its own diff is not docs-only:
{lies}
   A subject is a claim a reader trusts; one that lies is refused rather than
   banked under. Reword the subject (git commit --amend, or a rebase of the
   line) or move the path out of the commit, then bank again."""
MAC_ARM = """\
  This is the full gate: two whole-suite passes, the supply chain, the canary
  self-test and every shell refusal drive. It takes the machine-wide lease and
  EVERY pytest slot on this box, so every other full gate waits behind it AND
  every builder's --loop waits for this run's pytest passes, naming this bank.
  DJB_BANK_SHARES_SLOTS=1 takes one slot instead and shares the box.
  --on-boxes N runs the same units on N verifier boxes and takes neither.
  A red one stops here: nothing is pinned and nothing is pushed."""


class Exited(Exception):
    """A measuring child's own exit, its sentences already printed."""

    def __init__(self, rc: int) -> None:
        super().__init__(rc)
        self.rc = rc


class Red(Exception):
    """Exit 1 in `gate_finding`'s shape: `RED: <headline>`, its lines indented."""

    def __init__(self, headline: str, *lines: str) -> None:
        super().__init__(headline)
        self.headline = headline
        self.lines = lines


def _claims_base(root: Path, sha: str) -> str:
    """The remote's branch when it is an ancestor of `sha`, else '' (the walk's depth)."""
    ref = f"refs/remotes/{_env('DJB_PUSH_REMOTE', 'origin')}/{_env('DJB_PUSH_BRANCH', 'main')}"
    if git(root, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
        return ""
    return ref if git(root, "merge-base", "--is-ancestor", ref, sha).returncode == 0 else ""


def _run_reader(root: Path, gate: Path, reader: str) -> int:
    """A drive by its own path from the checkout root, or `check.sh --leg <reader>`: its exit."""
    argv = [f"./{reader}"] if "/" in reader else [str(gate), "--leg", reader]
    sys.stdout.flush()
    return subprocess.run(argv, cwd=root, stdin=subprocess.DEVNULL, check=False).returncode


def docs_only_road(root: Path, gate: Path, sha: str) -> bool:
    """True with the reuse row banked; False when an arm must measure; `Red` on a red reader."""
    if os.environ.get("DJB_BANK_MEASURE", "0") not in ("", "0"):
        out("pm_push --bank: docs-only reuse SKIPPED by DJB_BANK_MEASURE — measuring.")
        out("")
        return False
    t0 = int(time.time())
    lies = ledger.docs_only_claims(root, sha, _claims_base(root, sha))
    if lies:
        listed = "\n".join(f"     {c[:12]}  {p}" for c, p in lies)
        raise Died(NOTHING_PUSHED, LIES.format(lies=listed))
    try:
        plan = ledger.docs_only_plan(root, sha)
    except ledger.DocsOnlyRefused as no:
        out(f"pm_push --bank: {no}")
        out("")
        return False
    out(f"pm_push --bank: docs-only? yes — {plan.n} path(s) changed since the")
    out(f"  measured tree {plan.source}, every one of them on the declared list.")
    out("  readers, DERIVED from what those paths are read by:")
    for reader in plan.readers:
        out(f"    {reader}")
    took = 0
    for reader in plan.readers:
        r0 = int(time.time())
        rc = _run_reader(root, gate, reader)
        took += int(time.time()) - r0
        out(f"  reader {reader}: {int(time.time()) - r0}s (exit {rc})")
        if rc == 1:
            raise Red(
                f"pm_push --bank: docs-only readers RED: {reader}.",
                "That is a red tree and not a cheaper road: NO ROW was written, nothing",
                "was pinned and nothing was pushed. Fix it and run the bank again.",
            )
        if rc != 0:
            out(f"pm_push --bank: could not look — {reader} exited {rc} — full bank.")
            out("  2 is enforcement broken, and a reuse resting on a reader that could not")
            out("  look would be a green nobody measured.")
            out("")
            return False
    try:
        tree = ledger.measured_tree(root)
    except (ledger.Mismatch, OSError):
        raise Died(
            NOTHING_PUSHED, "pm_push: could not read the measured tree for the docs-only row"
        ) from None
    readers = ",".join(plan.readers)
    try:
        sanction = ledger.Sanction(
            "docs-only", "pm_push", f"from={plan.source} paths={plan.n} readers={readers}"
        ).check()
    except ledger.Refused:
        raise Died(
            NOTHING_PUSHED,
            "pm_push: the docs-only row's sanction would not set — nothing was written and"
            " nothing was pushed.",
        ) from None
    try:
        ledger.record_full(
            root, tree=tree, legs=plan.legs, caller="pm-bank", sanction=sanction, proof=plan.proof
        )
    except (ledger.Refused, ledger.Mismatch, OSError):
        raise Died(
            NOTHING_PUSHED,
            "pm_push: the verdict ledger could not be written. Every reader was green and\n"
            "   nothing was pushed: a green nobody can read is not a verdict.",
        ) from None
    t1 = int(time.time())
    out(f"pm_push --bank: docs-only reuse of {plan.source} — readers {took} s, total {t1 - t0} s")
    out(f"  source + delta + row: {t1 - t0 - took} s")
    out(f"  verdict banked for tree {tree}")
    out(f"  caller=pm-bank sanction={sanction.field().removeprefix('sanction=')}")
    out(f"  legs={plan.legs}")
    if plan.proof:
        out(f"  leak-proof={plan.proof}")
    out("  The pre-push hook will honour it and cost seconds.")
    out("")
    return True


def bank(root: Path, args: Args) -> int:
    """`--bank`: fold, re-read HEAD, refuse dirt, the docs-only road, an arm, then pin and push."""
    pm_push = pm_push_worktree(root)
    gate = root / "scripts" / "check.sh"
    if not (gate.is_file() and os.access(gate, os.X_OK)):
        raise Died(
            NOTHING_PUSHED, f"pm_push: no executable gate at {gate} — there is nothing to bank with"
        )
    with contextlib.chdir(root):
        rc = ledger.bank_arm(root, who="pm_push --bank", no_fold=args.no_fold, nothing=BANK_NOTHING)
    if rc != 0:
        return rc
    sha = head(root)
    if not sha:
        raise Died(NOTHING_PUSHED, "pm_push: could not re-read HEAD after the fold")
    if not args.no_fold:
        out(f"pm_push --bank: banking the POST-FOLD HEAD {short(root, sha)}.")
    out("")
    if dirt(root):
        raise _dirty_refusal(
            root,
            f"pm_push --bank: {root} has uncommitted changes.",
            "A banked verdict is keyed on the tree the gate measured, and that tree",
            "would not be the one this push carries. Commit or stash first.",
            BANK_NOTHING,
        )
    require_current_reference(root)
    if not docs_only_road(root, gate, sha):
        mac_or_boxes(root, gate, args)
    return pin_and_push(root, pm_push, sha)


def mac_or_boxes(root: Path, gate: Path, args: Args) -> None:
    """The arm that measures: `--on-boxes` on verifier boxes, else this Mac's full gate."""
    if args.on_boxes:
        from quality.djb.rituals.push_boxes import on_boxes

        rc = on_boxes(root, gate, int(args.on_boxes), args.leak_proof)
        if rc != 0:
            err(f"!! pm_push --bank --on-boxes: the composed gate exited {rc}.")
            err("   2 is enforcement broken or a shard nobody could read, 1 is a red tree;")
            err("   neither is a tree to push, and no row was written for either.")
            err("   Nothing was pinned and nothing was pushed.")
            raise Exited(rc)
        out("")
    else:
        out(f"pm_push: banking a verdict for {root} before the push — {gate} --bank")
        out(MAC_ARM)
        sys.stdout.flush()
        rc = subprocess.run([str(gate), "--bank"], cwd=root, check=False).returncode
        if rc != 0:
            err(f"!! pm_push --bank: the full gate exited {rc}.")
            err("   2 is enforcement broken, 1 is a red tree; neither is a tree to push.")
            err("   Nothing was pinned and nothing was pushed.")
            raise Exited(rc)
        out("pm_push: verdict banked. The pre-push hook will honour it and cost seconds.")
        out("")


# --- --proof: the whole suite twice under one seed, the map, the record ------------------------

#: The workers each pass runs at, on the nightly runner and on the acceptance box.
PROOF_WORKERS = "16"


def leak_proof_verdict(p1: str, p2: str, seed: str, workers: str) -> str:
    """One line naming what the two statuses mean and the command that replays them."""
    if p1 == "0" and p2 == "0":
        return f"leak proof: GREEN - pass 1 and pass 2 both passed under seed {seed}"
    if p1 == "0":
        return (
            "pass 2 red after a green pass 1 — candidate causes: state pass 1 left behind, the"
            f" wall clock, test order; replay: ./scripts/pm_push.sh --proof --seed {seed}"
            f" --workers {workers}"
        )
    if p1 == "-":
        return (
            f"leak proof: COULD NOT LOOK - the collection failed and neither pass ran (seed {seed})"
        )
    return (
        f"pass 1 red (exit {p1}; pass 2 exit {p2}) — the suite is red before a second pass could"
        f" say anything about a leak; replay: ./scripts/test.sh -n {workers} --randomly-seed={seed}"
    )


def _decimal(value: str) -> bool:
    return value.isascii() and value.isdigit() and (value == "0" or value[0] != "0")


def _proof_out(root: Path, given: str) -> Path:
    """`--out` made and resolved, or a fresh directory; never inside the checkout."""
    if given:
        try:
            Path(given).mkdir(parents=True, exist_ok=True)
            where = Path(given).resolve()
        except OSError:
            raise Died(NOTHING_PUSHED, f"pm_push: could not make --out {given}") from None
    else:
        where = Path(tempfile.mkdtemp(prefix="djb-leak-proof."))
    if f"{where}/".startswith(f"{root.resolve()}/"):
        raise Died(
            NOTHING_PUSHED,
            f"pm_push: --proof --out {where} is inside {root}. A measurement may not dirty the"
            " tree it\n   measured: the map and the record are written OUTSIDE the checkout,"
            " always.",
        )
    return where


def _suite(root: Path, log: Path, argv: list[str], env: dict[str, str] | None = None) -> int:
    with log.open("w") as sink:
        return subprocess.run(
            argv, cwd=root, stdout=sink, stderr=subprocess.STDOUT, env=env, check=False
        ).returncode


def proof(root: Path, args: Args) -> int:
    """`--proof`: 0 both passes green · 1 a pass red · 2 could not look; a record on every one."""
    opts = args.proof or {}
    workers = opts.get("--workers") or _env("DJB_BANK_PROOF_WORKERS", PROOF_WORKERS)
    if not (_decimal(workers) and workers != "0"):
        raise Died(
            NOTHING_PUSHED,
            f"pm_push: --proof --workers takes a whole number above zero, got '{workers}'.",
        )
    where, run, attempt = opts["--where"], opts["--run"], opts["--attempt"]
    if where not in ("nightly", "acceptance"):
        raise Died(
            NOTHING_PUSHED, f"pm_push: --proof --where takes nightly or acceptance, got '{where}'."
        )
    if not (_decimal(run) and _decimal(attempt)):
        raise Died(
            NOTHING_PUSHED,
            "pm_push: --proof --run and --attempt take decimals (the workflow's run id and"
            f" attempt), got '{run}' '{attempt}'.",
        )
    if where == "nightly" and "0" in (run, attempt):
        raise Died(
            NOTHING_PUSHED,
            "pm_push: --proof --where nightly names the workflow run that is writing it:"
            " --run ${{ github.run_id }} --attempt ${{ github.run_attempt }}.",
        )
    seed = opts.get("--seed") or str(random.randrange(32768 * 32768))  # noqa: S311 — a pytest-randomly order seed, not crypto
    if not (seed.isascii() and seed.isdigit()):
        raise Died(NOTHING_PUSHED, f"pm_push: --proof --seed takes a decimal, got '{seed}'.")
    out_dir = _proof_out(root, opts.get("--out", ""))
    commit = head(root)
    if not commit:
        raise Died(NOTHING_PUSHED, f"pm_push: could not read HEAD in {root}")
    try:
        tree = ledger.measured_tree(root)
    except (ledger.Mismatch, OSError):
        raise Died(NOTHING_PUSHED, f"pm_push: could not read the measured tree of {root}") from None
    for stale in out_dir.glob("impact.coverage*"):
        stale.unlink(missing_ok=True)
    for name in (ledger.NIGHTLY_RECORD, "test_impact.json", "map.log"):
        (out_dir / name).unlink(missing_ok=True)
    out(f"pm_push --proof: the whole suite twice under one seed, and the map (where={where})")
    out(f"  checkout      {root}")
    out(f"  commit        {commit}")
    out(f"  tree          {tree} (measured)")
    out(f"  seed          {seed}")
    out(f"  workers       {workers}")
    out(f"  out           {out_dir}")
    t0 = t1 = t2 = int(time.time())
    p1 = p2 = map_ = "-"
    test = "./scripts/test.sh"
    collected = _suite(
        root, out_dir / "collected.txt", [test, "--collect-only", "-q", "-p", "no:randomly"]
    )
    if collected != 0:
        rc = 2
        err(
            f"!! pm_push --proof: the collection exited {collected} ({out_dir}/collected.txt);"
            " neither pass ran."
        )
    else:
        cov = dict(os.environ, COVERAGE_FILE=str(out_dir / "impact.coverage"))
        p1 = str(
            _suite(
                root,
                out_dir / "pass1.log",
                [test, "-n", workers, f"--randomly-seed={seed}", "--cov=apps", "--cov=config"]
                + ["--cov-context=test", "--cov-report="],
                cov,
            )
        )
        t1 = int(time.time())
        map_ = "2"
        if p1 == "0":
            map_ = str(
                _suite(
                    root,
                    out_dir / "map.log",
                    [".venv/bin/python", "scripts/test_impact.py", "write", "--coverage"]
                    + [str(out_dir / "impact.coverage"), "--collected"]
                    + [str(out_dir / "collected.txt"), "--root", ".", "--out"]
                    + [str(out_dir / "test_impact.json")],
                )
            )
        p2 = str(
            _suite(root, out_dir / "pass2.log", [test, "-n", workers, f"--randomly-seed={seed}"])
        )
        t2 = int(time.time())
        rc = 0 if p1 == p2 == "0" else 1
    at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        line = ledger.nightly_line(
            [at, commit, tree, seed, p1, p2, map_, str(rc), run, attempt, where]
        )
    except ledger.Refused as no:
        err(str(no))
        raise Died(
            NOTHING_PUSHED,
            "pm_push: the leak-proof record would not parse (above) — none was written, and a"
            " proof with no record proves nothing.",
        ) from None
    record = out_dir / ledger.NIGHTLY_RECORD
    record.write_text(f"{line}\n")
    out(
        f"{where}: pass1 (contexts) {t1 - t0}s · pass2 (plain) {t2 - t1}s rc1={p1} rc2={p2}"
        f" map={map_}"
    )
    out(line)
    log = out_dir / "map.log"
    if log.is_file() and log.stat().st_size:
        sys.stdout.write(log.read_text(errors="replace"))
    out(leak_proof_verdict(p1, p2, seed, workers))
    out(f"  record        {record}")
    impact = out_dir / "test_impact.json"
    if impact.is_file() and impact.stat().st_size:
        out(f"  map           {impact}")
    return rc


# --- the entry --------------------------------------------------------------------------------


def _root() -> Path:
    """The checkout the operator stands in, or exit 2."""
    done = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise Died(NOTHING_PUSHED, "pm_push: not inside a git checkout")
    return Path(done.stdout.strip())


def run(argv: Sequence[str]) -> int:
    """Parse, resolve the checkout and the commit, then the one mode the operator asked for."""
    args = parse(argv)
    if args.mode == "help":
        sys.stdout.write(USAGE)
        return 0
    root = _root()
    if not head(root):
        raise Died(NOTHING_PUSHED, f"pm_push: 'HEAD' is not a commit in {root}")
    if args.mode == "pr":
        return pr(root, args)
    if args.mode == "ci-verdict":
        return ci_verdict(root, args)
    if args.mode == "bank":
        return bank(root, args)
    # deleted: the "still scripts/pm_push.sh's" refusal — every mode `parse` yields has its arm
    # pin: quality/tests/test_push.py::test_every_mode_the_parser_yields_reaches_its_own_arm
    return proof(root, args)


@road(
    "push",
    example="quality/tests/test_push.py::test_pr_pushes_a_train_branch_on_an_intent_and_the_wall_says_so",  # noqa: E501
)
def main(argv: Sequence[str] | None = None) -> int:
    """`push --pr [--no-fold] | --ci-verdict [R] | --bank [--on-boxes N] [--no-fold] | --proof`."""
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except Died as died:
        err(f"!! {died.headline}")
        indented(*died.lines)
        if died.trailer:
            indented(died.trailer)
        return 2
    except Exited as exited:
        return exited.rc
    except Red as red:
        err(f"RED: {red.headline}")
        indented(*red.lines)
        return 1
    except Printed:
        return 2
    except CouldNotLook as cannot:
        err(f"!! COULD NOT LOOK: {cannot}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
