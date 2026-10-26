"""The product's drawer legs run: provisioned once per unit, tier and `touches` applied."""

# Invariant: a drawer leg's exit 2 is could-not-look and outranks any red; 2 > 1 > 0 for the run.
# does-not-cover: what a drawer leg checks — only that it ran, how it exited and which it was.

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import registry as R

#: The key schema a drawer leg's reuse key is spelled under (`DRIVE_KEY_SCHEMA`'s default).
KEY_SCHEMA = "drive-v1"


def _say(line: str) -> None:
    print(line, flush=True)


def _err(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def provision(home: Path, unit: str, done: set[str], env: Mapping[str, str]) -> int:
    """`<drawer>/_provision-<unit>.sh` once per run: 0 when absent or green, its exit otherwise."""
    if unit in done:
        return 0
    script = home / f"_provision-{unit}.sh"
    if not script.is_file():
        done.add(unit)
        return 0
    if not script.stat().st_mode & 0o111:
        _err(
            f"!! {script} is not executable — a provisioner this gate cannot run is a unit whose"
            " legs run unprovisioned."
        )
        return 2
    _say(f"  local unit {unit}: provisioning — {script}")
    rc = subprocess.run([str(script)], env=dict(env), check=False).returncode
    if rc:
        _err(f"!! {script} exited {rc} — unit '{unit}' is NOT provisioned.")
        return rc
    done.add(unit)
    return 0


def run(
    table: R.Table,
    mode: str,
    env: Mapping[str, str],
    *,
    narrowed: bool,
    changed: Sequence[str] = (),
    only: Sequence[str] = (),
) -> int:
    """Every drawer leg `mode`'s tier runs (or `only` those), each its own exit; 2 > 1 > 0."""
    tier = set(R.local_tier(table.local, mode))
    done: set[str] = set()
    green = red = cannot = skipped = 0
    rednames: list[str] = []
    cannotnames: list[str] = []
    for leg in table.local:
        if leg.name not in tier or (only and leg.name not in only):
            continue
        if narrowed and leg.touches:
            try:
                runs = R.local_touched(leg, changed)
            except CouldNotLook:
                _say(
                    f"  {leg.name}: touches ({' '.join(leg.touches)}) not applied — this run's"
                    " changed set could not be read, so the leg runs"
                )
                runs = True
            if not runs:
                _say(
                    f"  {leg.name}: SKIPPED — its touches ({' '.join(leg.touches)}) matched nothing"
                    " this run changed. The full gate runs it regardless."
                )
                skipped += 1
                continue
        if provision(leg.path.parent, leg.unit, done, env):
            _say(f"  {leg.name}: could not look — unit '{leg.unit}' did not provision")
            cannot += 1
            cannotnames.append(leg.name)
            continue
        t0 = time.monotonic()
        done_run = subprocess.run(
            [str(leg.path)], env=dict(env), capture_output=True, text=True, check=False
        )
        rc = done_run.returncode
        _say(f"  {leg.name}: exit {rc} ({int(time.monotonic() - t0)}s)")
        if rc == 0:
            green += 1
            continue
        for line in (done_run.stdout + done_run.stderr).splitlines():
            _say(f"      | {line}")
        if rc == 2:
            cannot += 1
            cannotnames.append(leg.name)
        else:
            red += 1
            rednames.append(leg.name)
    _say(
        f"  local legs ({mode}): {green} green · {red} red · {cannot} could-not-look ·"
        f" {skipped} skipped by touches"
    )
    if cannot:
        _err(f"!! LOCAL LEGS COULD NOT LOOK: {' '.join(cannotnames)}")
        if red:
            _err(f"!! and RED: {' '.join(rednames)}")
        _err("   2 outranks 1. A product leg's exit 2 is could-not-look, as everywhere here.")
        return 2
    if red:
        _err(f"!! LOCAL LEGS RED: {' '.join(rednames)}")
        return 1
    return 0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def key(
    leg: R.LocalLeg,
    listing: Callable[[str], str],
    env: Mapping[str, str],
    machine: str,
) -> tuple[str, str]:
    """A drawer leg's reuse key and parts: header, bytes, `inputs:` and `env:` values."""
    try:
        text = [
            KEY_SCHEMA,
            f"name {leg.name}",
            "header "
            + "|".join(
                (
                    leg.unit,
                    ",".join(leg.needs),
                    leg.tier,
                    " ".join(leg.touches),
                    " ".join(leg.inputs),
                    " ".join(leg.env),
                )
            ),
        ]
        own = hashlib.sha256(leg.path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CouldNotLook(f"the local leg {leg.path} is not readable ({exc})") from exc
    text.append(f"self {own}")
    parts = [f"self:{own[:12]}"]
    for prefix in leg.inputs:
        expanded = listing(prefix)
        if not expanded:
            raise CouldNotLook(
                f"its declared input {prefix} expands to nothing in the measured tree — never a"
                " silently narrower key"
            )
        digest = _digest(expanded + "\n")
        text.append(f"{prefix} {digest}")
        parts.append(f"{prefix}:{digest[:12]}")
    for name in leg.env:
        digest = _digest(env.get(name) or "<unset>")
        text.append(f"env:{name} {digest}")
        parts.append(f"env:{name}:{digest[:12]}")
    text.append(f"machine {machine}")
    parts.append(f"machine:{machine[:12]}")
    return f"{KEY_SCHEMA}:{_digest(chr(10).join(text) + chr(10))}", ",".join(parts)
