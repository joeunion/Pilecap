"""The push's fork point and its depth-limited mirror: what leaves for the box, one ref per push."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

from quality.djb.box.core import Box, drop_tree, vb_log
from quality.djb.box.transport import BAKE_SH, ROOT, Refused, die, spawn, verifier_box_user, warn

_PARK = re.compile(r'BAKE_PARK_BRANCH="(.*)"')
MAX_SCOPE_DEPTH_DEFAULT = "200"
KEEPALIVES = "-o ServerAliveInterval=30 -o ServerAliveCountMax=120"


def git(env: dict[str, str], *args: str, quiet: bool = True) -> tuple[int, str]:
    """`git <args>`: its status and stdout less trailing newlines; stderr dropped when `quiet`."""
    with tempfile.TemporaryFile("w+") as out, open(os.devnull, "w") as null:
        rc = spawn(["git", *args], env=env, stdout=out, stderr=null if quiet else None).returncode
        out.seek(0)
        return rc, out.read().rstrip("\n")


def git_status(env: dict[str, str], *args: str) -> int:
    """`git <args> >/dev/null 2>&1`: the status alone."""
    with open(os.devnull, "w") as null:
        return spawn(["git", *args], env=env, stdout=null, stderr=null).returncode


def verifier_park_branch() -> str:
    """The box's parking branch, `bake.sh`'s `BAKE_PARK_BRANCH`, the one place it is written."""
    if not os.access(BAKE_SH, os.R_OK):
        die(
            f"verifier_box: cannot read {BAKE_SH}, and it is the ONE place the box's parking\n"
            "   branch is written down."
        )
    lines = BAKE_SH.read_text().splitlines()
    park = next((m.group(1) for m in map(_PARK.fullmatch, lines) if m), "")
    if not park:
        die(
            f"verifier_box: could not read BAKE_PARK_BRANCH out of {BAKE_SH}. Its shape is the\n"
            "   contract this script reads; if it changed, this is the line that changes with it."
        )
    return park


def fork_point(env: dict[str, str], head_sha: str, head_ref: str, main_sha: str) -> tuple[str, str]:
    """The fork point that travels as `refs/djb/base` and where it came from; ('', '') for none."""
    _, declared = git(env, "-C", str(ROOT), "rev-parse", "-q", "--verify", "refs/djb/base^{commit}")
    if (
        declared
        and declared != head_sha
        and not git_status(env, "-C", str(ROOT), "merge-base", "--is-ancestor", declared, "HEAD")
    ):
        return declared, "refs/djb/base, declared in this checkout"
    if not main_sha:
        return "", ""
    _, base = git(env, "-C", str(ROOT), "merge-base", "HEAD", "refs/heads/main")
    base_from = "merge-base HEAD refs/heads/main" if base else ""
    if base == head_sha:
        base, base_from = "", ""
    if (
        not base
        and main_sha != head_sha
        and git_status(
            env, "-C", str(ROOT), "merge-base", "--is-ancestor", "HEAD", "refs/heads/main"
        )
    ):
        for line in (
            f"!! verifier_box: HEAD ({head_ref} {head_sha[:8]}) has commits past this checkout's"
            " main",
            f"   ({main_sha[:8]}) and no fork point can be derived: no refs/djb/base is declared",
            "   and `git merge-base HEAD refs/heads/main` answers nothing. The box's --loop",
            "   would derive an EMPTY scope for this tree. Nothing was pushed.",
            "   Declare the commit this tree forked from, then push again:",
            "     git update-ref refs/djb/base <sha>",
            "   (in a clone of its own — a linked worktree shares refs/djb/base with its",
            "   whole family; scripts/verify_start.sh writes it into every verify clone)",
        ):
            warn(line)
        raise Refused(printed=True)
    return base, base_from


def _max_scope_depth(env: dict[str, str]) -> int:
    raw = env.get("DJB_VERIFIER_MAX_SCOPE_DEPTH") or MAX_SCOPE_DEPTH_DEFAULT
    if not raw.isdigit():
        die(f"verifier_box: DJB_VERIFIER_MAX_SCOPE_DEPTH must be a whole number, got '{raw}'")
    return int(raw)


def push_the_tree_shallow(
    box: Box, instance: str, head_sha: str, checkout: str, base_sha: str, refs: Sequence[str]
) -> int:
    """Build a mirror deep enough for the fork point, prepare the box, push one ref per push."""
    env = box.cfg.env
    shallow = box.cfg.home / f".shallow-{os.getpid()}"
    drop_tree(shallow)
    box.cfg.home.mkdir(parents=True, exist_ok=True)
    if git_status(env, "init", "-q", "--bare", str(shallow)):
        die(f"verifier_box: could not make the shallow mirror at {shallow}")
    fetch_refs = ["+HEAD:refs/heads/main"]
    for ref in refs:
        if ref != "refs/heads/main:refs/heads/main":
            source = ref.split(":", 1)[0]
            fetch_refs.append(f"+{source}:{source}")
    depth, span = 1, ""
    if base_sha:
        _, span = git(env, "-C", str(ROOT), "rev-list", "--count", f"{base_sha}..HEAD")
        span = span if span.isdigit() else ""
        if span and int(span) <= _max_scope_depth(env):
            depth = int(span) + 1
        else:
            ceiling = _max_scope_depth(env)
            vb_log(
                f"note       the rung is {span or '?'} commits from its fork point (ceiling"
                f" {ceiling}); the base is",
                err=True,
            )
            vb_log(
                "           NOT being carried and the box's --loop will derive an empty scope",
                err=True,
            )
            base_sha = ""
    fetch = ["-C", str(shallow), "fetch", "-q", "--depth", str(depth), f"file://{ROOT}"]
    if spawn(["git", *fetch, *fetch_refs], env=env).returncode:
        drop_tree(shallow)
        die(
            f"verifier_box: could not build a depth-{depth} mirror of this checkout."
            " Nothing was pushed."
        )
    if base_sha and git_status(env, "-C", str(shallow), "update-ref", "refs/djb/base", base_sha):
        vb_log(
            f"note       the fork point {base_sha[:8]} is not in the mirror; the box's --loop will",
            err=True,
        )
        vb_log("           derive an empty scope", err=True)
        base_sha = ""
    _, got = git(env, "-C", str(shallow), "rev-parse", "refs/heads/main")
    if got != head_sha:
        drop_tree(shallow)
        die(
            f"verifier_box: the depth-1 mirror landed on {got or '<nothing>'} and this checkout's"
            " HEAD is\n"
            f"   {head_sha}. Nothing was pushed: the tree the pre-push hook vouched for is\n"
            "   not the tree that would have gone."
        )
    prepare_the_receiver(box, instance, checkout)
    push_order = (["refs/djb/base:refs/djb/base"] if base_sha else []) + list(refs)
    ssh_cmd = (
        f"ssh -i '{box.box_key(instance)}' -o 'ProxyCommand={box.proxy_command()}'"
        " -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
        f" {KEEPALIVES}"
    )
    target = f"ssh://{verifier_box_user()}@{instance}{checkout}"
    prc, sent, one_ref = 0, "", ""
    for one_ref in push_order:
        prc = spawn(
            ["git", "-C", str(shallow), "push", "--force", target, one_ref],
            env={**env, "GIT_SSH_COMMAND": ssh_cmd},
        ).returncode
        if prc:
            break
        sent = f"{sent} {one_ref}" if sent else one_ref
    drop_tree(shallow)
    if prc:
        transfer_failed(prc, instance, checkout, one_ref, sent)
        return prc
    pushed = " ".join(push_order)
    if base_sha:
        vb_log(
            f"pushed {pushed} to {instance}:{checkout} (depth {depth}: the tree and the rung's"
            f" own {span} commit(s), not the history; one push per ref)"
        )
    else:
        vb_log(f"pushed {pushed} to {instance}:{checkout} (depth-1: the tree, not the history)")
    return 0


def prepare_the_receiver(box: Box, instance: str, checkout: str) -> None:
    """Allow a shallow update on the box; on this checkout's first push, clear its three refs."""
    park = verifier_park_branch()
    marker = box.box_dir(instance) / "pushed-from"
    prep = f"git -C {checkout} config receive.shallowUpdate true"
    clearing = str(ROOT) not in _lines(marker)
    if clearing:
        prep = (
            f"git -C {checkout} update-ref -d refs/heads/main; git -C {checkout} update-ref -d"
            f" refs/heads/{park}; git -C {checkout} update-ref -d refs/djb/base; {prep}"
        )
        marker.parent.mkdir(parents=True, exist_ok=True)
        with marker.open("a") as handle:
            handle.write(f"{ROOT}\n")
    rc, _ = box.ssh_capture(instance, f"{prep}; true")
    if rc == 0:
        if clearing:
            vb_log(
                f"cleared    the box's main, {park} and refs/djb/base before the first push from"
                " this checkout — a receiver that advertises nothing is assumed to have nothing,"
                " and a shallow box that advertises its bake commit is not",
                err=True,
            )
    elif clearing:
        for line in (
            f"note       could not prepare {instance} for a shallow push — receive.shallowUpdate,"
            " or the",
            "           ref clear, or both. If the push below is refused for 'shallow update not",
            "           allowed', or fails with unresolved deltas / missing necessary objects,",
            "           that is why.",
        ):
            vb_log(line, err=True)
    else:
        vb_log(
            f"note       could not set receive.shallowUpdate on {instance}; a shallow push may be"
            " refused",
            err=True,
        )


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except OSError:
        return []


def transfer_failed(prc: int, instance: str, checkout: str, one_ref: str, sent: str) -> None:
    """The failed transfer's reading on stderr: a 141 named for what it is, else the four shapes."""
    if prc == 141:
        lines = [
            "!! verifier_box: git took SIGPIPE (exit 141) writing the pack — the transport",
            "   died before the pack was written. git opens this connection FIRST and",
            "   writes the pack LAST, so anything slow in between is an idle tunnel.",
            "   Nothing refused: the wall on this machine ran BEFORE the tunnel was opened",
            "   and passed. This is the transport. Try again; if it repeats, the tunnel is",
            "   the thing to look at — 'census' prints the image each box is running.",
        ]
    else:
        lines = [
            f"!! verifier_box: the transfer failed (git exit {prc}). FOUR THINGS LOOK LIKE THIS,",
            "   and git's own words above tell them apart:",
            "     THE RECEIVER REFUSED A SHALLOW HISTORY — 'shallow update not allowed'. The",
            "     pack sent here is a depth-1 mirror, and a repository that has not set",
            "     receive.shallowUpdate rejects it. This wrapper sets that config over the",
            "     transport before every push; if the line above says it could not, that is",
            "     the thing to fix and the box is otherwise fine.",
            "     THE TRANSPORT DIED mid-pack — 'the remote end hung up', a 'Broken pipe', a",
            "     'write error', or the tunnel's own death. Retry; a tunnel that keeps doing",
            "     it is a finding about the tunnel, not about this tree.",
            "     THE REMOTE END REFUSED THE REF — a non-fast-forward or a checked-out branch.",
            "     The box's repository parks itself off main for exactly that reason; a box",
            "     sitting ON main needs receive.denyCurrentBranch=updateInstead, which its",
            "     own user-data sets.",
            "     THE BOX IS SHALLOW AND STILL ADVERTISING ITS OWN REFS — 'pack has N",
            "     unresolved deltas' with 'index-pack abnormal exit', or 'Could not read",
            "     <sha>' with 'missing necessary objects'. A push omits whatever the",
            "     receiver's advertised refs imply it already has, and a freshly baked box",
            "     is shallow at its bake commit and has none of that commit's ancestors.",
            "     This wrapper clears the box's main, its parking branch and refs/djb/base",
            "     before the FIRST push from each checkout; if the line above says it could",
            "     not, that is the thing to fix. By hand, once, then push again:",
            f'       scripts/verifier_box.sh run {instance} -- "cd {checkout} && git update-ref -d'
            " refs/heads/main && git update-ref -d refs/heads/$(sed -n"
            ' \'s|^BAKE_PARK_BRANCH="\\(.*\\)"$|\\1|p\' deploy/verifier/bake.sh)"',
            "     --no-thin does NOT fix this: thin packs govern delta bases, the omission",
            "     is driven by the advertised refs. Measured both ways in test_verifier_box.sh.",
            "   The wall on THIS machine already passed: it ran before the tunnel was opened.",
        ]
    lines.append(f"   THE REF THAT FAILED: {one_ref}.")
    if sent:
        lines.append(f"   Already landed on the box before it: {sent}.")
    else:
        lines.append("   Nothing landed on the box: this was the first ref sent.")
    for line in lines:
        warn(line)
