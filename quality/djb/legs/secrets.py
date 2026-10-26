"""The loop-only `secrets` leg: detect-secrets over the active rung's changed files and no other."""

# does-not-cover: an untracked, never-staged file — git does not name it, so nothing scans it.
# does-not-cover: every file the rung did not touch — the supply-chain leg's full-tree scan.

from __future__ import annotations

from quality.could_not_look import CouldNotLook
from quality.djb import scope
from quality.djb.legs._run import say, tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "detect-secrets-hook", "--baseline", ".secrets.baseline"),)
#: The fork point's ref when not `refs/heads/main`, and the base a depth-1 mirror carries.
BASE_REF = "SECRETS_SCAN_BASE_REF"
CARRIED = "DJB_LOOP_SCOPE_BASE"


def run(ctx: Ctx) -> int:
    """The hook's exit over the changed set; 0 when it is empty; 2 when it could not be derived."""
    try:
        changed = scope.changed_files(
            ctx.root, ctx.env.get(BASE_REF) or None, ctx.env.get(CARRIED) or None
        )
    except CouldNotLook as exc:
        say(
            f"!! {exc}",
            "!! the secret scan COULD NOT DERIVE the active rung's changed files — see above.",
            f"   cause: {exc}",
            "   An underived set is not an empty set: nothing was judged, so this is",
            "   neither a finding nor a pass.",
        )
        return 2
    print(f"  basis: {changed.basis}", flush=True)
    if not changed.paths:
        print("  NOTHING WAS SCANNED: the active rung has changed no file that git knows about.")
        print("  A leg that looked at nothing is not the same claim as a clean tree — the")
        print("  FULL-TREE scan over `git ls-files` runs at push, in the supply-chain leg.")
        return 0
    print(f"  scanning {len(changed.paths)} changed file(s) against .secrets.baseline.")
    print("  NOT scanned here: every file the active rung did not touch, and every untracked,")
    print("  never-staged file. The full-tree scan at push is what covers the first;")
    print("  nothing has ever covered the second, there or here.", flush=True)
    return tool(ctx, (*ARGV[0], *changed.paths))


LEG = Leg(
    "secrets",
    "-",
    "detect-secrets vs .secrets.baseline — THE ACTIVE RUNG'S CHANGED FILES ONLY; the full-tree "
    "scan, pip-audit and licences stay push-side",
    run,
    None,
    frozenset({"loop"}),
    ARGV,
)
