"""House rule 26 in this app: a service names nothing the actor could not reach.

`require` answers "may you do this kind of thing here". It is about the verb
and the role, and a branch admin passes it everywhere in their tenant. The
question nobody used to ask is the other one — **could this hat have got hold
of this row?** — and until rule 26 was adopted the answer in `apps/comms` was "whoever calls
us presumably checked", which is a property of the caller and not of the
service. Twelve rows carried that gap (`quality/reach-measurement.md` §1, and
the baseline section under it); all twelve now call
`core.authz.may_be_named` and refuse `NotFound`.

**`NotFound`, never `Forbidden`, and the refusal is composed once.** Not-there
and not-yours are one answer, or the refusal itself tells you somebody else's
customer exists. `core.exceptions.wire_refusal` builds the body for the REST
door and `refusal_message` renders the same body for the machine door, so the
two doors' refusals are byte-equal by construction rather than by two modules
agreeing — asserted below rather than assumed.

**What this file does not test**: whether a *reachable* recipient's preferences
should be writable by this verb. That is the policy layer's question and
`policies.py` answers it; `may_be_named` answers reachability and nothing else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.comms import services
from apps.comms.models import Channel, ChannelPreference, Message, MessageTemplate, Recipient
from apps.comms.tests.conftest import Branches, make_recipient, make_template
from apps.comms.tests.test_mcp import context_for, tool
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import NotFound, refusal_message, wire_refusal
from apps.core.models import Organization

pytestmark = pytest.mark.django_db

JSON = "application/json"
MESSAGES_URL = "/api/v1/messages/"
RECIPIENTS_URL = "/api/v1/recipients/"

#: The body every refusal below must equal, from the one composer. Built here
#: rather than written out, so a change to the refusal shape moves both sides of
#: every assertion at once and this file can never pin a stale wire contract.
REFUSAL = wire_refusal(NotFound())


@pytest.fixture
def theirs(branches: Branches) -> Recipient:
    """A contact belonging to seller B — a branch nobody under seller A covers."""
    return make_recipient(
        actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_b),
        email="b-contact@example.com",
    )


@pytest.fixture
def ours(branches: Branches) -> Recipient:
    """A contact in sub A1 — under seller A, so a seller-A hat covers it."""
    return make_recipient(
        actor=actor_for(user=branches.clerk, tenant=branches.tenant, org=branches.sub_a1),
        email="a1-contact@example.com",
    )


def acting(branches: Branches, user: User, org: Organization) -> Actor:
    return actor_for(user=user, tenant=branches.tenant, org=org)


# --- the checks bite over the wire, and both doors say the same thing -------
#
# **Honest about what these two prove.** Over the wire the door resolves the id
# through `get_recipient`, which already scopes — so these two were green before
# this fix adopted anything, and they stay green after. What they measure is
# the end-to-end refusal a client actually receives and the byte-equality of the
# two doors' bodies; what they do NOT measure is the service's own check, which
# never speaks when the selector got there first. The service tier below is
# where the adoption is proven with the defect demonstrated first: eleven of
# this file's fourteen tests fail on the unadopted surface, and these two are
# not among them.


def test_send_refuses_a_sibling_branchs_recipient_identically_on_both_doors(
    api: Client, branches: Branches, theirs: Recipient, receipt: MessageTemplate
) -> None:
    """`send`'s `recipient=` comes straight off the wire; this is the row.

    The clerk holds a membership at sub A1 and `message.send` says yes to any
    member — so the *policy* is satisfied and the refusal below is entirely the
    reachability question's. Both doors are driven, and their refusals are
    compared against the one composer rather than against each other's text: a
    shared typo would pass an equality between the two doors.

    Absent: a seller addresses another branch's contact by
    guessing an id, and the tenant boundary's inner wall is paper.
    """
    api.force_login(branches.clerk)
    over_http = api.post(
        MESSAGES_URL,
        data={
            "recipient_id": str(theirs.pk),
            "template": "receipt",
            "context": {"name": "Ada"},
            "channel": Channel.EMAIL.value,
        },
        content_type=JSON,
        headers={"x-org": branches.sub_a1.slug},
    )
    assert over_http.status_code == 404
    assert over_http.json() == REFUSAL

    with pytest.raises(ToolError) as refused:
        tool("send_message")(
            context_for(branches.clerk, branches.tenant, branches.sub_a1),
            recipient_id=theirs.pk,
            template="receipt",
            context={"name": "Ada"},
            channel=Channel.EMAIL.value,
        )
    assert str(refused.value) == refusal_message(REFUSAL), "one composer, two doors"

    assert not Message.objects.for_tenant(branches.tenant).filter(recipient=theirs).exists()


def test_suppress_refuses_a_sibling_branchs_recipient_identically_on_both_doors(
    api: Client, branches: Branches, theirs: Recipient
) -> None:
    """The preference half — and the actor is deliberately a privileged one.

    `channel_preference.update` is an owner's or an admin's, and the manager is
    an admin. `require` therefore says **yes** and the write would have landed
    on seller B's contact: consent taken away from somebody in a branch this hat
    holds no membership over, which is the sharpest shape the gap had.

    Absent: an admin of one branch silences another branch's customers.
    """
    api.force_login(branches.manager)
    over_http = api.post(
        f"{RECIPIENTS_URL}{theirs.pk}/suppress/",
        data={"channel": Channel.EMAIL.value},
        content_type=JSON,
        headers={"x-org": branches.seller_a.slug},
    )
    assert over_http.status_code == 404
    assert over_http.json() == REFUSAL

    with pytest.raises(ToolError) as refused:
        tool("suppress_recipient")(
            context_for(branches.manager, branches.tenant, branches.seller_a),
            recipient_id=theirs.pk,
            channel=Channel.EMAIL.value,
        )
    assert str(refused.value) == refusal_message(REFUSAL), "one composer, two doors"

    assert (
        not ChannelPreference.objects.for_tenant(branches.tenant).filter(recipient=theirs).exists()
    )


# --- service tier, for every row the doors do not drive here ----------------
#
# The doors resolve their ids through `get_recipient`, which scopes — so over
# the wire the selector refuses first and the service's own check never speaks.
# That is the arrangement working, and it is also exactly why these tests exist:
# handing the ROW to the service directly is the second caller, and the second
# caller is the whole subject of house rule 26.


def _writers() -> list[tuple[str, Callable[..., Any]]]:
    """The eight `recipient: Recipient` rows of the measured population.

    Named as callables rather than strings so a rename moves this list with the
    code, and listed exhaustively rather than discovered: a service that quietly
    left the population would silently leave this test too.
    """
    return [
        ("update_recipient", services.update_recipient),
        ("archive_recipient", services.archive_recipient),
        ("grant_consent", services.grant_consent),
        ("revoke_consent", services.revoke_consent),
        ("set_quiet_hours", services.set_quiet_hours),
        ("suppress_recipient", services.suppress_recipient),
        ("unsuppress_recipient", services.unsuppress_recipient),
        ("send", services.send),
    ]


@pytest.mark.parametrize("name,writer", _writers(), ids=[n for n, _ in _writers()])
def test_every_recipient_writer_refuses_a_row_from_a_branch_it_cannot_reach(
    branches: Branches,
    theirs: Recipient,
    receipt: MessageTemplate,
    name: str,
    writer: Callable[..., Any],
) -> None:
    """Service tier. The row is handed over directly — no selector in front.

    The manager is an admin acting as seller A, so every policy these verbs
    consult says yes. The only thing standing between the call and a write into
    seller B is `may_be_named`.

    Absent: seven of the eight rows are protected by their one caller's habits,
    and the eighth caller inherits nothing.
    """
    actor = acting(branches, branches.manager, branches.seller_a)
    if name == "send":
        with pytest.raises(NotFound):
            writer(
                recipient=theirs,
                tenant=branches.tenant,
                actor=actor,
                template="receipt",
                context={"name": "Ada"},
                channel=Channel.EMAIL.value,
            )
        return
    with pytest.raises(NotFound):
        writer(tenant=branches.tenant, actor=actor, recipient=theirs)


# --- R3-3: the four message writers, judged ---------------------------------------


def test_every_message_writer_refuses_an_anchor_from_a_branch_it_cannot_reach(
    branches: Branches, theirs: Recipient, receipt: MessageTemplate
) -> None:
    """R3-3. The four `message: Message` rows took the check, not a `# reach:`.

    Each of them is reached from a delivery activity that resolved the row
    through `get_message(... org=)` — a `.visible_to(hat)` read — so the check
    cannot refuse a legitimate call, and every comms test passes unmodified.
    What it does refuse is the caller that resolved the row some other way,
    which is the only caller house rule 26 was ever about.

    The `# reach:` sentence the plan reserved for these was for the case where
    the platform acts for itself and holds no hat. That case does not arise in
    this app: `send()` refuses `actor.org is None` before a run is ever started,
    so every delivery run carries a hat and the check was the stronger of two
    available answers.

    Absent: three or four standing valves in the rule's count, each excusing a
    check that would have cost nothing.
    """
    theirs_message = services.send(
        recipient=theirs,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL.value,
        tenant=branches.tenant,
        actor=acting(branches, branches.owner, branches.seller_b),
    )
    make_template(actor=acting(branches, branches.owner, branches.hq), name="chaser")
    outsider = acting(branches, branches.manager, branches.seller_a)

    with pytest.raises(NotFound):
        services.mark_message_sending(
            tenant=branches.tenant, actor=outsider, message=theirs_message
        )
    with pytest.raises(NotFound):
        services.record_message_sent(
            tenant=branches.tenant,
            actor=outsider,
            message=theirs_message,
            provider="locmem",
            provider_message_id="<x@y>",
        )
    with pytest.raises(NotFound):
        services.record_message_failed(
            tenant=branches.tenant, actor=outsider, message=theirs_message, error="no"
        )
    with pytest.raises(NotFound):
        services.send_step(
            tenant=branches.tenant,
            actor=outsider,
            message=theirs_message,
            step=2,
            channel=Channel.EMAIL.value,
            template="chaser",
        )

    assert Message.objects.for_tenant(branches.tenant).filter(recipient=theirs).count() == 1, (
        "four refusals, and not one of them wrote a row"
    )


# --- R3-5: down-only is preserved -------------------------------------------------


def test_a_parent_hat_still_names_a_descendants_recipient(
    branches: Branches, ours: Recipient, receipt: MessageTemplate
) -> None:
    """R3-5. **The check must not land inverted.**

    Roles inherit downwards and so does reach: seller A's admin covers sub A1,
    and the root covers everything. Both directions are asserted, against the
    same kind of row the sibling tests refuse — so a check that simply refused
    everything would pass those and fail here.

    Absent: the fix closes the sibling hole by breaking the hierarchy, which is
    the feature the hole was a side effect of.
    """
    from_the_parent = services.suppress_recipient(
        tenant=branches.tenant,
        actor=acting(branches, branches.manager, branches.seller_a),
        recipient=ours,
        channel=Channel.EMAIL,
    )
    assert from_the_parent.suppressed_at is not None

    from_the_root = services.unsuppress_recipient(
        tenant=branches.tenant,
        actor=acting(branches, branches.owner, branches.hq),
        recipient=ours,
        channel=Channel.EMAIL,
    )
    assert from_the_root.suppressed_at is None

    at_home = services.send(
        recipient=ours,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL.value,
        tenant=branches.tenant,
        actor=acting(branches, branches.clerk, branches.sub_a1),
    )
    assert at_home.status == Message.Status.QUEUED


def test_an_unresolved_hat_names_nothing(branches: Branches, ours: Recipient) -> None:
    """Fails closed, like every other unresolved scope in the product.

    `for_tenant(None)` reads nothing and `visible_to(None)` reads nothing; an
    actor with no hat must name nothing, rather than naming everything because
    there was nobody to compare it against.
    """
    hatless = actor_for(user=branches.owner, tenant=branches.tenant, org=None)
    with pytest.raises(NotFound):
        services.suppress_recipient(
            tenant=branches.tenant, actor=hatless, recipient=ours, channel=Channel.EMAIL
        )


def test_the_refusal_is_reachability_and_not_the_role(
    branches: Branches, theirs: Recipient, ours: Recipient
) -> None:
    """The control that makes every `NotFound` above mean what it claims.

    One actor, two rows, two answers. If the manager were simply unauthorised
    for this verb the sibling tests would pass for the wrong reason and this
    would fail — the same call on a row inside their own subtree has to work.
    """
    manager = acting(branches, branches.manager, branches.seller_a)
    assert (
        services.grant_consent(
            tenant=branches.tenant, actor=manager, recipient=ours, channel=Channel.EMAIL
        ).marketing_consented_at
        is not None
    )
    with pytest.raises(NotFound):
        services.grant_consent(
            tenant=branches.tenant, actor=manager, recipient=theirs, channel=Channel.EMAIL
        )
