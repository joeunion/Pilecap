"""The licence policy and the declared advisory exceptions both supply-chain halves judge by.

Both licence readers import `banned`, and the pnpm audit reader imports `judge_advisory`: one answer each, in one place.
Each predicate carries a canary pair the leg drives before any real package is judged; either half misjudged is exit 2.
Standard library only: the leg runs it through `uv run python` from the checkout's root, with `scripts/` on `sys.path`.
"""

# The road marker above `banned` is one line by its grammar (quality/roads.py,
# TEXT_MARKER_RE) and its example path alone is most of the line limit, so the
# long-line rule is off for this file; every other line here fits.
# ruff: noqa: E501

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

#: The Python half's regex, moved here unchanged: `\b(?<!L)` keeps `LGPL` out of
#: the GPL match, and `banned` also refuses to call anything naming LGPL banned.
BANNED = re.compile(r"\b(?<!L)(A?GPL)|\bSSPL\b|Server Side Public License", re.IGNORECASE)

#: Licence strings the policy MUST refuse — the refused half of the canary pair.
MUST_REFUSE: tuple[str, ...] = (
    "GPL-3.0",
    "AGPL-3.0-only",
    "SSPL-1.0",
    "Server Side Public License",
    "GPL-2.0 WITH Classpath-exception-2.0",
)

#: Licence strings the policy MUST accept — the accepted half of the canary pair.
MUST_ACCEPT: tuple[str, ...] = (
    "MIT",
    "Apache-2.0",
    "LGPL-2.1",
    "BSD-3-Clause",
    "ISC",
    "(MIT OR Apache-2.0)",
)


# road: supply_chain_policy — Refuse a licence that names GPL, AGPL or SSPL; LGPL is allowed. · example: quality/tests/test_supply_chain.py::test_the_policy_pair_holds
def banned(licence: str) -> bool:
    """Refuse a licence that names GPL, AGPL or SSPL; LGPL is allowed."""
    return bool(BANNED.search(licence)) and "LGPL" not in licence


def pair_failures(predicate: Callable[[str], bool]) -> list[str]:
    """Every canary-pair member the predicate misjudges, one sentence each."""
    wrong = [f"{s!r} must be refused and was accepted" for s in MUST_REFUSE if not predicate(s)]
    wrong += [f"{s!r} must be accepted and was refused" for s in MUST_ACCEPT if predicate(s)]
    return wrong


#: The longest an advisory exception may stand before it is declared again (principle 20).
MAX_EXCEPTION_DAYS = 60

#: The `patched_versions` pnpm reports for an advisory with no fix; anything else is a patched range.
NO_PATCH = "<0.0.0"

GHSA_RE = re.compile(r"^GHSA(-[23456789cfghjmpqrvwx]{4}){3}$")


@dataclass(frozen=True)
class AdvisoryException:
    """One published advisory accepted on the dependency paths it was judged on, until a fix or a date."""

    ghsa: str
    why: str
    paths: tuple[str, ...]
    declared: date
    until: date

    def sentence(self) -> str:
        """The `accepted:` line the reader prints for this exception."""
        return f"accepted: {self.ghsa} — {self.why} (until {self.until.isoformat()}; ends when a patched range exists)"


#: The declared advisory exceptions: each ends when pnpm reports a patched range, or at `until`, whichever is first.
ADVISORY_EXCEPTIONS: tuple[AdvisoryException, ...] = (
    AdvisoryException(
        ghsa="GHSA-vfj7-8cjw-p6xm",
        why="a stack-exhaustion DoS in a glob matcher fed only our own lint config's patterns, reached only through the face's dev-only lint (eslint-config-next); worst case a crashed lint run, nothing shipped",
        paths=(".>eslint-config-next>@next/eslint-plugin-next>fast-glob>micromatch>braces",),
        declared=date(2026, 10, 2),
        until=date(2026, 12, 1),
    ),
)


def exception_failures(exceptions: tuple[AdvisoryException, ...], today: date) -> list[str]:
    """Every declared exception that is malformed, one sentence each."""
    wrong: list[str] = []
    seen: set[str] = set()
    for e in exceptions:
        if not GHSA_RE.match(e.ghsa):
            wrong.append(f"{e.ghsa!r} is not a GHSA id")
        if e.ghsa in seen:
            wrong.append(f"{e.ghsa} is declared twice")
        seen.add(e.ghsa)
        if not e.why.strip() or "\n" in e.why:
            wrong.append(f"{e.ghsa} carries no one-line why")
        if not e.paths or not all(p.strip() for p in e.paths):
            wrong.append(f"{e.ghsa} names no dependency path it was judged on")
        if e.declared > today:
            wrong.append(f"{e.ghsa} is declared in the future ({e.declared.isoformat()})")
        span = (e.until - e.declared).days
        if not 0 < span <= MAX_EXCEPTION_DAYS:
            wrong.append(f"{e.ghsa} stands {span} days, outside 1..{MAX_EXCEPTION_DAYS}")
    return wrong


def advisory_paths(advisory: Mapping[str, Any]) -> set[str]:
    """Every dependency path the report says the advisory is reached on."""
    return {
        str(p)
        for f in advisory.get("findings") or []
        if isinstance(f, Mapping)
        for p in f.get("paths") or []
    }


def judge_advisory(
    advisory: Mapping[str, Any],
    today: date,
    exceptions: tuple[AdvisoryException, ...] | None = None,
) -> tuple[bool, str]:
    """Accept a published advisory only on a declared, unexpired, still-unpatched exception."""
    declared = ADVISORY_EXCEPTIONS if exceptions is None else exceptions
    ghsa = str(advisory.get("github_advisory_id") or "")
    entry = next((e for e in declared if ghsa and e.ghsa == ghsa), None)
    if entry is None:
        return False, f"{ghsa or 'an advisory with no GHSA id'} is not a declared exception"
    patched = advisory.get("patched_versions")
    if not isinstance(patched, str):
        return (
            False,
            f"exception ended: {entry.ghsa} — the report does not say whether a patched range exists",
        )
    if patched.strip() != NO_PATCH:
        module = advisory.get("module_name")
        return (
            False,
            f"exception ended: {entry.ghsa} — a patched range exists ({patched}); move {module} to it",
        )
    if today > entry.until:
        return (
            False,
            f"exception ended: {entry.ghsa} — its until {entry.until.isoformat()} has passed",
        )
    paths = advisory_paths(advisory)
    stray = sorted(paths - set(entry.paths))
    if not paths or stray:
        return (
            False,
            f"exception does not cover: {entry.ghsa} reached on {', '.join(stray) or 'no path the report names'}",
        )
    return True, entry.sentence()


#: The advisory canary pair's own exception, so the pair judges the predicate and not today's list.
CANARY_EXCEPTION = AdvisoryException(
    ghsa="GHSA-2222-3333-4444",
    why="a planted exception for the canary pair",
    paths=(".>lint>glob", ".>lint>other>glob"),
    declared=date(2026, 1, 1),
    until=date(2026, 2, 1),
)

#: The day the advisory canary pair is judged on.
CANARY_TODAY = date(2026, 1, 15)


def _canary(
    ghsa: str, patched: object = NO_PATCH, paths: tuple[str, ...] = (".>lint>glob",)
) -> dict[str, Any]:
    """A planted advisory record in the shape `pnpm audit --json` reports."""
    record: dict[str, Any] = {
        "github_advisory_id": ghsa,
        "module_name": "glob",
        "severity": "high",
        "findings": [{"version": "1.0.0", "paths": list(paths)}],
    }
    if patched is not None:
        record["patched_versions"] = patched
    return record


#: Advisories the policy MUST refuse, each with the day it is judged on.
MUST_REFUSE_ADVISORIES: tuple[tuple[str, dict[str, Any], date], ...] = (
    ("unlisted", _canary("GHSA-9999-9999-9999"), CANARY_TODAY),
    ("patched now", _canary(CANARY_EXCEPTION.ghsa, patched=">=1.0.1"), CANARY_TODAY),
    ("patch unreported", _canary(CANARY_EXCEPTION.ghsa, patched=None), CANARY_TODAY),
    ("past until", _canary(CANARY_EXCEPTION.ghsa), date(2026, 2, 2)),
    ("undeclared path", _canary(CANARY_EXCEPTION.ghsa, paths=(".>runtime>glob",)), CANARY_TODAY),
)

#: Advisories the policy MUST accept, each with the day it is judged on.
MUST_ACCEPT_ADVISORIES: tuple[tuple[str, dict[str, Any], date], ...] = (
    ("listed", _canary(CANARY_EXCEPTION.ghsa), CANARY_TODAY),
    (
        "listed, both paths, on until",
        _canary(CANARY_EXCEPTION.ghsa, paths=CANARY_EXCEPTION.paths),
        CANARY_EXCEPTION.until,
    ),
)


def advisory_pair_failures(
    judge: Callable[
        [Mapping[str, Any], date, tuple[AdvisoryException, ...] | None], tuple[bool, str]
    ],
) -> list[str]:
    """Every advisory canary-pair member the judge misjudges, one sentence each."""
    planted = (CANARY_EXCEPTION,)
    wrong = [
        f"the {n} advisory must be refused and was accepted"
        for n, a, d in MUST_REFUSE_ADVISORIES
        if judge(a, d, planted)[0]
    ]
    wrong += [
        f"the {n} advisory must be accepted and was refused"
        for n, a, d in MUST_ACCEPT_ADVISORIES
        if not judge(a, d, planted)[0]
    ]
    return wrong
