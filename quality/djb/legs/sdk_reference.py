"""The `sdk-reference` leg: `docs/sdk/` against what `python -m quality.sdk --reference` derives."""

# does-not-cover: whether a page's prose is true — the derivation's own pointers are its reach.

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from quality.djb.legs._run import CAUSE, cause_of, checkout_python, could_not_look, say
from quality.djb.registry import Ctx, Leg

HOME = "docs/sdk"
ARGV = (("<checkout python>", "-m", "quality.sdk", "--reference", "--check", "--root", "."),)
STALE = "{page} is stale — run: python -m quality.sdk --reference, then stage docs/sdk/"
_DIFFERS = re.compile(r"^reference: (\S+\.md) differs — ", re.MULTILINE)


def check(root: Path, env: Mapping[str, str] | None = None) -> tuple[int, list[str], str]:
    """`--reference --check` over `root`: its exit, the stale pages' lines, and its whole text."""
    argv = [str(checkout_python(root) or sys.executable), *ARGV[0][1:]]
    try:
        done = subprocess.run(
            argv,
            cwd=root,
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 2, [], f"!! {argv[0]} could not be started: {exc}\n"
    said = f"{done.stdout or ''}{done.stderr or ''}"
    pages = _DIFFERS.findall(done.stdout or "")
    return done.returncode, [STALE.format(page=p) for p in pages], said


def run(ctx: Ctx) -> int:
    """Exit 1 naming each stale page with the one regeneration line; 2 when it could not look."""
    rc, stale, text = check(ctx.root, ctx.env)
    if rc == 2:
        sys.stdout.write(text)
        return could_not_look(
            ctx,
            cause_of(text),
            "!! THE SDK REFERENCE COULD NOT BE CHECKED — nothing was judged.",
            CAUSE,
        )
    if rc and stale:
        say(*(f"!! {line}" for line in stale))
        return 1
    if rc:
        sys.stdout.write(text)
        say("!! the SDK reference would not derive — its own lines are above.")
        return 1
    print("  sdk reference: current", flush=True)
    return 0


LEG = Leg(
    "sdk-reference",
    "static",
    "sdk reference (docs/sdk/ is what python -m quality.sdk --reference derives)",
    run,
    "ruff",
    argv=ARGV,
)
