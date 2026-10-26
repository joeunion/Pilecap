"""The `migrations` leg: a model change whose migration was never made."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "manage.py", "makemigrations", "--check", "--dry-run"),)
ENV = {"DJANGO_SETTINGS_MODULE": "config.settings.test"}


def run(ctx: Ctx) -> int:
    """`makemigrations --check --dry-run` under test settings; one leaf per app is rule 6's."""
    return tool(ctx, ARGV[0], ENV)


LEG = Leg(
    "migrations",
    "static",
    "makemigrations --check (+ linear migrations: one leaf per app)",
    run,
    "house-rules",
    argv=ARGV,
)
