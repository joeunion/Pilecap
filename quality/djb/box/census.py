"""`census`, `zones` and `pool`: the fleet read back, the zones a bank spreads across, the pool."""

from __future__ import annotations

import re
from collections.abc import Sequence

from quality.djb.box.core import (
    SPOT_QUOTA_CODE,
    Box,
    Command,
    ceiling_sources,
    clock_s,
    epoch_of_iso,
    terminate_or_by_hand,
    vb_log,
)
from quality.djb.box.transport import Refused, api_line, die, say, warn

BAKE_STALE_MINUTES = 90
_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_PRICE = re.compile(r"[0-9]+(\.[0-9]+)?")
CENSUS_QUERY = (
    "Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`djb:role`].Value|[0],"
    "Tags[?Key==`djb:owner`].Value|[0],Tags[?Key==`djb:expires`].Value|[0],LaunchTime,ImageId,"
    "InstanceLifecycle,Placement.AvailabilityZone]"
)
POOL_QUERY = (
    "sort_by(Reservations[].Instances[],&LaunchTime)[].[InstanceId,LaunchTime,ImageId,"
    "InstanceType,Tags[?Key==`djb:price`].Value|[0]]"
)


# --- the shell's arithmetic and its `read` -------------------------------------------


def tdiv(a: int, b: int) -> int:
    """`$((a / b))`: integer division truncating toward zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def hm(seconds: int) -> str:
    """`<h>h<mm>m` of a span of seconds, as the shell's `printf '%dh%02dm'` prints it."""
    rest = seconds - tdiv(seconds, 3600) * 3600
    return f"{tdiv(seconds, 3600)}h{tdiv(rest, 60):02d}m"


def tab_fields(line: str, count: int) -> list[str]:
    """`IFS=$'\\t' read -r` into `count` names: runs of tabs split, the last name takes the rest."""
    rest = line.lstrip("\t")
    fields: list[str] = []
    for _ in range(count - 1):
        head, _, tail = rest.partition("\t")
        fields.append(head)
        rest = tail.lstrip("\t")
    fields.append(rest.rstrip("\t"))
    return fields


def rows_of(raw: str, count: int) -> list[list[str]]:
    """Every line of `raw` as `count` fields, a line with no first field skipped."""
    rows = [tab_fields(line, count) for line in raw.split("\n")]
    return [row for row in rows if row[0]]


def blank(text: str) -> bool:
    """Whether `text` holds nothing but whitespace (`tr -d '[:space:]'` left nothing)."""
    return not re.sub(r"\s", "", text)


def strict_epoch(iso: str) -> int | None:
    """`epoch_of_iso`: the one shape `YYYY-MM-DDTHH:MM:SSZ`, else None."""
    return epoch_of_iso(iso) if _ISO.fullmatch(iso) else None


def age_minutes(launched: str, now: int) -> int:
    """Whole minutes since `launched` in any shape EC2 gives it; 0 when it cannot be read."""
    stamp = launched[: -len("+00:00")] + "Z" if launched.endswith("+00:00") else launched
    if "." in stamp and stamp.endswith("Z"):
        stamp = stamp.split(".", 1)[0] + "Z"
    epoch = strict_epoch(stamp)
    return 0 if epoch is None else tdiv(now - epoch, 60)


def market_of_lifecycle(lifecycle: str) -> str:
    """EC2's `InstanceLifecycle` as a market: absent is `on-demand`."""
    return "on-demand" if lifecycle in ("", "None", "null") else lifecycle


def priced(price: str) -> bool:
    """Whether a `djb:price` tag reads as a number (`[0-9]*`)."""
    return bool(re.match(r"[0-9]", price))


def pool_price_sum(prices: Sequence[str]) -> str:
    """The hourly cost of boxes from the prices they were launched with; a non-number adds 0."""
    return f"{sum(float(p) for p in prices if _PRICE.fullmatch(p)):.4f}"


def unknown_note(prices: Sequence[str]) -> str:
    """` (<n> price(s) unknown)`, or '' when every price is a number."""
    unknown = sum(1 for price in prices if not priced(price))
    return f" ({unknown} price(s) unknown)" if unknown else ""


# --- the reads -----------------------------------------------------------------------


def warm_pool_rows(box: Box) -> str:
    """This owner's warm boxes, oldest first: `<id> <launched> <ami> <type> <price>` per line."""
    cfg = box.cfg
    _, rows = box.aws_quiet(
        "ec2",
        "describe-instances",
        "--filters",
        "Name=tag:djb:role,Values=verifier",
        f"Name=tag:djb:namespace,Values={cfg.namespace}",
        f"Name=tag:djb:owner,Values={cfg.owner}",
        "Name=tag:djb:for,Values=pool",
        "Name=instance-state-name,Values=pending,running",
        "--query",
        POOL_QUERY,
        "--output",
        "text",
    )
    return rows


def vpc_of_group(box: Box) -> str:
    """The VpcId of the security group every box carries; '' when it cannot be read."""
    _, vpc = box.aws_quiet(
        "ec2",
        "describe-security-groups",
        "--filters",
        f"Name=group-name,Values={box.cfg.group_name}",
        "--query",
        "SecurityGroups[0].VpcId",
        "--output",
        "text",
    )
    vpc = vpc.split("\n")[0]
    return "" if vpc in ("", "None", "null") else vpc


def zones_of_vpc(box: Box, vpc: str) -> list[str]:
    """The zones `vpc` has a subnet in, sorted and de-duplicated."""
    _, raw = box.aws_quiet(
        "ec2",
        "describe-subnets",
        "--filters",
        f"Name=vpc-id,Values={vpc}",
        "--query",
        "Subnets[].AvailabilityZone",
        "--output",
        "text",
    )
    return sorted(set(raw.split()))


# --- census ----------------------------------------------------------------------------


def census_pool_section(box: Box) -> None:
    """The warm boxes, their ages and launch prices, under the ceiling line; a report only."""
    cfg = box.cfg
    rows = warm_pool_rows(box)
    if blank(rows):
        say(f"ceiling {cfg.max_boxes} ({cfg.max_boxes_source}) · pool: empty")
        return
    now = clock_s()
    prices: list[str] = []
    for instance, launched, _ami, _type, price in rows_of(rows, 5):
        price = price if priced(price) else "?"
        say(f"{instance} warm {age_minutes(launched, now)}m ${price}/h")
        prices.append(price)
    say(
        f"ceiling {cfg.max_boxes} ({cfg.max_boxes_source}) · pool: {len(prices)} warm"
        f" · ${pool_price_sum(prices)}/h{unknown_note(prices)}"
    )


def census_line(row: Sequence[str], now: int) -> tuple[str, bool]:
    """One box's census line and whether it is a finding (OVERDUE or STALE BAKE)."""
    instance, kind, role, owner, expires, launched, ami, lifecycle, az = row
    age = age_minutes(launched, now)
    expiry = strict_epoch(expires)
    note = ""
    if expiry is not None and now >= expiry:
        note = f"   OVERDUE {hm(now - expiry)} — the reaper did not fire; down it"
    elif role == "verifier-bake" and age >= BAKE_STALE_MINUTES:
        note = f"   STALE BAKE {age}m — a bake box that outlived its bake is a bill"
    az = "unknown" if az in ("", "None", "null") else az
    line = (
        f"{instance}   {kind}   {role}   market {market_of_lifecycle(lifecycle)}   az {az}"
        f"   ami {ami or 'unknown'}   owner {owner}   expires {expires}   age {hm(age * 60)} {note}"
    )
    return line, bool(note)


def cmd_census(box: Box, args: Sequence[str]) -> int:
    """`census`: every box in the namespace, its market, zone, image and age; 1 on a finding."""
    cfg = box.cfg
    box.require_profile()
    rc, raw = box.aws_both(
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:djb:namespace,Values={cfg.namespace}",
        "Name=instance-state-name,Values=pending,running",
        "--query",
        CENSUS_QUERY,
        "--output",
        "text",
    )
    if rc != 0:
        warn(f"!! verifier_box: could not look — {api_line(raw)}")
        box.print_owner_commands()
        raise Refused(printed=True)
    if blank(raw):
        say(f"no verifier boxes ({cfg.region}, profile {cfg.profile}, namespace {cfg.namespace})")
        census_pool_section(box)
        return 0
    now = clock_s()
    findings = 0
    for row in rows_of(raw, 9):
        line, finding = census_line(row, now)
        findings += finding
        say(line)
    census_pool_section(box)
    if findings:
        warn(f"RED: verifier_box: {findings} box(es) above need a hand. 'down <id>' takes one.")
        return 1
    return 0


# --- zones -----------------------------------------------------------------------------


def cmd_zones(box: Box, args: Sequence[str]) -> int:
    """`zones`: the zones this account can launch a box in, one per line; exit 2 when blind."""
    cfg = box.cfg
    box.require_profile()
    vpc = vpc_of_group(box)
    if not vpc:
        warn(
            f"!! verifier_box: could not look — no VPC for security group '{cfg.group_name}'"
            f" in {cfg.region}."
        )
        box.print_owner_commands()
        raise Refused(printed=True)
    zones = zones_of_vpc(box, vpc)
    if not zones:
        warn(
            f"!! verifier_box: could not look — {vpc} has no subnets this credential can see"
            f" in {cfg.region},"
        )
        warn("   so there is no zone to launch into and no spread to plan. Nothing was asked for.")
        box.print_owner_commands()
        raise Refused(printed=True)
    say("\n".join(zones))
    return 0


# --- pool ------------------------------------------------------------------------------


def pool_launch(box: Box, count: int, idle: str) -> list[str]:
    """Launch `count` warm boxes tagged for the pool; the price each was launched at."""
    # `launch` imports this module, so the launch family is imported at the call.
    from quality.djb.box.launch import launch_one_box, require_headroom, spot_price

    cfg = box.cfg
    image = box.require_image()
    require_headroom(box)
    price = spot_price(box, cfg.instance_type)
    if price in ("", "None", "null"):
        price = "?"
    tags = (
        f",{{Key=djb:for,Value=pool}},{{Key=djb:price,Value={price}}},{{Key=djb:idle,Value={idle}}}"
    )
    prices: list[str] = []
    for _ in range(count):
        launched = launch_one_box(
            box, image, cfg.instance_type, idle, cfg.ttl_hours, "pool", False, tags
        )
        prices.append(price)
        vb_log(f"pool launched {launched.id} ({launched.market}, idle {idle}m)")
    return prices


def pool_ceiling_refusal(box: Box, want: str) -> str:
    """The sentence `pool --want` above the ceiling refuses with, before any call."""
    cfg = box.cfg
    return (
        f"verifier_box: pool --want {want} is above the ceiling of {cfg.max_boxes}"
        f" ({cfg.max_boxes_source}). Nothing was\n"
        f"   asked of AWS and nothing was launched. Where the {cfg.max_boxes} came from,\n"
        "   '->' the one that bound:\n"
        f"{ceiling_sources(box)}\n"
        f"   The ceiling stands for the Spot vCPU quota ({SPOT_QUOTA_CODE}) divided by this\n"
        "   instance type; raise it only after the quota is raised —\n"
        "   `./scripts/verifier_box.sh ceiling <n>` writes the file, DJB_VERIFIER_MAX_BOXES\n"
        "   raises it for this shell alone. Nothing here asked AWS for the quota: this\n"
        "   refusal is arithmetic and stays free."
    )


def cmd_pool(box: Box, args: Sequence[str]) -> int:
    """`pool --want N [--idle M]`: launch the shortfall, trim the oldest unclaimed surplus."""
    cfg = box.cfg
    opts = {"want": "", "idle": cfg.idle_minutes}
    takes = {
        "--want": ("want", "--want takes a box count"),
        "--idle": ("idle", "--idle takes minutes"),
    }
    rest = list(args)
    while rest:
        word = rest.pop(0)
        if word not in takes:
            die(f"verifier_box: unknown argument '{word}' to pool")
        key, sentence = takes[word]
        if not rest:
            die(f"verifier_box: {sentence}")
        opts[key] = rest.pop(0)
    want, idle = opts["want"], opts["idle"]
    if not want:
        die(
            "verifier_box: pool needs --want <N>: how many warm boxes to keep."
            " 'pool --want 0'\n   is how the pool is emptied."
        )
    if not re.fullmatch(r"[0-9]+", want):
        die(f"verifier_box: --want takes a whole number of boxes, got '{want}'")
    if not re.fullmatch(r"[0-9]+", idle):
        die(f"verifier_box: --idle takes whole minutes, got '{idle}'")
    if int(want) > cfg.max_boxes:
        die(pool_ceiling_refusal(box, want))
    box.require_profile()
    box.require_plugin()
    warm_rows = rows_of(warm_pool_rows(box), 5)
    warm = len(warm_rows)
    keep_prices: list[str] = []
    launched = 0
    if int(want) > warm:
        keep_prices += pool_launch(box, int(want) - warm, idle)
        launched = len(keep_prices)
    due = max(warm - int(want), 0)
    trimmed = 0
    for instance, _launched, _ami, _type, price in warm_rows:
        if due > 0 and not (box.box_dir(instance) / "claim").is_dir():
            terminate_or_by_hand(box, instance)
            trimmed += 1
            due -= 1
            continue
        keep_prices.append(price)
    if due > 0:
        vb_log(
            f"pool {due} box(es) over the want are CLAIMED and were left alone — a claim is"
            " a verification in flight"
        )
    say(
        f"pool: {warm} warm · {launched} launched · {trimmed} trimmed"
        f" · ${pool_price_sum(keep_prices)}/h{unknown_note(keep_prices)}"
    )
    return 0


COMMANDS: dict[str, Command] = {"census": cmd_census, "zones": cmd_zones, "pool": cmd_pool}
