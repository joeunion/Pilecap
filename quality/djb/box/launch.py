"""One box launched: the zone, the per-box key, the user-data, Spot then the market rule."""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from quality.djb.box.census import vpc_of_group, zones_of_vpc
from quality.djb.box.core import (
    ONLINE_POLL_SECONDS,
    SPOT_QUOTA_CODE,
    Box,
    ceiling_sources,
    clock_s,
    drop_tree,
    iso_at,
    pause,
)
from quality.djb.box.transport import (
    PIPE,
    ROOT,
    Refused,
    Transport,
    die,
    spawn,
    warn,
)

USER_DATA = ROOT / "deploy" / "verifier" / "user-data.yaml.in"
ONLINE_WAIT_SECONDS = 300
SPOT_MARKET = (
    "MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}"
)
LAUNCH_QUERY = (
    "Instances[0].[InstanceId,SpotInstanceRequestId,Placement.AvailabilityZone,InstanceLifecycle]"
)
_SPOT_CODE = re.compile(
    r"\((AuthFailure\.ServiceLinkedRoleCreationNotPermitted|InsufficientInstanceCapacity"
    r"|SpotMaxPriceTooLow|MaxSpotInstanceCountExceeded|UnauthorizedOperation|ExpiredToken"
    r"|AuthFailure|InvalidClientTokenId|Unsupported)\)"
)
_USD = re.compile(r'"USD"[^0-9]*[0-9]+\.[0-9]+')
ZONE_CODES = ("InsufficientInstanceCapacity", "Unsupported")
MARKET_CODES = (
    "InsufficientInstanceCapacity",
    "SpotMaxPriceTooLow",
    "MaxSpotInstanceCountExceeded",
)
CREDENTIAL_CODES = ("UnauthorizedOperation", "ExpiredToken", "AuthFailure", "InvalidClientTokenId")
SLR_CODE = "AuthFailure.ServiceLinkedRoleCreationNotPermitted"


def _absent(value: str) -> str:
    return "" if value in ("None", "null") else value


@dataclass
class Attempt:
    """One `run-instances`: its status and the four fields its projection answered."""

    rc: int = 0
    id: str = ""
    sir: str = ""
    az: str = ""
    lifecycle: str = ""

    @property
    def failed(self) -> bool:
        """A non-zero status, an empty id, or the CLI's `None` for a query that matched nothing."""
        return self.rc != 0 or self.id in ("", "None")


@dataclass
class Launched:
    """What `launch_one_box` hands back: the id, the market sentence, the expiry, the placement."""

    id: str
    market: str
    expires: str
    spot_request: str
    az: str
    lifecycle: str


def run_instances_argv(
    box: Box,
    image: str,
    type_: str,
    group: str,
    user_data: str,
    role: str,
    expires: str,
    name: str,
    market: str,
    extra_tags: str = "",
    subnet: str = "",
) -> list[str]:
    """The one `run-instances` argv: the image, the walls, the user-data, the tags, the query."""
    cfg = box.cfg
    ns = cfg.namespace
    subnet_args = ["--subnet-id", subnet] if subnet else []
    market_args = ["--instance-market-options", SPOT_MARKET] if market else []
    tags = (
        f"ResourceType=instance,Tags=[{{Key=djb:role,Value={role}}},{{Key=djb:owner,Value={cfg.owner}}},"
        f"{{Key=djb:expires,Value={expires}}},{{Key=djb:namespace,Value={ns}}},{{Key=Name,Value={name}}},"
        f"{{Key=Project,Value={ns}}}{extra_tags}]"
    )
    return box.aws(
        "ec2",
        "run-instances",
        "--image-id",
        image,
        "--instance-type",
        type_,
        "--security-group-ids",
        group,
        *subnet_args,
        "--iam-instance-profile",
        f"Name={ns}-verifier-box",
        "--instance-initiated-shutdown-behavior",
        "terminate",
        "--metadata-options",
        "HttpTokens=required,HttpEndpoint=enabled",
        "--block-device-mappings",
        "DeviceName=/dev/xvda,Ebs={VolumeSize=60,VolumeType=gp3,Encrypted=true}",
        "--user-data",
        user_data,
        *market_args,
        "--tag-specifications",
        tags,
        "--query",
        LAUNCH_QUERY,
        "--output",
        "text",
    )


def run_instances_common(
    box: Box,
    image: str,
    type_: str,
    group: str,
    user_data: str,
    role: str,
    expires: str,
    name: str,
    market: str,
    extra_tags: str = "",
    subnet: str = "",
    *,
    errors: IO[str] | None = None,
) -> tuple[int, str]:
    """Launch once: the status and the projection's stdout; stderr to `errors`, else through."""
    argv = run_instances_argv(
        box, image, type_, group, user_data, role, expires, name, market, extra_tags, subnet
    )
    done = spawn(argv, env=box.cfg.env, stdout=PIPE, stderr=errors)
    return done.returncode, done.stdout.rstrip("\n")


def launch_attempt(
    box: Box,
    image: str,
    type_: str,
    group: str,
    user_data: str,
    expires: str,
    name: str,
    market: str,
    extra_tags: str,
    subnet: str,
    errfile: Path | None,
) -> Attempt:
    """One attempt at a verifier launch; never decides, its failure is the caller's input."""
    args = (box, image, type_, group, user_data, "verifier", expires, name, market, extra_tags)
    if errfile is None:
        rc, out = run_instances_common(*args, subnet)
    else:
        with errfile.open("w") as errors:
            rc, out = run_instances_common(*args, subnet, errors=errors)
    fields = out.split("\n")[0].split("\t")
    fields += [""] * (4 - len(fields))
    return Attempt(rc, fields[0], _absent(fields[1]), _absent(fields[2]), _absent(fields[3]))


def on_demand_price(box: Box, type_: str) -> str:
    """The on-demand hourly USD of `type_` from the Price List API, or `?` with no region to ask."""
    cfg = box.cfg
    pricing = cfg.env.get("DJB_VERIFIER_PRICING_REGION", "")
    if not pricing:
        return "?"
    asker = Transport(dataclasses.replace(cfg, region=pricing))
    _, blob = asker.aws_quiet(
        "pricing",
        "get-products",
        "--service-code",
        "AmazonEC2",
        "--filters",
        f"Type=TERM_MATCH,Field=instanceType,Value={type_}",
        f"Type=TERM_MATCH,Field=regionCode,Value={cfg.region}",
        "Type=TERM_MATCH,Field=operatingSystem,Value=Linux",
        "Type=TERM_MATCH,Field=tenancy,Value=Shared",
        "Type=TERM_MATCH,Field=preInstalledSw,Value=NA",
        "Type=TERM_MATCH,Field=capacitystatus,Value=Used",
        "--max-items",
        "1",
        "--query",
        "PriceList[0]",
        "--output",
        "text",
    )
    found = _USD.search(blob)
    num = re.sub(r"[^0-9.]", "", found.group(0)) if found else ""
    return "?" if not num or num.startswith(".") else num


def spot_error_code(errfile: Path) -> str:
    """The first error code a Spot attempt's stderr names, or ''."""
    try:
        text = errfile.read_text(errors="replace")
    except OSError:
        return ""
    found = _SPOT_CODE.search(text)
    return found.group(1) if found else ""


def spot_price(box: Box, type_: str) -> str:
    """The last Spot price of `type_`, or `?`."""
    _, out = box.aws_quiet(
        "ec2",
        "describe-spot-price-history",
        "--instance-types",
        type_,
        "--product-descriptions",
        "Linux/UNIX",
        "--max-items",
        "1",
        "--query",
        "SpotPriceHistory[0].SpotPrice",
        "--output",
        "text",
    )
    out = out.split("\n")[0]
    return "?" if out in ("", "None", "null") else out


def render_user_data(
    template: Path, pubkey: str, owner: str, expires: str, idle: str, image: str = "unknown"
) -> str:
    """The launch seam with its five slots filled."""
    if not os.access(template, os.R_OK):
        die(f"verifier_box: cannot read the launch seam {template}")
    text = template.read_text()
    for slot, value in (
        ("VERIFIER_PUBKEY", pubkey),
        ("VERIFIER_OWNER", owner),
        ("VERIFIER_EXPIRES", expires),
        ("VERIFIER_IDLE_MINUTES", idle),
        ("VERIFIER_IMAGE_ID", image),
    ):
        text = text.replace("${" + slot + "}", value)
    return text.rstrip("\n")


def wait_for_ssm(box: Box, instance: str, *, baking: bool = False) -> None:
    """Poll until `instance` is Online with Session Manager; refuse at the ceiling."""
    waited = 0
    started = clock_s()
    while waited < ONLINE_WAIT_SECONDS:
        _, status = box.aws_quiet(
            "ssm",
            "describe-instance-information",
            "--filters",
            f"Key=InstanceIds,Values={instance}",
            "--query",
            "InstanceInformationList[0].PingStatus",
            "--output",
            "text",
        )
        if status == "Online":
            return
        pause(ONLINE_POLL_SECONDS)
        waited = clock_s() - started
    hint = (
        "The bake's teardown takes it down on the way out; nothing is left for you to do."
        if baking
        else "It is RUNNING and it is BILLING: take it down with\n\n"
        f"     scripts/verifier_box.sh down {instance}"
    )
    die(
        f"verifier_box: {instance} did not register with Session Manager inside {waited}s"
        f" (ceiling {ONLINE_WAIT_SECONDS}s).\n   {hint}"
    )


def subnet_in_zone(box: Box, vpc: str, az: str) -> str:
    """The first subnet of `vpc` in `az`, or ''."""
    _, out = box.aws_quiet(
        "ec2",
        "describe-subnets",
        "--filters",
        f"Name=vpc-id,Values={vpc}",
        f"Name=availability-zone,Values={az}",
        "--query",
        "Subnets[0].SubnetId",
        "--output",
        "text",
    )
    return _absent(out.split("\n")[0])


def next_zone_after(box: Box, vpc: str, az: str) -> str:
    """The zone after `az` in `vpc`'s ring, wrapping; '' with one zone or `az` not in it."""
    zones = [zone for zone in zones_of_vpc(box, vpc) if zone]
    if az not in zones or len(zones) < 2:
        return ""
    return zones[(zones.index(az) + 1) % len(zones)]


def require_headroom(box: Box) -> None:
    """Refuse a launch at or over the ceiling, naming the boxes and where the ceiling came from."""
    cfg = box.cfg
    _, running = box.aws_quiet(
        "ec2",
        "describe-instances",
        "--filters",
        "Name=tag:djb:role,Values=verifier",
        f"Name=tag:djb:namespace,Values={cfg.namespace}",
        "Name=instance-state-name,Values=pending,running",
        "--query",
        "Reservations[].Instances[].InstanceId",
        "--output",
        "text",
    )
    count = sum(1 for line in running.replace("\t", "\n").split("\n") if line) if running else 0
    if count < cfg.max_boxes:
        return
    rc, quota = box.aws_quiet(
        "service-quotas",
        "get-service-quota",
        "--service-code",
        "ec2",
        "--quota-code",
        SPOT_QUOTA_CODE,
        "--query",
        "Quota.Value",
        "--output",
        "text",
    )
    if rc:
        quota = f"{quota}\n?" if quota else "?"
    die(
        f"verifier_box: {count} verifier box(es) already running and the ceiling is"
        f" {cfg.max_boxes} ({cfg.max_boxes_source}):\n"
        f"     {running.replace(chr(9), ' ')}\n"
        f"   Nothing was launched. Where the {cfg.max_boxes} came from, '->' the one that bound:\n"
        f"{ceiling_sources(box)}\n"
        f"   The ceiling stands for the Spot vCPU quota ({SPOT_QUOTA_CODE} = {quota})\n"
        f"   divided by this instance type ({cfg.instance_type}); raise it only after the quota\n"
        "   is raised — `./scripts/verifier_box.sh ceiling <n>` writes the file for every\n"
        "   session on this machine, DJB_VERIFIER_MAX_BOXES raises it for this shell alone\n"
        "   — or 'down' one of the boxes above."
    )


def security_group(box: Box) -> str:
    """The group every box joins; a refusal printing the owner's commands when it is absent."""
    cfg = box.cfg
    _, group = box.aws_quiet(
        "ec2",
        "describe-security-groups",
        "--filters",
        f"Name=group-name,Values={cfg.group_name}",
        "--query",
        "SecurityGroups[0].GroupId",
        "--output",
        "text",
    )
    if group in ("", "None", "null"):
        warn(f"!! verifier_box: no security group '{cfg.group_name}' in {cfg.region}.")
        box.print_owner_commands()
        raise Refused(printed=True)
    return group


def _keypair(box: Box, pending: Path) -> Path:
    """A fresh ed25519 pair under `pending`; the private half's path."""
    drop_tree(pending)
    pending.mkdir(parents=True)
    pending.chmod(0o700)
    keyfile = pending / "id_ed25519"
    argv = ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"verifier@{box.cfg.owner}"]
    if spawn([*argv, "-f", str(keyfile)], env=box.cfg.env).returncode:
        raise Refused(printed=True)
    keyfile.chmod(0o600)
    return keyfile


def _market_refused(box: Box, pending: Path, type_: str, code: str) -> str:
    """Spot said no for the market: the price, the shard wall, the valve; the market sentence."""
    cfg = box.cfg
    od = on_demand_price(box, type_)
    warn(f"!! verifier_box: Spot was refused ({code}) for {type_} in {cfg.region}.")
    if od == "?":
        warn("   on-demand price: UNKNOWN — DJB_VERIFIER_PRICING_REGION is unset, so the")
        warn("   Price List API was not asked. It is published in a small number of")
        warn("   regions and this wrapper guesses none of them.")
    else:
        warn(
            f"   on-demand would cost ${od}/h for {type_}; Spot's last price was"
            f" ${spot_price(box, type_)}/h."
        )
    shard = cfg.env.get("DJB_VERIFIER_BANK_SHARD", "")
    allowed = cfg.env.get("DJB_VERIFIER_ON_DEMAND_OK", "")
    if shard and not allowed:
        drop_tree(pending)
        warn("   THIS IS A BANK SHARD, so nothing was launched: could not launch.")
        warn("   A bank's shards fall back together or not at all, and an unasked")
        warn("   on-demand bank is the failure this refusal exists to prevent. The")
        warn("   bank will refuse for the missing box, which is the outcome you want.")
        warn("   To buy on-demand deliberately, type the reason and run the bank again:")
        warn('     DJB_VERIFIER_ON_DEMAND_OK="<why this wave is worth on-demand money>"')
        raise Refused(printed=True)
    if allowed:
        warn(f"   on-demand ALLOWED by DJB_VERIFIER_ON_DEMAND_OK: {allowed}")
        return f"on-demand (spot refused: {code}; allowed: {allowed})"
    return f"on-demand (spot refused: {code})"


def _refuse_prerequisite(box: Box, pending: Path, code: str) -> None:
    """The Spot service-linked role is missing: the account's one-time fix, never on-demand."""
    region = box.cfg.region
    drop_tree(pending)
    for line in (
        "!! verifier_box: Spot was refused for an ACCOUNT PREREQUISITE, not for capacity and",
        f"   not for your credential: {code}.",
        "   EC2's Spot service-linked role does not exist in this account. The first Spot",
        "   request creates it as a side effect IF the caller may, and this one may not —",
        "   the verifier ops policy grants no iam write at all, by design.",
        "   Nothing was launched. Two ways on, in order of preference:",
        "     1. create the role ONCE, under the ADMIN profile:",
        f"          aws --region {region} --profile <admin> \\",
        "            iam create-service-linked-role --aws-service-name spot.amazonaws.com",
        "        `./deploy/iam/verifier_bootstrap.sh` checks this as its step 0 and prints",
        "        that same command when it is needed.",
        "     2. this one launch on-demand: verifier_box.sh up --on-demand --for <rung>",
    ):
        warn(line)
    raise Refused(printed=True)


def launch_one_box(
    box: Box,
    image: str,
    type_: str,
    idle: str,
    ttl: str,
    rung: str,
    on_demand: bool,
    extra_tags: str = "",
    want_az: str = "",
) -> Launched:
    """Launch one verifier box: Spot, the next zone once, then the market rule; its record kept."""
    cfg = box.cfg
    group = security_group(box)
    vpc = subnet = ""
    az = want_az
    if az:
        vpc = vpc_of_group(box)
        if not vpc:
            die(
                f"verifier_box: could not read the VPC of security group '{cfg.group_name}' in"
                f" {cfg.region};\n"
                f"   --az {az} cannot be honoured and nothing was launched. 'zones' asks the same\n"
                "   question on its own."
            )
        subnet = subnet_in_zone(box, vpc, az)
        if not subnet:
            zones = "\n".join(f"     {zone}" for zone in zones_of_vpc(box, vpc))
            die(
                f"verifier_box: no subnet of {vpc} is in availability zone '{az}', so there is"
                " no way to\n"
                "   ask for that zone and nothing was launched. The zones this VPC can reach:\n"
                f"{zones}"
            )
    pending = cfg.home / f".pending-{os.getpid()}"
    keyfile = _keypair(box, pending)
    pubkey = Path(f"{keyfile}.pub").read_text().rstrip("\n")
    expires = iso_at(clock_s() + int(ttl) * 3600)
    user_data = render_user_data(USER_DATA, pubkey, cfg.owner, expires, idle, image)
    name = f"{cfg.namespace}-verifier-{cfg.owner}-{rung}"
    spot_err = pending / "spot.err"

    def attempt(market: str, errfile: Path | None) -> Attempt:
        return launch_attempt(
            box, image, type_, group, user_data, expires, name, market, extra_tags, subnet, errfile
        )

    if on_demand:
        market_note = "on-demand (asked for)"
        launch = attempt("", None)
    else:
        launch = attempt("spot", spot_err)
        if launch.failed and spot_error_code(spot_err) in ZONE_CODES and az:
            code = spot_error_code(spot_err)
            next_az = next_zone_after(box, vpc, az)
            next_subnet = subnet_in_zone(box, vpc, next_az) if next_az else ""
            if next_az and next_subnet:
                warn(f"az {az} refused ({code}); trying {next_az}")
                az, subnet = next_az, next_subnet
                launch = attempt("spot", spot_err)
        if launch.failed:
            code = spot_error_code(spot_err)
            if code in MARKET_CODES:
                market_note = _market_refused(box, pending, type_, code)
                launch = attempt("", None)
            elif code == SLR_CODE:
                _refuse_prerequisite(box, pending, code)
            elif code in CREDENTIAL_CODES:
                drop_tree(pending)
                warn(f"!! verifier_box: the credential was refused ({code}). Nothing was launched.")
                box.print_owner_commands()
                raise Refused(printed=True)
            else:
                try:
                    detail = "\n".join(spot_err.read_text(errors="replace").split("\n")[:3])
                except OSError:
                    detail = ""
                drop_tree(pending)
                die(
                    f"verifier_box: run-instances failed ({code or 'no error code'}). Nothing was"
                    f" launched.\n   {detail.rstrip(chr(10))}"
                )
        else:
            market_note = f"spot ({spot_price(box, type_)}/h at launch)"
    if launch.id in ("", "None"):
        drop_tree(pending)
        die("verifier_box: run-instances returned no instance id")
    home = box.box_dir(launch.id)
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    key = box.box_key(launch.id)
    keyfile.replace(key)
    Path(f"{keyfile}.pub").replace(Path(f"{key}.pub"))
    key.chmod(0o600)
    (home / "rung").write_text(f"{rung}\n")
    if launch.sir:
        (home / "spot-request").write_text(f"{launch.sir}\n")
    drop_tree(pending)
    return Launched(launch.id, market_note, expires, launch.sir, launch.az, launch.lifecycle)
