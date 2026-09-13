"""The scope-kind declarations, read the way a RUNNER subprocess needs them.

THE SHARED HALF OF THE F1 FIX (Vra, 2026-08-31). `quality/gate.py`'s override walk and
every runner under `quality/runners/` must skip the SAME vendored directories,
or a 12k-file `node_modules` enters one census and not the other — which is
exactly what happened before this module existed: `js_secrets.py` carried its
own `SKIP_DIRS` literal, and the engine's walk knew only `__pycache__`. Both
sides now read `quality/rules.yaml`'s `scope_kinds.<kind>.skip_dirs` and
nothing else.

Deliberately NOT an import of `quality.gate` or `quality.worlds`: a runner is
its own subprocess, invoked as `python3 quality/runners/<x>.py <roots...>`
with the checkout root as its cwd (`quality/check_v1.py::invoke` sets `cwd`),
and pulling in the engine's Django-dependent world (`quality.checks`,
`quality.gate`) just to learn a skip-dir list would tie a static-analysis
runner to a settings module it has no other reason to import. This module
reads the same six lines of YAML gate.py already reads, and no more.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_RULES_YAML = "quality/rules.yaml"


def load_scope_kinds(root: Path) -> dict:
    """`scope_kinds:` from `quality/rules.yaml`, read directly."""
    doc = yaml.safe_load((root / _RULES_YAML).read_text())
    return dict((doc or {}).get("scope_kinds") or {})


def skip_dirs(root: Path, kind_name: str) -> frozenset[str]:
    """The directory names `kind_name`'s walk skips — one declaration, every reader."""
    kind = load_scope_kinds(root).get(kind_name) or {}
    return frozenset(str(d) for d in (kind.get("skip_dirs") or []))
