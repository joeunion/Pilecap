"""`up`: the walls, the image, a warm box claimed or one launched, the push, the summary."""

from __future__ import annotations

import os
from collections.abc import Sequence

from quality.djb.box.census import age_minutes, blank, market_of_lifecycle, rows_of, warm_pool_rows
from quality.djb.box.core import TTL_CAP, Box, Command, clock_s, vb_log
from quality.djb.box.launch import launch_one_box, require_headroom, wait_for_ssm
from quality.djb.box.push import cmd_push
from quality.djb.box.transport import Refused, die, say, warn

PAD = " " * 11


def claim_warm_box(box: Box, image: str, rung: str) -> tuple[str, str]:
    """Claim one warm box for `rung`, or say why each was skipped: `(id, type)`, or two blanks."""
    rows = warm_pool_rows(box)
    if blank(rows):
        say("no warm box — launching")
        return "", ""
    now = clock_s()
    for instance, launched, ami, type_, _price in rows_of(rows, 5):
        if ami != image:
            say(f"skipped {instance}: image {ami} ≠ {image}")
            continue
        if not os.access(box.box_key(instance), os.R_OK):
            say(f"skipped {instance}: no key on this machine")
            continue
        try:
            (box.box_dir(instance) / "claim").mkdir()
        except OSError:
            say(f"skipped {instance}: already claimed on this machine")
            continue
        if not box.aws_ok(
            "ec2", "create-tags", "--resources", instance, "--tags", f"Key=djb:for,Value={rung}"
        ):
            vb_log(
                f"           NOTE: could not tag {instance} with djb:for={rung}; it IS claimed on"
                " this machine (the directory is the lock) but the census will still call it"
                " warm.",
                err=True,
            )
        (box.box_dir(instance) / "rung").write_text(f"{rung}\n")
        say(f"claimed {instance} (warm, {age_minutes(launched, now)}m)")
        return instance, type_
    say("no warm box — launching")
    return "", ""


def cmd_up(box: Box, args: Sequence[str]) -> int:
    """`up --for <rung> …`: a warm box claimed or one launched, pushed to, and summarised."""
    cfg = box.cfg
    opts = {"rung": "", "ttl": cfg.ttl_hours, "idle": cfg.idle_minutes, "image": ""}
    opts.update({"type": cfg.instance_type, "az": ""})
    takes = {
        "--az": (
            "az",
            f"--az takes an availability zone (e.g. {cfg.region}a); 'zones' lists them",
        ),
        "--image-id": ("image", "--image-id takes an ami id"),
        "--for": ("rung", "--for takes a rung id"),
        "--ttl": ("ttl", "--ttl takes hours"),
        "--idle": ("idle", "--idle takes minutes"),
        "--type": ("type", "--type takes an instance type"),
    }
    flags: set[str] = set()
    rest = list(args)
    while rest:
        word = rest.pop(0)
        if word in takes:
            key, sentence = takes[word]
            if not rest:
                die(f"verifier_box: {sentence}")
            opts[key] = rest.pop(0)
            flags.add(word)
        elif word in ("--on-demand", "--no-push"):
            flags.add(word)
        else:
            die(f"verifier_box: unknown argument '{word}' to up")
    if not opts["rung"]:
        die(
            "verifier_box: up needs --for <rung>: the tag and the box's log directory are"
            " named after it"
        )
    if not opts["ttl"].isdigit():
        die(f"verifier_box: --ttl takes whole hours, got '{opts['ttl']}'")
    if not opts["idle"].isdigit():
        die(f"verifier_box: --idle takes whole minutes, got '{opts['idle']}'")
    if int(opts["ttl"]) > TTL_CAP:
        die(
            f"verifier_box: --ttl {opts['ttl']} is above the {TTL_CAP}h cap. Nothing was"
            " launched. The cap is the\n"
            "   only thing between a forgotten box and an unbounded bill; a verification that\n"
            "   genuinely needs longer is a conversation, not a flag."
        )
    if int(opts["ttl"]) < 1:
        die("verifier_box: --ttl must be at least 1 hour")
    box.require_profile()
    box.require_plugin()
    image = box.require_named_image(opts["image"]) if opts["image"] else box.require_image()
    instance, type_ = claim_warm_box(box, image, opts["rung"])
    az = lifecycle = ""
    answered = False
    if instance:
        expires = box.tag_of(instance, "djb:expires")
        if expires in ("", "None", "null"):
            expires = "(unread — census prints the tag)"
        idle = box.tag_of(instance, "djb:idle")
        opts["idle"] = idle if idle.isdigit() and idle.isascii() else "?"
        market_note = "claimed from the warm pool"
        typed = "".join(f" {flag}" for flag in ("--ttl", "--idle") if flag in flags)
        if typed:
            vb_log(
                f"{PAD}NOTE: this box was CLAIMED warm, so it keeps the lifetime and idle",
                err=True,
            )
            vb_log(
                f"{PAD}threshold it was launched with; the{typed} you typed applied to nothing.",
                err=True,
            )
        if opts["az"]:
            vb_log(
                f"{PAD}NOTE: this box was CLAIMED warm, so it is in the zone it was launched in;",
                err=True,
            )
            vb_log(
                f"{PAD}the --az {opts['az']} you typed applied to nothing."
                " The 'launched' line below",
                err=True,
            )
            vb_log(f"{PAD}says where it actually is.", err=True)
    else:
        type_ = opts["type"]
        require_headroom(box)
        launched = launch_one_box(
            box,
            image,
            type_,
            opts["idle"],
            opts["ttl"],
            opts["rung"],
            "--on-demand" in flags,
            "",
            opts["az"],
        )
        instance, market_note, expires = launched.id, launched.market, launched.expires
        az, lifecycle = launched.az, launched.lifecycle
        answered = bool(launched.az)
    if not answered:
        _, placement = box.aws_quiet(
            "ec2",
            "describe-instances",
            "--instance-ids",
            instance,
            "--query",
            "Reservations[0].Instances[0].[InstanceLifecycle,Placement.AvailabilityZone]",
            "--output",
            "text",
        )
        lifecycle, tab, az = placement.split("\n")[0].partition("\t")
        az = az if tab else ""
    market = market_of_lifecycle(lifecycle)
    say(f"launched   {instance}   az {az or 'unknown'}")
    wait_for_ssm(box, instance)
    pushed = "--no-push" not in flags
    if pushed and cmd_push(box, [instance]) != 0:
        warn(
            f"!! verifier_box: box {instance} is UP (idle {opts['idle']}m, expires {expires})"
            f" — fix the cause and run: verifier_box.sh push {instance}"
            f"   or take it down: verifier_box.sh down {instance}"
        )
        warn("   The box was NOT torn down: the launch is paid for and a re-push after the")
        warn("   remedy is the fast path. Nothing reached it — the tree above is not on it.")
        raise Refused(printed=True)
    cfg = box.cfg
    say(f"instance   {instance}   {type_}   market: {market_note}   az {az}")
    say(f"market     {market}")
    say(
        f"owner      {cfg.owner}        for: {opts['rung']}   expires: {expires}"
        f" (ttl {opts['ttl']}h)   idle: {opts['idle']}m"
    )
    if not pushed:
        say("tree       (not pushed — --no-push)")
    say(
        f"session    aws ssm start-session --target {instance} --profile {cfg.profile}"
        f" --region {cfg.region}"
    )
    say(f"run        scripts/verifier_box.sh run {instance} -- <cmd>")
    return 0


COMMANDS: dict[str, Command] = {"up": cmd_up}
