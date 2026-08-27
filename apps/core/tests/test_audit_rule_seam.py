"""Rule 49's two halves the canary harness cannot plant, driven directly.

A canary is a planted FILE — the harness appends a fixture to a real module and
asserts the rule fires naming that path. Two of rule 49's clauses are not
additions to a file and therefore have no fixture shape:

* **the allow-list ghost** — an entry naming a service that does not exist. It
  is the ABSENCE of a thing, and you cannot append an absence;
* **the seam consistency canary** — `apps.core.service._declares_tenant` failing
  to import. That is a removal, and appending to `apps/core/service.py` cannot
  cause it (nor should any fixture try: breaking that import breaks every other
  rule's canary in the same run).

So both are driven here, against the real check, with a synthetic rule dict.
The rule's own text points at this module by name so the coverage is stated
rather than assumed — and `selftest_floor` records four canaries rather than
six for the same reason: a number that counted these would be a number the
harness could not prove.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

#: Reached through `importlib` rather than imported at the top, and the reason
#: is mypy's graph rather than style: `files = ["apps", "config"]`, so a plain
#: `from quality import checks` in a module under `apps/` drags the whole
#: `quality/` tree into `--strict` for the first time and surfaces ~85
#: pre-existing findings in code this pass did not touch. Fixing those is
#: separate work, not this one's to take; keeping the reference dynamic
#: leaves the boundary exactly where the configuration puts it.
C = importlib.import_module("quality.checks")
C_RULES = importlib.import_module("quality.gate").RULES

ROOT = Path(__file__).resolve().parents[3]


def _rule(services: list[dict[str, str]]) -> dict[str, Any]:
    return {"id": "49", "scope": {"enumerated_absence": services}}


def _run(rule: dict[str, Any]) -> Any:
    return C.audit_row_shape(ROOT, rule)


def test_the_real_allow_list_has_no_ghosts() -> None:
    """The live list, as committed: every name resolves to a real `@service`.

    This is the half that would rot silently. An entry keeps exempting nothing
    long after the name it was written for has been renamed, and the rule goes
    on reporting green over a population it has quietly stopped covering.
    """
    live = next(r for r in C_RULES if str(r["id"]) == "49")

    result = _run(live)

    ghosts = [f for f in result.findings if "ghost exemption" in f.msg]
    assert ghosts == [], [f.msg for f in ghosts]


def test_an_entry_naming_no_service_fires_the_lists_own_consistency_half() -> None:
    """The ghost canary. A name nothing answers to is a line covering nothing."""
    result = _run(_rule([{"service": "example.no_such_service_anywhere", "reason": "planted"}]))

    ghosts = [f for f in result.findings if "ghost exemption" in f.msg]
    assert len(ghosts) == 1, [f.msg for f in result.findings]
    assert "example.no_such_service_anywhere" in ghosts[0].msg
    assert ghosts[0].path == "quality/rules.yaml", "it fires where the line lives"


def test_a_service_that_exists_but_is_unaudited_is_not_a_ghost() -> None:
    """The negative beside it, and the distinction is deliberate.

    `events.purge_dispatched_outbox` and `workflows.purge_finished_runs` are on
    the live list and declare no tenant, so they are outside the audited
    population and their entries exempt nothing TODAY. That is not a ghost: the
    name resolves, the ADR's census names it, and the day one of them grows a
    `tenant` the entry is already correct. A ghost is a name nothing answers to.
    """
    result = _run(_rule([{"service": "events.purge_dispatched_outbox", "reason": "absence 1"}]))

    assert [f for f in result.findings if "ghost exemption" in f.msg] == []


def test_a_broken_seam_is_enforcement_broken_and_never_a_clean_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consistency canary: an unimportable seam must not read as a pass.

    The failure mode this refuses is specific and quiet. If
    `_declares_tenant` could not be imported the probe would have no population
    to walk, the census would come back empty, there would be no findings — and
    an empty census is indistinguishable from a conformant tree unless somebody
    says so. It emits NO counts on this path, so every floor in `rules.yaml`
    goes unbound and the gate exits 2 rather than 1: enforcement broken outranks
    any pass.
    """
    broken = json.dumps(
        {"seam": None, "seam_error": "ImportError: planted", "audited": [], "services": []}
    )
    monkeypatch.setattr(
        C.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": broken, "stderr": ""})(),
    )

    result = _run(_rule([]))

    assert len(result.findings) == 1
    assert "could not be imported" in result.findings[0].msg
    assert "reads the SEAM and never a copy of it" in result.findings[0].msg
    assert result.targets_matched == {}, "no counts, so every floor is unbound — exit 2"


def test_a_probe_that_cannot_run_is_also_enforcement_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same shape one layer out: the subprocess itself failing."""
    monkeypatch.setattr(
        C.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
    )

    result = _run(_rule([]))

    assert len(result.findings) == 1
    assert "could not run" in result.findings[0].msg
    assert result.targets_matched == {}


def test_the_seam_the_rule_reads_is_the_seam_the_decorator_reads() -> None:
    """One seam, imported and never mirrored — asserted as identity, not by eye.

    `quality/audit_population_probe.py` imports `_declares_tenant` rather than
    re-implementing "a keyword-only parameter named tenant". If it ever grew a
    copy, the copy and the decorator would agree on the day it was written and
    drift on some later one — with the rule enforcing the old population and
    reporting green the whole time.
    """
    source = (ROOT / "quality" / "audit_population_probe.py").read_text()

    assert "from apps.core.service import _declares_tenant" in source
    assert "_declares_tenant(wrapped)" in source
    assert "KEYWORD_ONLY" not in source, "a mirrored predicate is a second opinion"
