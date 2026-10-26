"""The bank's boxes: `scripts/pm_push.sh`'s 26 `bank_boxes_*` bodies, one function each."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.djb.box.census import tab_fields
from quality.djb.box.core import clock_s
from quality.djb.box.transport import DEVNULL, STDOUT, capture, say, spawn, warn

#: What `pm_push.sh` sets and never exports; its wrapper lines export them for this module only.
_SHELL_ONLY = ("BANK_", "ROOT", "PYTHONPATH")
_WS = re.compile(r"[ \t\n]+")
_TAG_SUFFIX = "/djb-{service}:{tag}"


@dataclass
class Bank:
    """`pm_push.sh`'s `BANK_*` globals and `ROOT`, read once from the wrapper's environment."""

    vb: str = ""
    sink: str = ""
    tsv: str = ""
    workers: str = ""
    accept_id: str = ""
    accept_note: str = ""
    zones: str = ""
    plan: str = ""
    tree8: str = ""
    arung: str = ""
    acmd: str = ""
    accept_az: str = ""
    fe_cmd: str = ""
    ttl_hours: str = ""
    idle_minutes: str = ""
    retry_seconds: str = ""
    proof_workers: str = ""
    suite_leg: str = ""
    root: str = ""
    env: dict[str, str] = field(default_factory=dict)

    def at(self, name: str) -> Path:
        """`${BANK_BOXES_SINK}/<name>`."""
        return Path(f"{self.sink}/{name}")


def bank_of(environ: dict[str, str]) -> Bank:
    """The bank's globals out of `environ`; children get `environ` less the wrapper's exports."""
    get = environ.get
    return Bank(
        vb=get("BANK_BOXES_VB", ""),
        sink=get("BANK_BOXES_SINK", ""),
        tsv=get("BANK_BOXES_TSV", ""),
        workers=get("BANK_BOXES_WORKERS", ""),
        accept_id=get("BANK_BOXES_ACCEPT_ID", ""),
        accept_note=get("BANK_BOXES_ACCEPT_NOTE", ""),
        zones=get("BANK_BOXES_ZONES", ""),
        plan=get("BANK_BOXES_PLAN", ""),
        tree8=get("BANK_BOXES_TREE8", ""),
        arung=get("BANK_BOXES_ARUNG", ""),
        acmd=get("BANK_BOXES_ACMD", ""),
        accept_az=get("BANK_BOXES_ACCEPT_AZ", ""),
        fe_cmd=get("BANK_BOXES_FE_CMD", ""),
        ttl_hours=get("BANK_BOX_TTL_HOURS", ""),
        idle_minutes=get("BANK_BOX_IDLE_MINUTES", ""),
        retry_seconds=get("BANK_DETACH_RETRY_SECONDS", ""),
        proof_workers=get("BANK_PROOF_WORKERS", ""),
        suite_leg=get("BANK_SUITE_LEG", ""),
        root=get("ROOT", ""),
        env={k: v for k, v in environ.items() if not k.startswith(_SHELL_ONLY)},
    )


# --- the shell's readers -----------------------------------------------------------


def out(text: str) -> None:
    """`printf '%s' text`: no newline added."""
    sys.stdout.write(text)
    sys.stdout.flush()


def read_or(path: Path | str, default: str) -> str:
    """`$(cat path 2>/dev/null || echo default)`."""
    try:
        return Path(path).read_text(errors="replace").rstrip("\n")
    except OSError:
        return default


def write_line(path: Path, value: object, *, append: bool = False) -> None:
    """`printf '%s\\n' value >path` (or `>>`)."""
    with open(path, "a" if append else "w") as fh:
        fh.write(f"{value}\n")


def read_lines(path: Path | str) -> list[str]:
    """The lines a `while read` loop over `path` reaches: every newline-terminated one."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    return text.split("\n")[:-1]


def awk_fields(line: str) -> list[str]:
    """awk's default field split: runs of blanks, tabs and newlines, the ends trimmed."""
    trimmed = line.strip(" \t\n")
    return _WS.split(trimmed) if trimmed else []


def awk_records(path: Path | str) -> list[str]:
    """awk's records of `path`, or none when it cannot be read."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    records = text.split("\n")
    return records[:-1] if records and records[-1] == "" else records


def first_field_after(path: Path | str, key: str, index: int) -> str:
    """`awk '$1 == key { print $<index+1>; exit }'`."""
    for record in awk_records(path):
        fields = awk_fields(record)
        if fields and fields[0] == key:
            return fields[index] if len(fields) > index else ""
    return ""


def vb_call(bank: Bank, argv: Sequence[str], log: Path | str, *, mode: str = "w") -> int:
    """`"$BANK_BOXES_VB" argv… >log 2>&1 </dev/null` (`mode` "a" for `>>`): its status."""
    with open(log, mode) as fh:
        return spawn([bank.vb, *argv], env=bank.env, stdout=fh, stderr=STDOUT).returncode


# --- the teardown --------------------------------------------------------------------


def bank_boxes_kill_workers(bank: Bank) -> int:
    """TERM the bank's own children, by pid and nothing else; the list is emptied."""
    for pid in bank.workers.split():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (ValueError, OSError):
            pass
    bank.workers = ""
    return 0


def bank_boxes_down_all(bank: Bank) -> int:
    """`down` every id `boxes.tsv` records, once, emptying it: 0 iff every one went down."""
    if not bank.tsv or not Path(bank.tsv).is_file():
        return 0
    frc = 0
    for line in read_lines(bank.tsv):
        label, box = tab_fields(line, 2)
        if not box:
            continue
        if spawn([bank.vb, "down", box], env=bank.env).returncode == 0:
            continue
        frc = 1
        warn(f"!! pm_push --bank --on-boxes: could not terminate {box} ({label}) — IT IS STILL UP")
        warn("   AND IT IS STILL BILLING, and nothing else is going to notice except its")
        warn("   expiry tag. TAKE IT DOWN BY HAND:")
        warn(f"     scripts/verifier_box.sh down {box}")
        warn("   then read the fleet back:")
        warn("     scripts/verifier_box.sh census")
    Path(bank.tsv).write_text("")
    return frc


def bank_boxes_teardown(bank: Bank, rc: str = "0") -> int:
    """Every way out of the bank after the first `up` takes its boxes down; the status is `rc`'s."""
    status = int(rc) if rc.isdigit() else 2
    bank_boxes_kill_workers(bank)
    if bank.tsv and Path(bank.tsv).is_file() and Path(bank.tsv).stat().st_size > 0:
        warn(f"!! pm_push --bank --on-boxes: the bank stopped (exit {status}) with boxes still up;")
        warn("   taking them down so they cannot become a stale bill.")
        if bank_boxes_down_all(bank) != 0 and status == 0:
            status = 2
    if bank.sink:
        warn(f"   the bank's logs are under {bank.sink}")
    return status


# --- the zone ring -------------------------------------------------------------------


def bank_boxes_zones_read(bank: Bank, vb: str, dest: str) -> int:
    """The wrapper's zone ring into `dest`, one per line: 0, or 2 refused or empty."""
    with open(dest, "w") as fh, open(f"{dest}.err", "w") as err:
        if spawn([vb, "zones"], env=bank.env, stdout=fh, stderr=err).returncode != 0:
            return 2
    return 0 if any(Path(dest).read_text(errors="replace").split("\n")) else 2


def bank_boxes_zone_at(zones: str, idx: str | int) -> int:
    """The `idx`'th zone of the ring, wrapping; nothing for an empty ring."""
    ring = zones.split()
    if ring:
        say(ring[int(idx or 0) % len(ring)])
    return 0


def bank_boxes_zone_after(bank: Bank, want: str) -> int:
    """The zone after `want` in the bank's ring, wrapping; the first when `want` is not in it."""
    say(_zone_after(bank, want))
    return 0


def bank_boxes_plan(
    listing: str, n: str | int, passes: str, zones: str, *, suite_leg: str | None = None
) -> int:
    """One row per shard, `label unit az [k/P] [passes]` TSV; 2 when N cannot cover it."""
    leg = os.environ.get("BANK_SUITE_LEG", "") if suite_leg is None else suite_leg
    boxes = int(n)
    if not zones.split():
        warn(
            "!! pm_push --bank --on-boxes: the zone ring is empty — there is nowhere to spread to."
        )
        return 2
    indiv: list[str] = []
    capable: list[str] = []
    suite: list[str] = []
    for line in read_lines(listing):
        unit, _needs, shards, legs = tab_fields(line, 4)
        if not unit:
            continue
        if f",{leg}," in f",{legs},":
            suite.append(unit)
        (capable if shards == "N-capable" else indiv).append(unit)
    if not indiv and not capable:
        warn("!! pm_push --bank --on-boxes: the unit listing declared no units at all.")
        return 2
    ii, ci = len(indiv), len(capable)
    need = ii + ci
    if boxes < need:
        warn(
            f"!! pm_push --bank --on-boxes {boxes}: this gate declares {need} units"
            f" ({ii} indivisible,"
        )
        warn(f"   {ci} shardable) and {boxes} boxes cannot give every one of them a box.")
        warn("   The floor is DERIVED from ./scripts/check.sh --list-legs, never typed: a bank")
        warn("   that silently dropped a unit is a green that vouches for less than it says.")
        warn("   Nothing was launched.")
        return 2
    per = 2 if boxes >= 7 else 1
    remaining = boxes - ii - ci
    ring = zones.split()
    zslot = 0
    for unit in indiv:
        say(f"{unit}\t{unit}\t{ring[zslot % len(ring)]}\t\t")
        zslot += 1
    for idx, unit in enumerate(capable, start=1):
        rowpasses = passes if unit in suite else ""
        if idx < ci:
            take = min(per - 1, remaining) + 1
            remaining -= take - 1
        else:
            take = 1 + remaining
            remaining = 0
        for k in range(1, take + 1):
            az = ring[zslot % len(ring)]
            say(f"{unit}-{k}of{take}\t{unit}\t{az}\t{k}/{take}\t{rowpasses}")
            zslot += 1
    return 0


# --- the acceptance box --------------------------------------------------------------


def bank_boxes_box_checkout(root: str) -> int:
    """The box's checkout path out of `<root>/deploy/verifier/bake.sh`'s two knob defaults, or 1."""
    bake = Path(f"{root}/deploy/verifier/bake.sh")
    if not (bake.is_file() and os.access(bake, os.R_OK)):
        return 1
    lines = bake.read_text(errors="replace").split("\n")

    def knob(name: str, var: str) -> str:
        pattern = re.compile(rf'^{name}="\$\{{{var}:-(.*)\}}"$')
        found = [m.group(1) for m in map(pattern.match, lines) if m]
        return found[0] if found else ""

    user = knob("BAKE_USER", "DJB_VERIFIER_BAKE_USER")
    path = knob("BAKE_CHECKOUT", "DJB_VERIFIER_CHECKOUT")
    if not user or not path:
        return 1
    say(path.replace("${BAKE_USER}", user))
    return 0


def acceptance_remote_line(checkout: str, rung: str, workers: str) -> str:
    """The one line the acceptance box's shell runs: `--proof` twice under one seed."""
    v = f"$HOME/verify/{rung}"
    return (
        f"mkdir -p {v}; cd {checkout}; "
        f"./scripts/pm_push.sh --proof --where acceptance --workers {workers} --out {v}; "
        'r=$?; [ "${r}" != 1 ] || r=0; exit ${r}'
    )


def bank_boxes_acceptance_remote(checkout: str, rung: str, *, workers: str | None = None) -> int:
    """`acceptance_remote_line` on stdout, no newline; workers default to `BANK_PROOF_WORKERS`."""
    count = os.environ.get("BANK_PROOF_WORKERS", "") if workers is None else workers
    out(acceptance_remote_line(checkout, rung, count))
    return 0


def bank_boxes_acceptance_report(bank: Bank, arc: str = "") -> int:
    """What the acceptance box measured, said in full on every path; always 0."""
    fetched = bank.at("test_impact.json")
    say("")
    if bank.accept_note:
        say(bank.accept_note)
        say("")
        return 0
    if not bank.accept_id:
        say("acceptance: no box — none was asked for.")
        say("")
        return 0
    for record in awk_records(bank.at("acceptance.log")):
        if record.startswith("acceptance: pass1"):
            say(f"  {record}")
            break
    wall = read_or(bank.at("acceptance.wall"), "?")
    say(f"  acceptance box {bank.accept_id} · {wall}s from this Mac")
    if (arc or "1") != "0":
        say(
            f"acceptance: map NOT written (exit {arc or '<no status>'})"
            " — the loop keeps the closure scope"
        )
        say(f"   Its whole log is {bank.sink}/acceptance.log. NOTHING about the verdict")
        say("   above depends on it: a measurement may not refuse a claim every shard passed.")
        say("")
        return 0
    if not (fetched.is_file() and fetched.stat().st_size > 0):
        mrc = proof_field_of(bank.at("acceptance.proof"), "map") or ""
        if mrc in ("", "0"):
            say(
                "acceptance: map NOT written (the box said 0 and no file came back)"
                " — the loop keeps the closure scope"
            )
            say(f"   The fetch log is {bank.sink}/fetch-acceptance.log.")
        else:
            say(
                f"acceptance: map NOT written (the box's map writer exited {mrc})"
                " — the loop keeps the closure scope"
            )
            say(f"   Its log is {bank.sink}/acceptance.log and the fetch log is")
            say(f"   {bank.sink}/fetch-acceptance.log. NOTHING about the verdict above")
            say("   depends on it: a measurement may not refuse a claim every pass passed.")
        say("")
        return 0
    target = Path(f"{bank.root}/scripts/test_impact.json")
    try:
        shutil.copyfile(fetched, target)
    except OSError:
        say(
            f"acceptance: map NOT written (it came back and could not be copied into {bank.root}) —"
        )
        say(f"   the loop keeps the closure scope. It is at {fetched}.")
        say("")
        return 0
    say(f"acceptance: scripts/test_impact.json rewritten from {bank.accept_id}")
    found = {"tree": "", "at": "", "pytest": ""}
    for record in awk_records(target):
        for key in found:
            if f'"{key}"' in record:
                found[key] = record
    tree, at, pytest = (found[k].strip(" \t") for k in ("tree", "at", "pytest"))
    say(f"  generated  {tree} {at} {pytest}")
    say("  It is MODIFIED IN THE WORKING TREE AND NOT COMMITTED — a bank takes no commit.")
    say("  Commit it the way scripts/pytest_durations.json is committed:")
    say("     git add scripts/test_impact.json")
    say("")
    return 0


def bank_boxes_first_match(bank: Bank, path: str, program: str) -> int:
    """`awk program path`, its stdout as it is and its status never read."""
    spawn(["awk", program, path], env=bank.env, stderr=DEVNULL)
    return 0


def proof_field_of(path: Path | str, key: str) -> str | None:
    """The value of `<key>=` in a `leak_proof.txt`, or None when no word names it."""
    for record in awk_records(path):
        for word in awk_fields(record):
            name, eq, value = word.partition("=")
            if eq and name == key:
                return value
    return None


def bank_boxes_proof_field(path: str, key: str) -> int:
    """`<key>=`'s value in the box's `leak_proof.txt` on stdout, or nothing."""
    value = proof_field_of(path, key)
    if value is not None:
        say(value)
    return 0


# --- one launch, one detach, one fetch ------------------------------------------------


def bank_boxes_up_one(
    bank: Bank, label: str, rung: str, az: str, log: str, isshard: str = "0"
) -> int:
    """Bring ONE box up; its launched id reaches `boxes.tsv` before its status is read. Always 0."""
    env = dict(bank.env)
    if isshard == "1":
        env["DJB_VERIFIER_BANK_SHARD"] = "1"
    argv = [bank.vb, "up", "--for", rung, "--az", az]
    argv += ["--ttl", bank.ttl_hours, "--idle", bank.idle_minutes]
    with open(log, "w") as fh:
        urc = spawn(argv, env=env, stdout=fh, stderr=STDOUT).returncode
    lid = first_field_after(log, "launched", 1)
    if lid:
        write_line(Path(bank.tsv), f"{label}\t{lid}", append=True)
    write_line(bank.at(f"{label}.up.rc"), urc)
    if urc != 0:
        return 0
    uid = first_field_after(log, "instance", 1)
    if not uid:
        write_line(bank.at(f"{label}.up.rc"), 2)
        return 0
    write_line(bank.at(f"{label}.id"), uid)
    market = first_field_after(log, "market", 1)
    bank.at(f"{label}.market").write_text(f"{market}\n" if _has_first(log, "market") else "")
    if uid != lid:
        write_line(Path(bank.tsv), f"{label}\t{uid}", append=True)
    return 0


def _has_first(path: str, key: str) -> bool:
    """Whether some record of `path` has `key` as its first field."""
    return any((f := awk_fields(r)) and f[0] == key for r in awk_records(path))


def bank_boxes_vb_255(bank: Bank, label: str, what: str, log: str, argv: Sequence[str]) -> int:
    """One wrapper call with the one retry ssh's 255 gets: its status."""
    rc = 0
    for attempt in (1, 2):
        rc = vb_call(bank, argv, log)
        if rc == 255 and attempt == 1:
            say(
                f"pm_push --bank --on-boxes: {label}: the {what} exited 255 — that is ssh, not"
                " the gate, and the tunnel is usually a few seconds behind the agent. Waiting"
                f" {bank.retry_seconds}s and retrying the {what}, once."
            )
            spawn(["sleep", bank.retry_seconds], env=bank.env)
            continue
        break
    return rc


def bank_boxes_detach(
    bank: Bank, label: str, lid: str, unit: str, shard: str, passes: str, log: str
) -> int:
    """One unit of the gate detached on one box, its status in `<label>.leg.rc`. Always 0."""
    legargv = ["leg", lid, "--unit", unit]
    if shard:
        legargv += ["--shard", shard]
    if passes == "1":
        legargv += ["--passes", "1"]
    legargv += ["--log", "leg"]
    rc = bank_boxes_vb_255(bank, label, "detach", log, legargv)
    write_line(bank.at(f"{label}.leg.rc"), rc)
    return 0


def frontend_remote_line(checkout: str, directory: str) -> str:
    """The box's command string for the fe leg's own frozen install."""
    return (
        f"cd {checkout} && bash -c '. ./scripts/fe_gate.sh && fe_leg_frozen_lockfile {directory}'"
    )


def bank_boxes_frontend_remote(checkout: str, directory: str) -> int:
    """`frontend_remote_line` on stdout, no newline."""
    out(frontend_remote_line(checkout, directory))
    return 0


def bank_boxes_frontend_install(bank: Bank, label: str, fid: str) -> int:
    """The frontend toolchain on one shard's box before its unit, timed; always 0."""
    if not bank.fe_cmd:
        return 0
    log = f"{bank.sink}/frontend-{label}.log"
    t0 = clock_s()
    rc = bank_boxes_vb_255(bank, label, "frontend install", log, ["run", fid, "--", bank.fe_cmd])
    took = clock_s() - t0
    say(f"pm_push --bank --on-boxes: {label}: frontend install exited {rc} in {took}s ({log})")
    return 0


def bank_boxes_fetch_shard(bank: Bank, label: str, fid: str) -> int:
    """One shard's leg log and status, fetched by the worker that waited on it."""
    if not fid:
        return 0
    remote = f"~/verify/bank-{bank.tree8}-{label}"
    log = bank.at(f"fetch-{label}.log")
    vb_call(bank, ["fetch", fid, f"{remote}/leg.log", f"{bank.sink}/{label}.log"], log)
    vb_call(bank, ["fetch", fid, f"{remote}/leg.rc", f"{bank.sink}/{label}.rc"], log, mode="a")
    return 0


def bank_boxes_fetch_acceptance_files(bank: Bank, arc: str = "", box: str | None = None) -> int:
    """The acceptance box's map (only after a 0), proof and two pass logs, in one place."""
    accept = bank.accept_id if box is None else box
    if not accept:
        return 0
    v = f"~/verify/{bank.arung}"
    sink = bank.sink
    if (arc or "1") == "0":
        rc = vb_call(
            bank,
            ["fetch", accept, f"{v}/test_impact.json", f"{sink}/test_impact.json"],
            f"{sink}/fetch-acceptance.log",
        )
        write_line(bank.at("acceptance.fetch.rc"), rc)
    rc = vb_call(
        bank,
        ["fetch", accept, f"{v}/leak_proof.txt", f"{sink}/acceptance.proof"],
        f"{sink}/fetch-proof.log",
    )
    write_line(bank.at("acceptance.proof.fetch.rc"), rc)
    for p in ("pass1", "pass2"):
        vb_call(bank, ["fetch", accept, f"{v}/{p}.log", f"{sink}/{p}.log"], f"{sink}/fetch-{p}.log")
    return 0


# --- a reclaim is one more box, in the next zone, once ---------------------------------


def saw_reclaim(*paths: str) -> bool:
    """Whether one of `paths` carries the wrapper's `box reclaimed` line."""
    for path in paths:
        try:
            if "box reclaimed" in Path(path).read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


def bank_boxes_saw_reclaim(*paths: str) -> int:
    """0 iff one of `paths` carries the wrapper's `box reclaimed` line."""
    return 0 if saw_reclaim(*paths) else 1


def reclaim_status_of(*paths: str) -> str:
    """The spot status the wrapper named on its `box reclaimed` line, or `status unread`."""
    for path in paths:
        for record in awk_records(path):
            if "box reclaimed" not in record:
                continue
            fields = awk_fields(record)
            if "status" in fields:
                i = fields.index("status")
                found = " ".join(fields[i + 1 :])
                if found:
                    return found
                break
    return "status unread"


def bank_boxes_reclaim_status(*paths: str) -> int:
    """The spot status code a reclaim left behind, or `status unread`, on stdout."""
    say(reclaim_status_of(*paths))
    return 0


def _retry_shard(bank: Bank, label: str, unit: str, nextaz: str, shard: str, passes: str) -> None:
    """One reclaimed shard's second box: up, install, detach, wait, fetch."""
    sink = bank.sink
    bank_boxes_up_one(
        bank, label, f"bank-{bank.tree8}-{label}", nextaz, f"{sink}/up-{label}-retry.log", "1"
    )
    if read_or(bank.at(f"{label}.up.rc"), "2") != "0":
        say(
            f"pm_push --bank --on-boxes: {label}: the second box did not come up either"
            f" ({sink}/up-{label}-retry.log); the shard stays LOST and this bank will refuse."
        )
        return
    newid = read_or(bank.at(f"{label}.id"), "")
    bank_boxes_frontend_install(bank, label, newid)
    bank_boxes_detach(bank, label, newid, unit, shard, passes, f"{sink}/leg-{label}-retry.log")
    if read_or(bank.at(f"{label}.leg.rc"), "2") != "0":
        say(
            f"pm_push --bank --on-boxes: {label}: the unit could not be detached on {newid};"
            " the shard stays LOST."
        )
        return
    began = clock_s()
    write_line(bank.at(f"{label}.began"), began)
    vb_call(bank, ["wait", newid, "leg"], f"{sink}/wait-{label}.log")
    write_line(bank.at(f"{label}.wall"), clock_s() - int(read_or(bank.at(f"{label}.began"), "0")))
    bank_boxes_fetch_shard(bank, label, newid)


def _retry_acceptance(bank: Bank, nextaz: str) -> None:
    """The acceptance box's second box: up, run the proof, fetch its files."""
    sink = bank.sink
    bank_boxes_up_one(
        bank, "acceptance", bank.arung, nextaz, f"{sink}/up-acceptance-retry.log", "0"
    )
    if read_or(bank.at("acceptance.up.rc"), "2") != "0":
        say(
            "pm_push --bank --on-boxes: acceptance: the second box did not come up either;"
            " the leak proof stays unread."
        )
        return
    aid = read_or(bank.at("acceptance.id"), "")
    arrc = vb_call(bank, ["run", aid, "--", bank.acmd], f"{sink}/acceptance.log")
    write_line(bank.at("acceptance.rc"), arrc)
    bank_boxes_fetch_acceptance_files(bank, str(arrc), box=aid)


def bank_boxes_retry_reclaimed(bank: Bank) -> int:
    """Once, after every log is home: each reclaimed box gets one more box in the next zone."""
    sink = bank.sink
    workers: list[threading.Thread] = []

    def start(target: Callable[..., None], *args: str) -> None:
        worker = threading.Thread(target=target, args=(bank, *args), daemon=True)
        worker.start()
        workers.append(worker)

    for line in read_lines(bank.plan):
        label, unit, az, shard, passes = tab_fields(line, 5)
        if not label or bank.at(f"{label}.retried").exists():
            continue
        logs = (f"{sink}/wait-{label}.log", f"{sink}/fetch-{label}.log")
        if not saw_reclaim(*logs):
            continue
        oldid = read_or(bank.at(f"{label}.id"), "<unnamed>")
        status = reclaim_status_of(*logs)
        nextaz = _zone_after(bank, az)
        write_line(bank.at(f"{label}.retried"), f"{oldid}\t{status}")
        say(f"pm_push --bank --on-boxes: {label}: the box was RECLAIMED ({status}).")
        say(f"    One more box, in {nextaz} — capacity is a per-zone fact and {az} has just")
        say(f"    said no. {oldid} stays on the teardown list; a reclaimed instance is")
        say("    'already gone' to a down, never a refusal.")
        start(_retry_shard, label, unit, nextaz, shard, passes)
    alogs = (f"{sink}/acceptance.log", f"{sink}/fetch-proof.log", f"{sink}/fetch-acceptance.log")
    if bank.accept_id and not bank.at("acceptance.retried").exists() and saw_reclaim(*alogs):
        oldid = bank.accept_id
        status = reclaim_status_of(*alogs)
        nextaz = _zone_after(bank, bank.accept_az)
        write_line(bank.at("acceptance.retried"), f"{oldid}\t{status}")
        say(f"pm_push --bank --on-boxes: acceptance: the box was RECLAIMED ({status}).")
        say(f"    One more box, in {nextaz}. Every pytest shard ran ONE pass, so this box")
        say("    IS the leak proof and a bank without it refuses over eight green shards.")
        start(_retry_acceptance, nextaz)
    if workers:
        for worker in workers:
            worker.join()
        if bank.at("acceptance.retried").exists():
            bank.accept_id = read_or(bank.at("acceptance.id"), "")
            if bank.accept_id:
                bank.accept_note = ""
        say("")
    bank.workers = ""
    return 0


def _zone_after(bank: Bank, want: str) -> str:
    """`$(bank_boxes_zone_after want)`."""
    ring = bank.zones.split()
    for here, after in zip(ring, ring[1:], strict=False):
        if here == want:
            return after
    return ring[0] if ring else ""


# --- which test failed, and the command that replays it --------------------------------


def bank_boxes_first_failing(log: str, what: str, seed: str, *, workers: str | None = None) -> int:
    """One line naming the first `FAILED` nodeid and its replay command, or `none named`."""
    count = os.environ.get("BANK_PROOF_WORKERS", "") if workers is None else workers
    failed = [awk_fields(r) for r in awk_records(log) if r.startswith("FAILED ")]
    node = failed[0][1] if failed and len(failed[0]) > 1 else ""
    if not node:
        say(f"first failing: none named - no FAILED line in {log}")
        return 0
    say(
        f"first failing: {node} ({what}; {len(failed)} FAILED) - replay: ./scripts/test.sh"
        f" -n {count} --randomly-seed={seed or '<seed unread>'} {node}"
    )
    return 0


def log_seed_of(log: str) -> str:
    """The seed pytest-randomly printed at the top of `log`, or ''."""
    token = "--randomly-seed="  # noqa: S105 — the pytest flag prefix the seed is parsed from
    for record in awk_records(log):
        if token in record:
            digits = re.match(r"[0-9]*", record[record.index(token) + len(token) :])
            if digits and digits.group():
                return digits.group()
    return ""


def bank_boxes_log_seed(log: str) -> int:
    """The seed pytest-randomly printed at the top of that run, on stdout."""
    seed = log_seed_of(log)
    if seed:
        say(seed)
    return 0


# --- the table ---------------------------------------------------------------------------


def _row(*cells: str) -> str:
    """`printf '  %-26s %-21s %-9s %-14s %-6s %-3s %-7s %s'`."""
    widths = (26, 21, 9, 14, 6, 3, 7)
    padded = [f"{c:<{w}}" for c, w in zip(cells, widths, strict=False)]
    return "  " + " ".join([*padded, cells[-1]])


def _retried_from(path: Path) -> str:
    """`retried-from <old id> (<status>)` out of a `.retried` file's first record."""
    records = awk_records(path)
    if not records:
        return ""
    first = records[0]
    fields = awk_fields(first)
    return f"retried-from {fields[0] if fields else ''} ({first[first.find(chr(9)) + 1 :]})"


def bank_boxes_table(bank: Bank) -> int:
    """The per-shard table, printed on every exit path."""
    say("")
    say(_row("shard", "box", "market", "az", "passes", "rc", "wall", "tree"))
    for line in read_lines(bank.at("plan.tsv")):
        label, _unit, az, _shard, passes = tab_fields(line, 5)
        if not label:
            continue
        box = read_or(bank.at(f"{label}.id"), "-")
        rc = read_or(bank.at(f"{label}.rc"), "?")
        wall = read_or(bank.at(f"{label}.legwall"), read_or(bank.at(f"{label}.wall"), "?"))
        tree = read_or(bank.at(f"{label}.tree"), "-")
        market = read_or(bank.at(f"{label}.market"), "") or "-"
        say(_row(label, box, market, az or "-", passes or "-", rc, f"{wall}s", tree))
        if bank.at(f"{label}.retried").is_file():
            say(f"    {_retried_from(bank.at(f'{label}.retried'))}")
    if bank.at("acceptance.retried").is_file():
        retried = _retried_from(bank.at("acceptance.retried"))
        say(f"  {'acceptance':<26} {bank.accept_id or '-':<21} ")
        say(f"    {retried}")
    valve = bank.env.get("DJB_VERIFIER_ON_DEMAND_OK", "")
    if valve:
        say(f"  on-demand valve: {valve}")
    else:
        say("  on-demand valve: unset — a shard whose Spot request is refused could not")
        say("    launch, and this bank refuses rather than buying on-demand for it.")
    say("")
    return 0


# --- the image (ADR deploy-4a) ------------------------------------------------------------


def image_remote_line(
    checkout: str, tag: str, registry: str, region: str, web: str, worker: str
) -> str:
    """The one line the box's shell runs to build, push and read back both images."""
    host = registry.split("/", 1)[0]
    return (
        f"set -e; cd {checkout}; export DJB_IMAGE_REGISTRY={registry}; "
        "t=$(./deploy/provision.sh image-tag); "
        f'if [ "$t" != "{tag}" ]; then '
        f"echo \"!! image: refusing to build under '$t' — this bank keys on {tag}\"; "
        "echo '   what moved under it (git status --short, first 10):'; "
        "git status --short | sed -n '1,10p'; exit 3; fi; "
        f"p=$(aws ecr get-login-password --region {region}); "
        f"printf '%s' \"$p\" | docker login --username AWS --password-stdin {host}; "
        "T0=$(date +%s); "
        f"docker build --target web --tag {web} .; docker push {web}; "
        "T1=$(date +%s); "
        f"docker build --target worker --tag {worker} .; docker push {worker}; "
        "T2=$(date +%s); "
        'echo "image: seconds web $((T1-T0)) worker $((T2-T1))"; '
        f'echo "image: digest web $(./deploy/provision.sh image-digest web {tag})"; '
        f'echo "image: digest worker $(./deploy/provision.sh image-digest worker {tag})"; '
        "echo \"image: platform $(docker image inspect --format '{{.Os}}/{{.Architecture}}'"
        f' {web})"; '
        f"docker logout {host} || true"
    )


def bank_boxes_image_remote(
    checkout: str, tag: str, registry: str, region: str, web: str, worker: str
) -> int:
    """`image_remote_line` on stdout, no newline."""
    out(image_remote_line(checkout, tag, registry, region, web, worker))
    return 0


def _image_ref(bank: Bank, service: str, tag: str) -> str | None:
    """`(cd "$ROOT" && ./deploy/provision.sh image-ref <service> <tag> 2>/dev/null)`, or None."""
    rc, ref = capture(
        ["./deploy/provision.sh", "image-ref", service, tag],
        env=bank.env,
        cwd=Path(bank.root),
    )
    return ref if rc == 0 else None


def _log_field(log: Path, prefix: str, index: int) -> str:
    """`awk '/^<prefix>/ { print $<index+1>; exit }' log`."""
    for record in awk_records(log):
        if record.startswith(prefix):
            fields = awk_fields(record)
            return fields[index] if len(fields) > index else ""
    return ""


def bank_boxes_image(bank: Bank, checkout: str = "", tag: str = "") -> int:
    """The image built once, by the bank, from the banked tree, on one box; always 0."""
    say("")
    if not checkout:
        say("image: not built — deploy/verifier/bake.sh does not say where a box's checkout")
        say("   lives, so there is nothing to build FROM. The row above stands.")
        return 0
    ref_web = _image_ref(bank, "web", tag)
    ref_worker = _image_ref(bank, "worker", tag) if ref_web is not None else None
    if ref_web is None or ref_worker is None:
        say("image: not built — no registry coordinate")
        say("   DJB_IMAGE_REGISTRY is unset here and deploy/.env carries none, so there is")
        say("   no name to push under. The verdict row above STANDS: the image is not the")
        say("   verdict. Set it and the next bank builds one; CI builds it meanwhile.")
        return 0
    suffix = _TAG_SUFFIX.format(service="web", tag=tag)
    registry = ref_web[: -len(suffix)] if ref_web.endswith(suffix) else ref_web
    if registry == ref_web or not registry:
        say(f"image: not built — deploy/provision.sh image-ref answered '{ref_web}', which is")
        say(f"   not <registry>/djb-web:{tag}. Nothing here will guess a registry. The row stands.")
        return 0
    host = registry.split("/", 1)[0]
    if not fnmatch.fnmatchcase(host, "*.dkr.ecr.*.amazonaws.com"):
        say(f"image: not built — {host} is not an ECR registry, and this step only knows")
        say("   how to mint an ECR token from a box's own role. The row above stands.")
        return 0
    parts = host.split(".")
    region = parts[3] if len(parts) > 3 else ""
    box = bank.accept_id
    why = "the acceptance box — the one box outside the composed verdict"
    if not box:
        label = next((r.split("\t")[0] for r in awk_records(bank.at("plan.tsv")) if r), "")
        if label:
            box = read_or(bank.at(f"{label}.id"), "")
        why = f"shard {label} — this bank has no acceptance box"
    if not box:
        say("image: not built — no box is still up to build on. The row above stands.")
        return 0
    log = bank.at("image.log")
    cmd = image_remote_line(checkout, tag, registry, region, ref_web, ref_worker)
    say(f"pm_push --bank --on-boxes: building the image on {box} ({why}).")
    say(f"  tag           {tag}")
    say(f"  refs          {ref_web}")
    say(f"                {ref_worker}")
    rc = vb_call(bank, ["run", box, "--", cmd], log)
    if rc != 0:
        say(f"image: NOT built (exit {rc}) — and the verdict row above STANDS.")
        say("   An image is downstream of a verdict and never part of one: the gate measured")
        say("   the tree, this step only names it in a registry. CI's images job builds a tag")
        say("   the registry does not have, which is the fallback ADR deploy-4a argues from.")
        for record in awk_records(log)[-15:]:
            say(f"     | {record}")
        return 0
    secs_web = _log_field(log, "image: seconds ", 3)
    secs_worker = _log_field(log, "image: seconds ", 5)
    dg_web = _log_field(log, "image: digest web ", 3)
    dg_worker = _log_field(log, "image: digest worker ", 3)
    platform = _log_field(log, "image: platform ", 2)
    say(f"image: {tag} pushed (web {secs_web or '?'}s, worker {secs_worker or '?'}s)")
    say(
        f"image: web {dg_web or '<no digest read back>'}"
        f" worker {dg_worker or '<no digest read back>'}"
    )
    say(f"  platform      {platform or '<unread>'} — the box's own architecture, built natively")
    say(f"  box log       {log}")
    return 0


# --- the wrapper lines' entry -------------------------------------------------------------

Body = Callable[..., int]
_STATEFUL: dict[str, Body] = {
    "bank_boxes_kill_workers": bank_boxes_kill_workers,
    "bank_boxes_down_all": bank_boxes_down_all,
    "bank_boxes_teardown": bank_boxes_teardown,
    "bank_boxes_zones_read": bank_boxes_zones_read,
    "bank_boxes_zone_after": bank_boxes_zone_after,
    "bank_boxes_acceptance_report": bank_boxes_acceptance_report,
    "bank_boxes_first_match": bank_boxes_first_match,
    "bank_boxes_up_one": bank_boxes_up_one,
    "bank_boxes_detach": bank_boxes_detach,
    "bank_boxes_frontend_install": bank_boxes_frontend_install,
    "bank_boxes_fetch_shard": bank_boxes_fetch_shard,
    "bank_boxes_fetch_acceptance_files": bank_boxes_fetch_acceptance_files,
    "bank_boxes_retry_reclaimed": bank_boxes_retry_reclaimed,
    "bank_boxes_table": bank_boxes_table,
    "bank_boxes_image": bank_boxes_image,
}
_PURE: dict[str, Body] = {
    "bank_boxes_zone_at": bank_boxes_zone_at,
    "bank_boxes_plan": bank_boxes_plan,
    "bank_boxes_box_checkout": bank_boxes_box_checkout,
    "bank_boxes_acceptance_remote": bank_boxes_acceptance_remote,
    "bank_boxes_proof_field": bank_boxes_proof_field,
    "bank_boxes_frontend_remote": bank_boxes_frontend_remote,
    "bank_boxes_saw_reclaim": bank_boxes_saw_reclaim,
    "bank_boxes_reclaim_status": bank_boxes_reclaim_status,
    "bank_boxes_first_failing": bank_boxes_first_failing,
    "bank_boxes_log_seed": bank_boxes_log_seed,
    "bank_boxes_image_remote": bank_boxes_image_remote,
}
#: Every wrapper line's function, by its shell name.
BODIES: dict[str, Body] = {**_STATEFUL, **_PURE}
_FIXED_ARITY = {
    "bank_boxes_zone_at": 2,
    "bank_boxes_plan": 4,
    "bank_boxes_box_checkout": 0,
    "bank_boxes_acceptance_remote": 2,
    "bank_boxes_proof_field": 2,
    "bank_boxes_frontend_remote": 2,
    "bank_boxes_first_failing": 3,
    "bank_boxes_log_seed": 1,
    "bank_boxes_image_remote": 6,
    "bank_boxes_kill_workers": 0,
    "bank_boxes_down_all": 0,
    "bank_boxes_teardown": 1,
    "bank_boxes_zones_read": 2,
    "bank_boxes_zone_after": 1,
    "bank_boxes_acceptance_report": 1,
    "bank_boxes_first_match": 2,
    "bank_boxes_up_one": 5,
    "bank_boxes_detach": 6,
    "bank_boxes_frontend_install": 2,
    "bank_boxes_fetch_shard": 2,
    "bank_boxes_fetch_acceptance_files": 1,
    "bank_boxes_retry_reclaimed": 0,
    "bank_boxes_table": 0,
    "bank_boxes_image": 2,
}


def main(argv: Sequence[str] | None = None) -> int:
    """`<python> -c '…main()' <bank_boxes_name> [args…]`: the shell body's own status."""
    args = list(sys.argv[1:] if argv is None else argv)
    name = args[0] if args else ""
    body = BODIES.get(name)
    if body is None:
        warn(f"!! pm_push: '{name}' is not one of the bank's bodies: {' '.join(sorted(BODIES))}")
        return 2
    rest = args[1:]
    arity = _FIXED_ARITY.get(name)
    if arity is not None:
        rest = (rest + [""] * arity)[:arity] if arity else []
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    if name == "bank_boxes_box_checkout":
        return bank_boxes_box_checkout(os.environ.get("ROOT", ""))
    if name in _STATEFUL:
        return body(bank_of(dict(os.environ)), *rest)
    return body(*rest)
