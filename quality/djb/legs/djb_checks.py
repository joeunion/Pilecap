"""The `djb-checks` leg: the system checks tagged `djb`, test settings, no database."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "manage.py", "check", "--tag", "djb"),)
ENV = {"DJANGO_SETTINGS_MODULE": "config.settings.test"}


def run(ctx: Ctx) -> int:
    """`manage.py check --tag djb` under `config.settings.test`; its exit."""
    return tool(ctx, ARGV[0], ENV)


LEG = Leg(
    "djb-checks",
    "static",
    "django system checks, tag djb (settings=test, no database)",
    run,
    "import-linter",
    argv=ARGV,
)
