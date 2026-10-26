"""How a leg body runs a command: the terminal's streams, a callee's cause carried out."""

# Invariant: standard library only — the registry imports every leg under the system python.

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from quality.djb.registry import Ctx

#: The shell libraries `check.sh` sources before its legs, in its order.
LIBRARIES = (
    "scripts/gate_refuse.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_lease.sh",
    "scripts/db.sh",
    "scripts/secrets_scan.sh",
    "scripts/archaeology_lib.sh",
    "scripts/docs_legs.sh",
    "scripts/fe_gate.sh",
)
#: The shell's word for each mode, as `check.sh`'s `$MODE` spells it.
SHELL_MODE = {"fast": "--fast", "loop": "--loop", "full": ""}
_CAUSE_NONE = re.compile(r"^GATE_CAUSE_NONE='([^']*)'", re.MULTILINE)


def say(*lines: str) -> None:
    """Print each line on stderr."""
    for line in lines:
        print(line, file=sys.stderr)
    sys.stderr.flush()


def checkout_python(root: Path) -> Path | None:
    """`<root>/.venv/bin/python` when it is executable, else None (`checkout_python`)."""
    py = root / ".venv" / "bin" / "python"
    return py if os.access(py, os.X_OK) else None


def cause_none(root: Path) -> str:
    """The sentence a banner prints when the callee recorded no cause (`GATE_CAUSE_NONE`)."""
    try:
        found = _CAUSE_NONE.search((root / "scripts/gate_refuse.sh").read_text(encoding="utf-8"))
    except OSError:
        found = None
    return found.group(1) if found else "(the callee set none)"


def cause_of(text: str) -> str:
    """The first `!!` line unled, else the first non-blank line (`gate_refuse_from_file`)."""
    for line in text.splitlines():
        if line.lstrip().startswith("!!"):
            return line.lstrip()[2:].strip()
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _env(ctx: Ctx, extra: Mapping[str, str] | None) -> dict[str, str]:
    env = dict(ctx.env)
    env.update(extra or {})
    return env


def tool(ctx: Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int:
    """Run `argv` in the checkout with the terminal's streams; its exit."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        return subprocess.run(list(argv), cwd=ctx.root, env=_env(ctx, env)).returncode
    except OSError as exc:
        say(f"!! {argv[0]} could not be started: {exc}")
        return 2


def callee(ctx: Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """Run `argv` with its stderr captured and replayed; its exit and its own cause."""
    sys.stdout.flush()
    sys.stderr.flush()
    with tempfile.TemporaryFile() as err:
        try:
            rc = subprocess.run(list(argv), cwd=ctx.root, env=_env(ctx, env), stderr=err).returncode
        except OSError as exc:
            return 2, f"{argv[0]} could not be started: {exc}"
        err.seek(0)
        text = err.read().decode(errors="replace")
    sys.stderr.write(text)
    sys.stderr.flush()
    return rc, cause_of(text)


def captured(
    ctx: Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None
) -> tuple[int, str]:
    """Run `argv` with both streams to a file, then print it; its exit and its text."""
    sys.stdout.flush()
    sys.stderr.flush()
    with tempfile.TemporaryFile() as out:
        try:
            rc = subprocess.run(
                list(argv), cwd=ctx.root, env=_env(ctx, env), stdout=out, stderr=out
            ).returncode
        except OSError as exc:
            return 2, f"{argv[0]} could not be started: {exc}"
        out.seek(0)
        text = out.read().decode(errors="replace")
    sys.stdout.write(text)
    sys.stdout.flush()
    return rc, text


def library(ctx: Ctx, script: str, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """Run `script` in bash over the libraries; its exit and the `GATE_LAST_REFUSAL` it left."""
    prelude = "".join(f". {lib} || exit 2\n" for lib in LIBRARIES)
    with tempfile.NamedTemporaryFile(prefix="djb-leg-cause.", delete=False) as handle:
        cause_path = handle.name
    body = (
        f'trap \'printf "%s" "${{GATE_LAST_REFUSAL:-}}" >"$DJB_LEG_CAUSE_OUT"\' EXIT\n'
        f"MODE={SHELL_MODE[ctx.mode]!r}\n{prelude}gate_refuse_reset\nset +e\n{script}"
    )
    extra = {"DJB_LEG_CAUSE_OUT": cause_path, "DB_PIN_NOTE_OFF": "1", **(env or {})}
    try:
        rc = tool(ctx, ["bash", "-c", body], extra)
        cause = Path(cause_path).read_text(errors="replace").strip()
    finally:
        os.unlink(cause_path)
    return rc, cause


#: Where a banner's `cause:` line goes among its lines.
CAUSE = "\0cause"


def could_not_look(ctx: Ctx, cause: str, *lines: str) -> int:
    """Print the banner with its `cause:` — the callee's own words whenever it said any; 2."""
    line = f"   cause: {cause or cause_none(ctx.root)}"
    say(*(line if text == CAUSE else text for text in lines))
    return 2
