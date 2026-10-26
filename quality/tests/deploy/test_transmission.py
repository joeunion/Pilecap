"""Transmission security (164.312(e)(1)): HSTS on every edge site block; production's HTTPS.

does-not-cover: Caddy's own reading of the file — `caddy validate` is the proof, run by hand.
does-not-cover: the live header on a box — `curl -I` on staging is the field proof, not run here.
does-not-cover: a site block declared outside `deploy/Caddyfile` (`scripts/local/` included).
does-not-cover: a box's `.env` overriding a default (`SECURE_HSTS_SECONDS=0`) — the operator's.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from apps.core.tests.settings_env import PRODUCTION_ENVIRONMENT, _settings_module
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives(
    "deploy/Caddyfile",
    "config/settings/base.py",
    "config/settings/production.py",
    "config/urls.py",
    "apps/core/health.py",
)

ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
HSTS_LINE = 'header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"'
#: A site block's opener: an environment placeholder for its address, then the brace.
OPENER = re.compile(r"^(\{\$[A-Z0-9_]+\})\s*\{\s*$")
#: Floor, from the printed `site blocks: 3 ({$SITE_ADDRESS}, {$AUTH_ADDRESS}, {$O11Y_ADDRESS})`.
SITE_BLOCK_FLOOR = 3
#: The six transport keys, cleared so production is read at its own defaults.
TRANSPORT_KEYS = (
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
)
ONE_YEAR = 31_536_000
PROBE_MODULE = "apps.core.health"


def site_blocks(text: str) -> Iterator[tuple[str, list[str]]]:
    """Each `{$ADDRESS} {` block of a Caddyfile, as its address and its body's lines."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        opened = OPENER.match(line)
        if not opened:
            continue
        depth, body = 1, []
        for inner in lines[index + 1 :]:
            code = inner.split("#", 1)[0]
            depth += code.count("{") - code.count("}")
            if depth <= 0:
                break
            body.append(inner)
        yield opened.group(1), body


def blocks_without_hsts(path: Path) -> tuple[list[str], list[str]]:
    """Every site block's address, and the addresses of those carrying no HSTS header line."""
    blocks = list(site_blocks(path.read_text(encoding="utf-8")))
    missing = [name for name, body in blocks if not any(b.strip() == HSTS_LINE for b in body)]
    return [name for name, _ in blocks], missing


def test_every_site_block_carries_hsts() -> None:
    """Every site block says "only ever HTTPS", on the responses Caddy makes itself too."""
    names, missing = blocks_without_hsts(CADDYFILE)
    print(f"site blocks: {len(names)} ({', '.join(names)})")
    assert len(names) >= SITE_BLOCK_FLOOR, f"site blocks fell below the floor: {names}"
    assert missing == [], f"site blocks without `{HSTS_LINE}`: {missing}"


def test_a_planted_block_without_hsts_is_named(tmp_path: Path) -> None:
    """The census's own negative: a fourth block with no header line is printed by name."""
    scratch = require_scratch(tmp_path, ROOT)
    planted = scratch / "Caddyfile"
    planted.write_text(
        CADDYFILE.read_text(encoding="utf-8")
        + "\n{$PLANTED_ADDRESS} {\n\ttls {$CADDY_TLS}\n\treverse_proxy web:8000\n}\n",
        encoding="utf-8",
    )
    names, missing = blocks_without_hsts(planted)
    assert "{$PLANTED_ADDRESS}" in names
    assert missing == ["{$PLANTED_ADDRESS}"]


def _production(**overrides: str | None) -> Any:
    environment: dict[str, str | None] = {
        **PRODUCTION_ENVIRONMENT,
        **dict.fromkeys(TRANSPORT_KEYS),
        **overrides,
    }
    with _settings_module("config.settings.production", **environment) as production:
        return production


def transport_findings(production: Any) -> list[str]:
    """The transport settings production does not hold, each named."""
    expected: dict[str, Any] = {
        "SECURE_SSL_REDIRECT": True,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
        "SECURE_HSTS_PRELOAD": True,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
    }
    findings = [
        f"{key} is {getattr(production, key)!r}, not {value!r}"
        for key, value in expected.items()
        if getattr(production, key) is not value
    ]
    if production.SECURE_HSTS_SECONDS < ONE_YEAR:
        findings.append(f"SECURE_HSTS_SECONDS is {production.SECURE_HSTS_SECONDS}, under a year")
    return findings


def probe_exemptions() -> set[str]:
    """The probes' redirect exemptions, read from `config/urls.py` in a subprocess with Django."""
    script = (
        "import django, json, re; django.setup(); from django.urls import URLPattern; "
        "from config import urls; print(json.dumps(sorted("
        "'^' + re.escape(str(e.pattern)) + '$' for e in urls.urlpatterns "
        "if isinstance(e, URLPattern) and e.callback.__module__ == '" + PROBE_MODULE + "')))"
    )
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.test"),
    }
    out = subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True, env=env
    )
    return set(json.loads(out.stdout))


def test_production_redirects_to_https_and_pins_hsts() -> None:
    """Production at its defaults redirects to HTTPS, pins HSTS and secures its cookies."""
    production = _production()
    assert transport_findings(production) == []
    probes = probe_exemptions()
    assert probes, "no probe route found in config/urls.py"
    assert set(production.SECURE_REDIRECT_EXEMPT) == probes
    assert len(production.SECURE_REDIRECT_EXEMPT) == len(probes)


def test_a_disabled_redirect_is_named() -> None:
    """The negative: `SECURE_SSL_REDIRECT=0` in the environment is a finding naming the setting."""
    findings = transport_findings(_production(SECURE_SSL_REDIRECT="0"))
    assert [f for f in findings if f.startswith("SECURE_SSL_REDIRECT ")] == [
        "SECURE_SSL_REDIRECT is False, not True"
    ]
