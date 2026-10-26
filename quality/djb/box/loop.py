"""`loop` and `leg`: the gate, or one unit of it, detached on the box behind the tree pre-flight."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Sequence

from quality.djb.box.core import Box, Command, vb_log
from quality.djb.box.transport import (
    die,
    last_line,
    measured_tree_here,
    spawn,
    verifier_checkout_path,
)

_UNIT = re.compile(r"[A-Za-z0-9._-]+")
_SHARD = re.compile(r"[0-9]+/[0-9]+")
_CALLER = re.compile(r"[a-z-]+")
_PID = re.compile(r"[0-9]+")
# The tail every detach shares: unpiped, its status to `.rc`, the idle clock restarted on exit.
_TAIL = (
    " > ~/verify/{rung}/{name}.log 2>&1; echo $? > ~/verify/{rung}/{name}.rc;"
    " touch /run/verifier/last-activity 2>/dev/null || true'; }}"
    " </dev/null >/dev/null 2>&1 & echo $!"
)


def box_ledger_ingest(checkout: str, rung: str) -> str:
    """The remote `{ …|| true; }` group appending `ledger.in`'s new lines to the box's ledger."""
    ledger = "$(bash -c '. scripts/gate_ledger.sh >/dev/null 2>&1 && gate_ledger_path')"
    incoming = f"~/verify/{rung}/ledger.in"
    return (
        f'{{ L={ledger}; if [ -n "$L" ] && [ -f {incoming} ]; then while IFS= read -r l; do'
        f' [ -z "$l" ] || grep -qxF -- "$l" "$L" 2>/dev/null || printf \'%s\\n\' "$l" >> "$L";'
        f" done < {incoming}; fi || true; }}"
    )


def _options(args: Sequence[str], sub: str, takes: dict[str, str]) -> dict[str, str]:
    """`--flag value` pairs for `sub`; a flag with no value refuses by its own sentence."""
    found = dict.fromkeys(takes, "")
    rest = list(args)
    while rest:
        word = rest.pop(0)
        if word not in takes:
            die(f"verifier_box: unknown argument '{word}' to {sub}")
        if not rest:
            die(f"verifier_box: {takes[word]}")
        found[word] = rest.pop(0)
    return found


def _box_trees(box: Box, instance: str, checkout: str, what: str, verdict: str) -> str:
    """The box's worktree tree, refused unless it is the main the box was last pushed."""
    head = box.measured_tree_on_box(instance, checkout, "HEAD")
    main = box.measured_tree_on_box(instance, checkout, "refs/heads/main")
    if not head or not main:
        die(
            "verifier_box: could not read the box's own trees"
            f" (worktree '{head or '<unreadable>'}',\n"
            f"   main '{main or '<unreadable>'}'). A {what} launched now would measure a tree\n"
            "   nothing here can name. Nothing was launched."
        )
    if head != main:
        die(
            f"verifier_box: the box's checkout is not the pushed tree — run push {instance}.\n"
            f"   its working tree is {head}\n"
            f"   its main is       {main}\n"
            "   A push moves a ref; it moves no files, and this box parks off main on purpose.\n"
            f"   {verdict} Nothing was launched."
        )
    return head


def _detach(box: Box, instance: str, remote: str, what: str) -> str:
    """Send `remote` over the one transport; the pid its last stdout line names, else a refusal."""
    with tempfile.TemporaryFile() as sink:
        spawn(box.ssh_argv(instance, remote), env=box.cfg.env, stdout=sink)
        sink.seek(0)
        pid = last_line(sink.read().decode(errors="replace"))
    if not _PID.fullmatch(pid):
        die(f"verifier_box: the box did not return a pid for the detached {what}")
    return pid


def cmd_loop(box: Box, args: Sequence[str]) -> int:
    """`loop <id> --log <name>`: the per-rung gate detached on a box standing on HEAD's tree."""
    instance = args[0] if args else ""
    if not instance:
        die("verifier_box: loop needs an instance id")
    name = _options(args[1:], "loop", {"--log": "--log takes a name"})["--log"]
    if not name:
        die("verifier_box: loop needs --log <name>")
    box.refuse_if_reclaimed(instance)
    rung = box.box_rung(instance)
    checkout = verifier_checkout_path()
    box_tree = _box_trees(
        box,
        instance,
        checkout,
        "gate",
        "A gate launched now would measure what the image was baked with and bank a\n"
        "   verdict about it.",
    )
    here = measured_tree_here("HEAD", box.cfg.env)
    if not here:
        die(
            "verifier_box: could not read this checkout's HEAD tree, so there is nothing to hold"
            f" the box's\n   {box_tree} up against. Nothing was launched."
        )
    if box_tree != here:
        die(
            f"verifier_box: the box holds {box_tree[:12]}, HEAD measures {here[:12]}"
            " — push first:\n"
            f"   scripts/verifier_box.sh push {instance}\n"
            "   The box is standing on an earlier push. A gate launched now would bank a\n"
            "   verdict about THAT tree and wait would print it as this checkout's. Nothing\n"
            "   was launched."
        )
    ingest = box_ledger_ingest(checkout, rung)
    word = box.cfg.env.get("DJB_GATE_CALLER", "")
    if word and not _CALLER.fullmatch(word):
        die(
            f"verifier_box: DJB_GATE_CALLER='{word}' is not a caller word (lower case and"
            " dashes). Nothing was launched."
        )
    caller = f"DJB_GATE_CALLER={word} " if word else ""
    remote = (
        f"{{ mkdir -p ~/verify/{rung} && cd {checkout} && {ingest} && setsid nohup sh -c"
        f" '{caller}DJB_GATE_SLOTS=1 DJB_LOOP_SCOPE_BASE=refs/djb/base ./scripts/check.sh --loop"
        + _TAIL.format(rung=rung, name=name)
    )
    pid = _detach(box, instance, remote, "gate")
    (box.box_dir(instance) / f"{name}.pid").write_text(f"{pid}\n")
    vb_log(f"gate detached on {instance} as pid {pid}; log ~/verify/{rung}/{name}.log")
    vb_log(f"read it with: scripts/verifier_box.sh wait {instance} {name}")
    return 0


def cmd_leg(box: Box, args: Sequence[str]) -> int:
    """`leg <id> --unit <unit> [--shard k/N] [--passes 1|2] --log <name>`: one unit, detached."""
    instance = args[0] if args else ""
    if not instance:
        die(
            "verifier_box: leg needs an instance id: leg <id> --unit <unit> [--shard k/N]"
            " [--passes 1|2] --log <name>"
        )
    takes = {
        "--unit": "--unit takes a unit name",
        "--shard": "--shard takes k/N",
        "--passes": "--passes takes 1 or 2",
        "--log": "--log takes a name",
    }
    opts = _options(args[1:], "leg", takes)
    unit, shard, passes, name = (opts[flag] for flag in takes)
    if not unit:
        die(
            "verifier_box: leg needs --unit <unit>: it runs ONE unit of the full gate, and the\n"
            "   units are the gate's own — ./scripts/check.sh --list-legs prints them."
        )
    if not name:
        die(
            "verifier_box: leg needs --log <name>: the box writes the unit's output to\n"
            "   ~/verify/<rung>/<name>.log and its status to <name>.rc, and 'wait <id> <name>'\n"
            "   is how they are read back."
        )
    # The charset walls are about the single-quoted `sh -c '…'` on the box, never the unit table.
    if not _UNIT.fullmatch(unit):
        die(
            f"verifier_box: '{unit}' is not a unit name — letters, digits, dot, underscore\n"
            "   and hyphen only. Nothing was sent. (Which units EXIST is the box's gate's\n"
            "   answer, not this wrapper's: ./scripts/check.sh --list-legs.)"
        )
    if shard and not _SHARD.fullmatch(shard):
        die(f"verifier_box: --shard takes k/N, got '{shard}'. Nothing was sent.")
    if passes and passes not in ("1", "2"):
        die(f"verifier_box: --passes takes 1 or 2, got '{passes}'. Nothing was sent.")
    box.refuse_if_reclaimed(instance)
    rung = box.box_rung(instance)
    checkout = verifier_checkout_path()
    _box_trees(
        box,
        instance,
        checkout,
        "unit",
        "A unit launched now would measure what the image was baked with and its shard\n"
        "   of a composed verdict would vouch for it.",
    )
    ingest = box_ledger_ingest(checkout, rung)
    modifiers = (f" --shard {shard}" if shard else "") + (f" --passes {passes}" if passes else "")
    remote = (
        f"{{ mkdir -p ~/verify/{rung} && cd {checkout} && {ingest} && setsid nohup sh -c"
        f" './scripts/check.sh --leg {unit}{modifiers}" + _TAIL.format(rung=rung, name=name)
    )
    pid = _detach(box, instance, remote, "unit")
    (box.box_dir(instance) / f"{name}.pid").write_text(f"{pid}\n")
    said = (f" shard {shard}" if shard else "") + (f" passes {passes}" if passes else "")
    vb_log(f"unit {unit}{said} detached on {instance} as pid {pid}; log ~/verify/{rung}/{name}.log")
    vb_log(f"read it with: scripts/verifier_box.sh wait {instance} {name}")
    return 0


COMMANDS: dict[str, Command] = {"loop": cmd_loop, "leg": cmd_leg}
