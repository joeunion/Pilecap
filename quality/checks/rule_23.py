"""Rule 23: supply chain (secret patterns; the tool legs live in the supply-chain leg)."""

from __future__ import annotations

import re
from pathlib import Path

from quality.checks._hub import CheckResult, _read

# --- rule 23: supply chain (secret patterns; the tool legs live in the supply-chain leg) --

#: The leg module that runs the three tools once `check.sh` is the shim.
SUPPLY_CHAIN_LEG = "quality/djb/legs/supply_chain.py"

_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "an AWS access key id"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "a private key block"),
    (re.compile(r"xox[bpoas]-[0-9A-Za-z-]{10,}"), "a Slack token"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "a GitHub personal access token"),
]


def supply_chain(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for sub in ("apps", "config", "scripts"):
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix in (".pyc", ".sqlite3"):
                continue
            if "__pycache__" in path.parts:
                continue
            text = _read(path)
            if not text:
                continue
            out.count("files_scanned")
            rel = str(path.relative_to(root))
            for pattern, what in _SECRET_PATTERNS:
                m = pattern.search(text)
                if m:
                    line = text[: m.start()].count("\n") + 1
                    out.hit(
                        rel,
                        line,
                        f"{what} in the tree — secrets live in the environment, never the repo",
                    )
    pyproject = _read(root / "pyproject.toml")
    for tool in ("pip-audit", "pip-licenses", "detect-secrets"):
        if tool not in pyproject:
            out.hit(
                "pyproject.toml",
                1,
                f"{tool} is not a declared dev dependency — the supply-chain legs have nothing "
                "to run",
            )
    gate = _read(root / "scripts" / "check.sh") + _read(root / SUPPLY_CHAIN_LEG)
    if gate:
        for tool in ("pip-audit", "pip-licenses", "detect-secrets"):
            if tool not in gate:
                out.hit(SUPPLY_CHAIN_LEG, 1, f"the {tool} leg is missing from the full gate")
    if not (root / ".secrets.baseline").exists():
        out.hit(
            ".secrets.baseline",
            1,
            "no detect-secrets baseline — the secrets leg cannot tell new from known",
        )
    return out
