"""The bake's image side: the base image's name and state, the teardown, the prune."""

from __future__ import annotations

from collections.abc import Callable

from quality.djb.box.core import Box, terminate_or_by_hand, vb_log
from quality.djb.box.transport import say, warn

KEEP_NEWEST = 2
PRUNE_QUERY = (
    "reverse(sort_by(Images,&CreationDate))[].[ImageId,BlockDeviceMappings[].Ebs.SnapshotId,"
    "CreationDate]"
)


def image_name_and_state(box: Box, image: str) -> str:
    """`<Name>\\t<State>` of `image` in one call; '' when the credential cannot see it."""
    return box.aws_text(
        "ec2",
        "describe-images",
        "--image-ids",
        image,
        "--query",
        "Images[0].[Name,State]",
        "--output",
        "text",
    )


def print_untagged_capture(box: Box, image: str) -> None:
    """The finding an untagged capture is handed over with: launch it by hand, fix the policy."""
    cfg = box.cfg
    for line in (
        f"!! verifier_box: {image} was captured WITHOUT ITS TAGS.",
        "   The image is good. What is missing is the labelling, and two things read it:",
        "   'up' finds the newest image by djb:role + djb:namespace, and '--prune' decides",
        "   what is ours. Until the tags are there, THIS IMAGE IS INVISIBLE to both.",
        "",
        "   NOW — launch from it by hand:",
        f"     scripts/verifier_box.sh up --for <rung> --image-id {image}",
        "",
        "   THE FIX, and it is the owner's: the ops policy must grant ec2:CreateTags on the",
        "   ACCOUNT-LESS image and snapshot ARNs — arn:aws:ec2:<region>::image/* and",
        "   ::snapshot/* — beside the account-scoped one. deploy/iam/verifier-ops-policy.json",
        "   carries them; the ACCOUNT may not. An existing policy keeps the document it was",
        "   created with, so re-running the bootstrap REPORTS it and does not update it:",
        "",
        f"     DJB_DEPLOY_NAMESPACE={cfg.namespace} DJB_VERIFIER_ACCOUNT=<12-digit account>"
        f" DJB_VERIFIER_REGION={cfg.region} \\",
        "       ./deploy/iam/verifier_bootstrap.sh --confirm",
        "",
        "   and then the command IT prints — an 'iam create-policy-version --set-as-default'",
        "   over the document it renders. Both are the owner's to run.",
    ):
        warn(line)


def bake_teardown(box: Box, rc: int, bake_box: str, summary: Callable[[], None]) -> int:
    """The bake's way out: the phase summary, then the box down; the original failure's status."""
    summary()
    if not bake_box:
        return rc
    warn(f"!! verifier_box: the bake stopped (exit {rc}) with {bake_box} still up; taking it")
    warn("   down so it cannot become a stale bill — nothing on a bake box outlives its bake.")
    if terminate_or_by_hand(box, bake_box) != 0 and rc == 0:
        return 2
    return rc


def bake_prune(box: Box) -> int:
    """`bake --prune`: keep the newest two images, deregister the rest with every snapshot."""
    box.require_profile()
    _, rows = box.aws_quiet(
        "ec2",
        "describe-images",
        "--owners",
        "self",
        "--filters",
        "Name=tag:djb:role,Values=verifier-image",
        f"Name=tag:djb:namespace,Values={box.cfg.namespace}",
        "--query",
        PRUNE_QUERY,
        "--output",
        "text",
    )
    if not rows.strip():
        vb_log("no verifier images to prune")
        return 0
    n = 0
    for line in rows.split("\n"):
        fields = [field for field in line.split("\t") if field]
        if not fields:
            continue
        image = fields[0]
        snaps = [snap for snap in fields[1:-1] if snap not in ("None", "null")]
        n += 1
        if n <= KEEP_NEWEST:
            vb_log(f"keeping {image}")
            continue
        rc = box.aws_status("ec2", "deregister-image", "--image-id", image)
        if rc:
            return rc
        for snap in snaps:
            rc = box.aws_status("ec2", "delete-snapshot", "--snapshot-id", snap)
            if rc:
                return rc
        say(f"pruned {image} (snapshot(s) {' '.join(snaps) or 'none'})")
    return 0
