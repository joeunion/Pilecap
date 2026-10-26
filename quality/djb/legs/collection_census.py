"""The `collection-census` leg: every `quality/tests` module imports with no app registry."""

# Invariant: stdlib only at import (the registry's system python); `main` runs in the venv.

# does-not-cover: a registry need reached only when a test RUNS, never at import.

from __future__ import annotations

import sys
import time

from quality.djb.legs._run import CAUSE, callee, checkout_python, could_not_look, say
from quality.djb.registry import Ctx, Leg

ARGV = (("<checkout python>", "-m", "quality.djb.legs.collection_census"),)
#: What CI's legs job exports to the selftest shards (ci.yml `env:`, its `$GITHUB_ENV` writes).
CI_ENV = {
    "PYTHON_VERSION": "3.12",
    "PYTEST_SHARDS": "3",
    "DATABASE_HOST": "127.0.0.1",
    "DATABASE_PORT": "5432",
    "DATABASE_USER": "djb",
    "DATABASE_PASSWORD": "djb",  # pragma: allowlist secret — the published compose dev password
    "DATABASE_NAME": "djb_collection_census",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "CACHE_URL": "redis://127.0.0.1:6379/1",
    "BRAND_ACCENT": "#3f4a5a",
    "EMAIL_HOST": "127.0.0.1",
    "EMAIL_PORT": "1025",
    "SERVER_EMAIL": "no-reply@localhost",
    "DJB_STACK_REGISTRY": "",
    "ZITADEL_ISSUER": "http://localhost:8081",
    "ZITADEL_PAT": "census-placeholder",
}


def main() -> int:
    """The census's own scan over `quality/tests`: one line per refused module; 0 · 1 · 2."""
    from quality.could_not_look import CouldNotLook
    from quality.tests import test_registry_free_collection as census
    from quality.tests.test_registry_free_collection import module_names, named, registry_needers

    withheld = census.withheld_env
    census.withheld_env = lambda root: {**withheld(root), **CI_ENV}
    t0 = time.monotonic()
    names = module_names()
    try:
        if not names:
            raise CouldNotLook("no module under quality/tests was found to import")
        found = registry_needers(names)
    except CouldNotLook as cannot:
        print(f"!! collection-census: could not look — {cannot}", file=sys.stderr)
        return 2
    for line in named(found).splitlines() if found else ():
        print(f"!! collection-census: {line}")
    print(
        f"== collection-census: {len(found)} refused of {len(names)} module(s) · "
        f"{time.monotonic() - t0:.2f}s"
    )
    return 1 if found else 0


def run(ctx: Ctx) -> int:
    """`python -m quality.djb.legs.collection_census`: 1 a module needs the registry; 2 unread."""
    py = checkout_python(ctx.root)
    if py is None:
        return could_not_look(
            ctx,
            "the collection census could not run: this checkout has no .venv/bin/python",
            "!! the collection census could not run: this checkout has no .venv/bin/python",
            "   Run ./scripts/setup.sh (or `uv sync`) first.",
        )
    rc, cause = callee(ctx, (str(py), *ARGV[0][1:]))
    if rc == 2:
        return could_not_look(
            ctx,
            cause,
            "!! the collection census COULD NOT LOOK — see above. Nothing was judged.",
            CAUSE,
        )
    if rc:
        say(
            "!! each `!! collection-census:` module above imports the app registry at collection;",
            "   CI's selftest shards run with DJANGO_SETTINGS_MODULE unset and would die there.",
            "   Move the Django import inside the test or its fixture.",
        )
    return rc


LEG = Leg(
    "collection-census",
    "static",
    "the registry-free collection census — every quality/tests module imports with "
    "DJANGO_SETTINGS_MODULE unset and the checkout's .env withheld, as CI's selftest shards do",
    run,
    "ci-env",
    argv=ARGV,
)


if __name__ == "__main__":
    raise SystemExit(main())
