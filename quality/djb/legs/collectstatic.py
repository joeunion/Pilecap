"""The `collectstatic` leg: the manifest storage resolves every reference under production."""

from __future__ import annotations

import shutil
import tempfile

from quality.djb.legs._run import say, tool
from quality.djb.legs._throwaway import production_env
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "manage.py", "collectstatic", "--noinput", "--clear"),)


def run(ctx: Ctx) -> int:
    """`collectstatic` into a scratch `STATIC_ROOT` this leg owns and removes; a failure is 1."""
    root = tempfile.mkdtemp(prefix="djb-collectstatic.")
    try:
        rc = tool(ctx, ARGV[0], {**production_env(), "STATIC_ROOT": root})
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if rc:
        say(
            f"RED: collectstatic failed (exit {rc}) under production settings.",
            "   The compressed MANIFEST storage resolves every reference inside every",
            "   file it post-processes, so this is usually a url() in a stylesheet",
            "   naming a file that is not in any STATICFILES_DIRS or app static dir.",
            "   It is a 500 on the admin in production and it shows up in no other leg.",
        )
        return 1
    return 0


LEG = Leg(
    "collectstatic",
    "static",
    "collectstatic under production settings (the compressed manifest storage resolves every "
    "reference), into a scratch STATIC_ROOT this leg owns",
    run,
    "fe",
    frozenset({"full"}),
    ARGV,
)
