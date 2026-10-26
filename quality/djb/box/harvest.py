"""`harvest`, `harvest-drives` and `fetch`: a box's verdict rows and files brought home."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from quality.djb import ledger
from quality.djb.box.core import Box, Command, vb_log
from quality.djb.box.transport import (
    ROOT,
    Refused,
    die,
    say,
    spawn,
    verifier_box_user,
    verifier_checkout_path,
)

BANKED_SENTENCE = "banked: this --loop verdict"


def box_rows_command(checkout: str, kind: str, store: str) -> str:
    """The remote line that prints the box's `kind` rows through its own reader, else `store`."""
    return (
        f"cd {checkout} && {{ bash -c '. scripts/gate_ledger.sh >/dev/null 2>&1 &&"
        f" declare -F ledger_rows >/dev/null && ledger_rows {kind}' || cat .git/{store}; }}"
    )


def read_lines(text: str) -> list[str]:
    """`while IFS= read -r line`'s lines: a last fragment with no newline is not read."""
    return text.split("\n")[:-1]


def field_of(row: str, name: str) -> str:
    """The value of ` <name>=<v>` in `row`, first match, '' when absent (`loop_component_value`)."""
    for token in row.split(" ")[1:]:
        if token.startswith(f"{name}="):
            return token[len(name) + 1 :]
    return ""


def banked_key(log: str) -> str:
    """The first `loop-v1:` token on the lines after the `banked:` sentence, or ''."""
    seen = False
    for line in read_lines(log):
        if BANKED_SENTENCE in line:
            seen = True
            continue
        if not seen:
            continue
        for token in line.split():
            if token.startswith("loop-v1:"):
                return token
    return ""


def append_carried(row: str, *extra: str, path: Path) -> None:
    """A row another ledger wrote, appended with its own stamp; `Refused` when it is not one."""
    if row.startswith("loop-v1 ") and " loop " in row:
        row = f"{ledger.SCHEMA} {row.removeprefix('loop-v1 ')}"
    parts = row.split()
    if len(parts) < 4 or parts[0] != ledger.SCHEMA:
        raise ledger.Refused(f"not a row of the one grammar: {row[:120]}")
    ledger.append(parts[2], parts[1], [*parts[4:], *extra], path=path, stamp=parts[3])


def local_ledger(box: Box) -> Path | None:
    """This checkout's gate ledger (`gate_ledger_path`), or None when it cannot be resolved."""
    try:
        return ledger.ledger_path(ROOT)
    except (ledger.Refused, ledger.Mismatch, OSError):
        return None


def harvest_drive_rows(box: Box, instance: str, checkout: str, tree: str) -> None:
    """The box's `drive` rows at `tree`, appended once each; narrates and never refuses."""
    if not tree:
        vb_log("drive rows: none brought home — the loop row names no tree to filter on")
        return
    path = local_ledger(box)
    if path is None:
        vb_log(
            "drive rows: none brought home — this checkout's gate ledger could not be resolved",
            err=True,
        )
        return
    rc, text = box.ssh_capture(instance, box_rows_command(checkout, "drive", "djb-gate-verdicts"))
    if rc != 0:
        vb_log(f"drive rows: none brought home — {instance} has no gate ledger to read")
        return
    here = {existing for _, existing in ledger.rows(path)}
    n = already = 0
    for line in read_lines(text):
        if not (" drive " in line and (f" tree={tree} " in line or line.endswith(f" tree={tree}"))):
            continue
        if line in here:
            already += 1
            continue
        try:
            append_carried(line, path=path)
        except (ledger.Refused, ledger.MalformedRow, OSError):
            continue
        here.add(line)
        n += 1
    vb_log(f"drive rows: {n} brought home at tree={tree} ({already} already here) from {instance}")


def cmd_harvest(box: Box, args: Sequence[str]) -> int:
    """`harvest <id> <name>`: the box's banked loop row for that log, appended here once."""
    instance = args[0] if args else ""
    name = args[1] if len(args) > 1 else ""
    if not instance or not name:
        die(
            "verifier_box: harvest takes: harvest <id> <name> — the <name> a"
            " 'loop <id> --log <name>' used."
        )
    box.refuse_if_reclaimed(instance)
    rung = box.box_rung(instance)
    checkout = verifier_checkout_path()
    rc, log = box.ssh_capture(instance, f"cat ~/verify/{rung}/{name}.log")
    if rc != 0:
        die(
            f"verifier_box: could not read ~/verify/{rung}/{name}.log on {instance} (exit {rc})."
            " Nothing was\n"
            "   harvested and nothing was appended. That is the transport or a name that\n"
            "   never ran, never a verdict."
        )
    key = banked_key(log)
    if not ledger.LOOP_KEY_RE.match(key):
        die(
            f"verifier_box: the log for '{name}' on {instance} banks no verdict — there is"
            " nothing to harvest and\n"
            "   NOTHING WAS APPENDED. A --mine run banks nothing (it walked no closure), a red\n"
            "   run banks nothing, and a run whose tree moved underneath it banks nothing; the\n"
            "   log itself says which. Harvesting anyway would put a key in this checkout's\n"
            "   ledger that no measurement stands behind."
        )
    rc, rows = box.ssh_capture(instance, box_rows_command(checkout, "loop", "djb-loop-verdicts"))
    row = ""
    if rc == 0:
        for line in read_lines(rows):
            fields = line.split()
            if f" {key} " in line and len(fields) > 1 and fields[1] == key:
                row = line
    if not row:
        die(
            f"verifier_box: the log on {instance} says it banked {key}, and that box's own ledger\n"
            f"   (its loop rows, under {checkout}) has no row for it. NOTHING WAS APPENDED.\n"
            "   A row composed here would be this machine's opinion of the box's measurement."
        )
    path = local_ledger(box)
    if path is None:
        die("verifier_box: could not resolve this checkout's ledger. Nothing was appended.")
    tree = field_of(row, "tree")
    harvest_drive_rows(box, instance, checkout, tree)
    home = ledger.last(path, "loop", key)
    if home is not None:
        vb_log(f"already harvested: {key} is in this checkout's ledger — nothing appended.")
        say(f"banked: tree {home.get('tree') or ''} key {key} box={instance}")
        return 0
    try:
        append_carried(row, f"box={instance}", path=path)
    except (ledger.Refused, ledger.MalformedRow, OSError):
        die(
            f"verifier_box: the box's row for {key} would not append through the one writer"
            " (ledger.append) —\n"
            "   the row is not a row of the one grammar, or the ledger would not take it."
            " Nothing was appended."
        )
    say(f"harvested: {key} tree={tree or 'unstated'} box={instance}")
    say(f"banked: tree {tree or 'unstated'} key {key} box={instance}")
    return 0


def cmd_harvest_drives(box: Box, args: Sequence[str]) -> int:
    """`harvest-drives <id> <tree>`: the box's drive rows at that tree, with no loop row."""
    instance = args[0] if args else ""
    tree = args[1] if len(args) > 1 else ""
    if not instance or not tree:
        die(
            "verifier_box: harvest-drives takes: harvest-drives <id> <tree> — the tree the rows"
            " are keyed at."
        )
    box.refuse_if_reclaimed(instance)
    harvest_drive_rows(box, instance, verifier_checkout_path(), tree)
    return 0


def scp_argv(box: Box, instance: str, remote: str, local: str) -> list[str]:
    """The one scp argv: the box's key and the same tunnel `ssh_argv` carries."""
    return [
        "scp",
        "-i",
        str(box.box_key(instance)),
        "-o",
        f"ProxyCommand={box.proxy_command()}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"{verifier_box_user()}@{instance}:{remote}",
        local,
    ]


def cmd_fetch(box: Box, args: Sequence[str]) -> int:
    """`fetch <id> <remote> <local>`: one scp over the box's transport; scp's own status."""
    instance, remote, local = ([*args, "", "", ""])[:3]
    if not instance or not remote or not local:
        die("verifier_box: fetch takes: fetch <id> <remote path> <local path>")
    box.refuse_if_reclaimed(instance)
    if not box.box_key(instance).is_file():
        die(f"verifier_box: no private key for {instance}")
    rc = spawn(scp_argv(box, instance, remote, local), env=box.cfg.env).returncode
    if rc != 0:
        return rc
    vb_log(f"fetched {instance}:{remote} -> {local}")
    return 0


def whole_log_home(box: Box, instance: str, name: str) -> Path:
    """Where a red wait's whole log lands: `DJB_VERIFIER_LOG_DIR`, else `<home>/logs`."""
    base = box.cfg.env.get("DJB_VERIFIER_LOG_DIR") or str(box.cfg.home / "logs")
    return Path(base) / f"{instance}-{name}.log"


def fetch_whole_log(box: Box, instance: str, name: str, log: str) -> None:
    """A red or could-not-look wait's whole log, fetched and its path printed; never a refusal."""
    local = whole_log_home(box, instance, name)
    try:
        local.parent.mkdir(parents=True, exist_ok=True)
        rc = cmd_fetch(box, [instance, log, str(local)])
    except (OSError, Refused) as failed:
        say(f"wait: the whole log did not come home — {str(failed).split(chr(10))[0]}")
        return
    if rc != 0:
        say(f"wait: the whole log did not come home — scp exit {rc}")
        return
    say(f"--- the whole log: {local} ---")


COMMANDS: dict[str, Command] = {
    "harvest": cmd_harvest,
    "harvest-drives": cmd_harvest_drives,
    "fetch": cmd_fetch,
}
