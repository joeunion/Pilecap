"""The names the gate package reads from the environment: one closed list, and its one reader."""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Every `DJB_*` name a module under `quality/djb/` reads, and the secret scan's base ref.
NAMES: Mapping[str, str] = {
    "DJB_GATE_LEASE_DIR": "the machine-wide directory the lease and the slots live in; absolute",
    "DJB_GATE_LEASE_MAX_WAIT": "seconds a full gate waits for the lease before refusing",
    "DJB_GATE_LEASE_POLL": "seconds between attempts while waiting, for the lease and a slot",
    "DJB_GATE_LEASE_ANNOUNCE": "seconds between still-waiting lines, for the lease and a slot",
    "DJB_GATE_HOST_SLOTS": "how many whole gates may run at once on this machine; default 3",
    "DJB_GATE_SLOTS": "how many pytest legs may run at once on this machine",
    "DJB_GATE_SLOT_MAX_WAIT": "seconds a pytest leg waits for a slot before refusing",
    "DJB_GATE_SLOT_WORKERS": "the -n a slot holder runs, at or below its share; written back",
    "DJB_BANK_SHARES_SLOTS": "set: a bank takes one slot and one share instead of every slot",
    "DJB_GATE_LEDGER": "the verdict ledger's path; absolute, else the common dir's file",
    "DJB_GATE_BOX_MARKER": "the file whose presence says this machine is a verifier box",
    "DJB_GATE_MEMBER_WALLS_CI": "a walls table read alone for CI's selftest shard count",
    "DJB_GATE_MEMBER_DURATIONS": "a walls table read for this machine's column when CI's is empty",
    "DJB_GATE_LEDGER_LEGACY_UNTIL": "the day the retired verdict stores stop being read",
    "DJB_GATE_INTENT_MAX_AGE": "seconds a CI intent row vouches for a train branch's push",
    "DJB_GATE_CALLER": "who asked for the full gate; one of the ledger's closed caller kinds",
    "DJB_LOCAL_LEGS_DIR": "a product's leg drawer; relative to the checkout",
    "DJB_LOCAL_DRIVES_DIR": "a product's drive drawer; relative to the checkout",
    "DJB_LOCAL_LEGS_CHANGED_FILES": "the changed set a narrowed mode applies drawer `touches` to",
    "DJB_CI_WORKFLOW": "the workflow file whose pull-request runs the CI consult reads",
    "DJB_PUSH_DESTINATION": "`verifier-box`: the pushing caller declares a box probe remote",
    "DJB_PUSH_INTENT": "`ci`: a train branch's push whose pull request's run is the measurement",
    "DJB_PUSH_WORKTREE": "the detached worktree's name a `--bank` may run from besides the primary",
    "DJB_GATE_SANCTION": "`<who>: <why>`: the typed sanction a hand-run full gate carries",
    "DJB_GATE_LEGS_DRY": "set: every leg is announced and no body runs; nothing is banked",
    "DJB_GATE_BOX_MARKERS": "space-separated files any one of which says this is a verifier box",
    "DJB_LOOP_HERE": "`<who>: <why>`: a `--loop` off a verifier box, said beside its verdict",
    "DJB_LOOP_NO_CACHE": "set: the `--loop` ledger is neither consulted nor written",
    "DJB_LOOP_VERBOSE": "set: a `--loop` miss prints its whole attribution",
    "DJB_LOOP_SCOPE_BASE": "the ref the `--loop` scope forks from; default `refs/heads/main`",
    "DJB_LOOP_SCOPE_ALSO": "app labels a caller adds to the `--loop` scope's seeds",
    "DJB_LOOP_NO_IMPACT": "set: the `--loop` scope bypasses the test-impact map, keyed so",
    "DJB_LOOP_MAP_SCAN": "how many commits back the test-impact map's freshness is looked for",
    "DJB_LOOP_ENV_READS": "a file naming the read-set the `--loop` environment fingerprint hashes",
    "DJB_LAYER_SANCTION": "`<who>: <why>`: a platform edit on a product, kept as its trailer",
    "DJB_LAYER_HOOK_JUDGED": "`1`: the pre-commit hook judged the staged set at the boundary",
    "DJB_SELFTEST_PLAN": "the selftest-plan/1 file a full lane's row narrows the selftest unit by",
    "SECRETS_SCAN_BASE_REF": "the secret scan's fork point; the `--loop` scope's when no other",
}


#: Every name that steers a child gate's verdict when inherited; a test and a drive start without.
STEERS: tuple[str, ...] = (
    "SELFTEST_PLAN",
    "DJB_SELFTEST_PLAN",
    "DJB_GATE_SANCTION",
    "DJB_GATE_CALLER",
    "DJB_GATE_PYTEST_SEED",
    "DJB_GATE_LEGS_DRY",
    "DJB_GATE_BOX_MARKER",
    "DJB_GATE_BOX_MARKERS",
    "DJB_GATE_MEMBER_DURATIONS",
    "DJB_LOOP_HERE",
    "DJB_LOOP_NO_IMPACT",
    "DJB_LAYER_HOOK_JUDGED",
    "DJB_LOCAL_LEGS_DIR",
    "DJB_LOCAL_LEGS_KNOWN_NAMES",
    "DJB_LOCAL_LEGS_TEMPLATE_UNITS",
    "DJB_LOCAL_LEGS_CHANGED_FILES",
    "DJB_LOCAL_DRIVES_DIR",
    "DJB_LOCAL_ENV_KEYS",
    "DJB_MEMBER_WALLS_OUT",
    "STACK_REGISTRY",
    "DOCKERHUB_USERNAME",
    "DOCKERHUB_TOKEN",
)


class UndeclaredName(LookupError):
    """A `DJB_*` name read or written that `NAMES` does not declare — a defect, never a default."""


def _declared(name: str) -> str:
    if name not in NAMES:
        raise UndeclaredName(
            f"{name} is not in quality/djb/env.py's NAMES — declare it there first"
        )
    return name


def read(name: str, default: str | None = None) -> str | None:
    """A declared name's value at call time; empty is unset, as the shell's `${X:-d}` reads it."""
    value = os.environ.get(_declared(name), "")
    return value if value else default


def environ() -> dict[str, str]:
    """A copy of this process's whole environment: what a leg body's children inherit."""
    return dict(os.environ)


def export(name: str, value: str) -> None:
    """Set a declared name for this process and every child it starts."""
    os.environ[_declared(name)] = value


def unset(name: str) -> None:
    """Remove a declared name from this process's environment."""
    os.environ.pop(_declared(name), None)
