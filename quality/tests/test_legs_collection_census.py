"""The collection-census leg's worker carries every name CI's legs job exports to its shards."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from quality.djb.legs import collection_census

pytestmark = pytest.mark.drives("quality/djb/legs/collection_census.py")

ROOT = Path(__file__).resolve().parents[2]
#: A step's `NAME=… >> $GITHUB_ENV` write: the name every later step of the job inherits.
GITHUB_ENV_WRITE = re.compile(r"echo \"([A-Z_][A-Z0-9_]*)=[^\n]*>>\s*\"?\$GITHUB_ENV")


def ci_exports(root: Path = ROOT) -> set[str]:
    """The workflow's `env:` keys, the legs job's own, and every `$GITHUB_ENV` name its run sets."""
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    legs = workflow["jobs"]["legs"]
    names = set(workflow.get("env") or {}) | set(legs.get("env") or {})
    runs = [step.get("run") or "" for step in legs["steps"]]
    runs.append((root / "scripts/ci_stack.sh").read_text(encoding="utf-8"))
    for run in runs:
        names |= set(GITHUB_ENV_WRITE.findall(run))
    return names


def test_the_worker_sets_every_name_ci_exports_to_a_selftest_shard() -> None:
    exported = ci_exports()
    assert {"DATABASE_HOST", "DATABASE_NAME", "ZITADEL_ISSUER"} <= exported, exported
    missing = sorted(exported - set(collection_census.CI_ENV))
    assert not missing, (
        f"CI exports these to the selftest shards; CI_ENV does not set them: {missing}"
    )
