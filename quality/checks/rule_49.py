"""Rule 49: every audit emitter declared WHO and WHERE."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from quality.checks._hub import CheckResult

# --- rule 49: every audit emitter declared WHO and WHERE ------------------------
#
# ADR core-22. The audit trail answers NIST SP 800-53 AU-3's content elements off
# columns this table already had — and `core.service.write_audit` takes the WHO
# from the `actor` a service was given AND FROM NOWHERE ELSE, deliberately: the
# bound context has a `user_id` on it and it is ambient observability data, while
# an audit row is a claim. So a service that does not take an actor cannot record
# a person even when a person is standing at the door, and its probe found
# exactly that — `actor_user_id` None on every row of the one compliance-shaped
# table in the product.
#
# WHY A DEFAULT IS THE FAILURE AND AN ABSENCE IS NOT. The decorator reads the
# audited population off the DECLARATION and writes the row from the CALL. A
# service with no `actor` at all is making a claim a reviewer can check — nobody
# asked for this, it is machine work — and the allow-list below is where that
# claim is written down. A service with a DEFAULTED actor is making no claim at
# all: it looks attributed, and it files under nobody the moment one caller
# leaves the argument out, with nothing anywhere recording which callers did.
# That is precisely how `accounts.sync_workforce_identity_config` went unaudited
# under ADR core-8 while its signature said otherwise, and this rule is that
# lesson turned from a paragraph into a check. `tenant` reads the same way, and
# `Tenant | None` with no default is CONFORMANT: nullable is a real declared
# population (core-8 (b)); required-but-nullable made the caller say.
#
# ONE SEAM, IMPORTED AND NEVER MIRRORED. The population is whatever
# `apps.core.service._declares_tenant` says it is — the same predicate `@service`
# reads at decoration time. The probe imports it. A rule that re-implemented "a
# keyword-only parameter named tenant" would be a second opinion about the
# population, and the day the seam moved the rule would enforce the old one and
# report green; the seam breaking is exit 2 here, never an empty census.
#
# THE ALLOW-LIST GROWS ADR-FIRST. Every entry names an enumerated absence in
# core-22 by number and carries its ground. A new exemption is an amendment to
# that ADR and THEN a line here — never a line here because a rung went red.

_AUDIT_PROBE = "quality/audit_population_probe.py"
_AUDIT_KLASS = "audit_shape"


def _audit_allow_list(rule: dict) -> dict[str, str]:
    """`{dotted service name: reason}` off the rule's own scope."""
    scope = rule.get("scope") or {}
    out: dict[str, str] = {}
    for entry in scope.get("enumerated_absence") or []:
        name = str(entry.get("service", "")).strip()
        if name:
            out[name] = str(entry.get("reason", "")).strip()
    return out


def audit_row_shape(root: Path, rule: dict) -> CheckResult:
    """Rule 49. Every audit emitter declares who acted and which workspace.

    Signature tier only, and the boundary is in `does_not_cover`: this sees that
    a service was MADE to be told, never that the door told it the truth. The
    worked counter-example is real and is named there — `TenantAdmin
    .call_service` dropped an actor whose signature was already perfect — and
    `apps/core/tests/test_admin_actor_passthrough.py` is the other half of that
    division of labor.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / _AUDIT_PROBE)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        report = {}
    if proc.returncode != 0 or not report:
        out.hit(
            _AUDIT_PROBE,
            1,
            "the audited-population probe could not run, so the population is unknown "
            f"and nothing below was measured: {(proc.stderr or '').strip()[:400]}",
            klass=_AUDIT_KLASS,
        )
        return out

    # THE CONSISTENCY CANARY. A seam that could not be imported is enforcement
    # broken, not a clean tree: the census would be empty and an empty census
    # reads as a pass. No counts are emitted on this path, so every floor below
    # is unbound and the gate exits 2 rather than 1.
    if not report.get("seam"):
        out.hit(
            _AUDIT_PROBE,
            1,
            "apps.core.service._declares_tenant could not be imported, so this rule has "
            "no population to check and cannot tell a conformant tree from an empty one: "
            f"{report.get('seam_error', '')}. The rule reads the SEAM and never a copy of "
            "it (ADR core-22); fix the import, never the rule",
            klass=_AUDIT_KLASS,
        )
        return out

    allow = _audit_allow_list(rule)
    every_service = set(report.get("services") or [])
    audited = report.get("audited") or []

    # THE ALLOW-LIST'S OWN CONSISTENCY HALF. An entry naming no service at all is
    # a ghost: it exempts nothing, and it will go on exempting nothing after the
    # name it was written for has gone. Same reasoning as its `_scope_paths`
    # assertion for a path that does not resolve.
    for name in sorted(allow):
        if name not in every_service:
            out.hit(
                "quality/rules.yaml",
                1,
                f"the enumerated-absence list names {name!r}, which is no @service in this "
                "tree — a ghost exemption, covering nothing and outliving its own reason. "
                "Remove it, or fix the name",
                klass=_AUDIT_KLASS,
            )

    for row in audited:
        out.count("audited_services")
        dotted = row["dotted"]
        exempt = dotted in allow
        if exempt:
            out.count("enumerated_absences")
        if row.get("sweep") and exempt:
            out.hit(
                row["file"],
                row["line"],
                f"the enumerated-absence list names {dotted}, which is a sweep "
                "`core.schedules.daily_purge` reaches on the factory's signature — absence 1 by "
                "construction (ADR core-22), so its entry in quality/rules.yaml is a ghost. "
                "Remove the entry",
                klass=_AUDIT_KLASS,
            )
        if row.get("sweep") and row["actor"] == "absent":
            # core-22 absence 1, derived: reached by `daily_purge(...)` AND on its signature.
            exempt = True
            out.count("derived_sweeps")
        bad = False
        for parameter in ("actor", "tenant"):
            shape = row[parameter]
            if shape == "required":
                continue
            # AN ENUMERATED ABSENCE IS AN ABSENCE, NEVER A LICENCE TO DEFAULT.
            # The list excuses a service for taking NO actor — a claim a reviewer
            # can read, grounded in a numbered absence in ADR core-22. It cannot
            # excuse a DEFAULT: no absence in that ADR describes a signature that
            # says a person is recorded beside call sites that quietly say
            # otherwise, and letting the list cover it would turn the list into a
            # way to buy silence for the exact shape this rule catches.
            if exempt and shape == "absent":
                continue
            bad = True
            out.count("nonconformant")
            if shape == "absent":
                out.hit(
                    row["file"],
                    row["line"],
                    f"{dotted} writes an AuditEntry (it declares a tenant, so @service "
                    f"audits it) and takes no {parameter} — so the row it writes can never "
                    f"name {'who acted' if parameter == 'actor' else 'which workspace'}. "
                    "Take it as a required keyword-only parameter, or enumerate the service "
                    "in rule 49's absence list with its ADR core-22 absence number (which is "
                    "an amendment to that ADR first, and a line here second)",
                    klass=_AUDIT_KLASS,
                )
            else:
                out.hit(
                    row["file"],
                    row["line"],
                    f"{dotted} DEFAULTS its {parameter}. The decorator reads the audited "
                    "population off the declaration and writes the row from the call, so a "
                    "defaulted parameter is a service that looks attributed and files every "
                    "row under nobody the moment one caller leaves it out — with nothing "
                    "recording which callers did. `X | None` with NO default is fine (a "
                    "nullable value is a real declared population); a default is not. This "
                    "is ADR core-8's sync_workforce lesson, checked",
                    klass=_AUDIT_KLASS,
                )
        if not bad:
            out.count("conformant")
    return out
