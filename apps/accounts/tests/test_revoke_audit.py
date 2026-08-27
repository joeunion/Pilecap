"""A credential's death is audited beside its birth (ADR core-22).

`issue_token` has written an `AuditEntry` since ADR core-8's flip. `revoke_token`
wrote none, because `@service` reads the audited population off the signature
(`core.service._declares_tenant`) and revoke declared no `tenant` — so the one
compliance-shaped trail in this product recorded who was *given* the ability to
act as somebody, and never who *ended* it. That gap was found; the lead ruled it
closed the way the mint already works, rather than by inventing a population.

Three properties, and they are not the same property:

1. **The row exists, at both doors**, carrying the door it came through and the
   tenant the *token* is pinned to.
2. **The pin decides the population.** An unpinned token's death joins the
   platform (null-tenant) population — the same one its birth joined. The test
   asserts the pair, not each half, because "both rows are in the platform
   population" is the claim and either half alone is compatible with a split.
3. **The parameter cannot lie.** `tenant` is required (never defaulted — ADR
   core-8's own `sync_workforce` lesson is that a caller relying on a default
   is how a service goes unaudited), and a `tenant` that disagrees with
   `token.tenant` is refused rather than filed.

And the property that rides along: a second revoke is an idempotent no-op — the recorded
moment is the audit fact being protected, so nothing may move it, and nothing
may fire a socket kick on the strength of a write that did not happen.

**The fourth property: the rows record WHO.** ADR
core-22's actor semantics are per door and there are three kinds, closed — a
session mint or revocation is `human` with `actor_user` set, a bearer call is
`agent` with `actor_user` AND `actor_token` set, and the shell door is
`system` with `actor_user` None **honestly** (absence iv: the box's own access
audit owns who held the shell, and this table does not duplicate an authority
it cannot verify). `actor` is required and never defaulted on both token
services for the same reason `tenant` is: the decorator reads the population
off the declaration and writes the row from the *call*, so a defaulted
parameter is a service that looks attributed and files every row under nobody.
"""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID

import pytest

from apps.accounts.models import ApiToken, User
from apps.accounts.services import issue_token, revoke_token
from apps.core import bridge
from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.core.exceptions import Invalid
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

#: What `@service` names this write in the trail: `<app label>.<function>`.
REVOKE = "accounts.revoke_token"
MINT = "accounts.issue_token"


def _deaths(token: ApiToken) -> list[AuditEntry]:
    """The revoke rows about this one token, whichever population they are in.

    Read off the bare manager on purpose: `for_tenant` fails closed and can
    never see a platform row, and the question here is *which* population the
    row landed in — a read that could not see one of the answers would make the
    null-tenant test pass for the wrong reason.

    `object_id` works here because `revoke_token` returns the row it wrote and
    `@service._object_of` takes the object from the return value. Since AUDIT-2
    it works for the mint too (`_births`, below): the asymmetry MICRO-1 found
    was a gap in the seam, not a fact about tuples.
    """
    return list(AuditEntry.objects.filter(action=REVOKE, object_id=token.pk).order_by("created_at"))


def _births(token: ApiToken) -> list[AuditEntry]:
    """The mint rows for this one token — an ID JOIN since AUDIT-2.

    **This helper used to match on the NAME**, because a mint row carried no
    `object_id`: `@service` takes the audited object from what the service
    returned (`_object_of`), and `issue_token` returns `(token, plaintext)` —
    the plaintext exists exactly once and cannot be re-derived, so the return
    shape is load-bearing and was not reshaped. A tuple was not a
    `models.Model`, so the row landed with `object_type=""` and `object_id=None`
    and its only link to the credential it created was a string a person chose.

    ADR core-22's ruling closed that at the generic seam instead: `_object_of`
    learns tuples and the FIRST `models.Model` element wins. So the birth side
    of the pairing is now exactly as strong as the death side, and this helper
    says so by joining on the id rather than on the name.
    """
    return list(AuditEntry.objects.filter(action=MINT, object_id=token.pk).order_by("created_at"))


def _failed_revokes() -> list[AuditEntry]:
    """The failed-call rows the decorator writes when a revoke is refused.

    Matched on action and outcome rather than on `object_id`, because a failed
    call returns nothing for `_object_of` to read — that column is `None` on
    every one of them and always will be, since the service raised instead of
    returning.

    What the row DOES name since AUDIT-2 is the credential, through the
    redacted `input`: `redact` renders a `models.Model` argument as
    `<app_label>.<Model>:<pk>` whatever its parameter is called, because a
    primary key is not a secret and a whole row is never carried along. Before
    that, `token` was neither `_id`-suffixed nor in this app's `LOG_KEYS`, so a
    refused revocation was in the trail as an event and not as an event *about
    a particular credential*.
    """
    return list(
        AuditEntry.objects.filter(action=REVOKE, outcome=AuditEntry.Outcome.ERROR).order_by(
            "created_at"
        )
    )


# --- the signature is the contract -------------------------------------------


def test_revoke_declares_a_required_tenant() -> None:
    """`tenant` is keyword-only, present, and has NO default.

    The absence of a default is the criterion, not decoration. `@service` reads
    the audited population off the declaration but writes the row from the
    *call* (`kwargs.get("tenant")`), so a defaulted parameter is a service that
    looks audited and files every row under `None`. That is exactly how
    `sync_workforce_identity_config` went unaudited (ADR core-8), and it is the
    one shape a signature test can refuse before anything runs.
    """
    parameters = inspect.signature(revoke_token).parameters

    assert "tenant" in parameters, "revoke_token must declare tenant to be audited at all"
    tenant = parameters["tenant"]
    assert tenant.kind is inspect.Parameter.KEYWORD_ONLY
    assert tenant.default is inspect.Parameter.empty, "a defaulted tenant is an unaudited service"
    assert parameters["token"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("fn", [issue_token, revoke_token], ids=["mint", "revoke"])
def test_both_token_doors_declare_a_required_actor(fn: Any) -> None:
    """Mechanically: `actor` is keyword-only, present, and has NO default.

    The same shape the `tenant` test above uses, and for the same reason. ADR
    core-22 reads AU-3's "identity of associated individuals" onto
    `actor_user`/`actor_token`/`actor_kind`, and `write_audit` takes all three
    from the `actor` the service was given **and from nowhere else** — the
    bound context's `user_id` is ambient observability data and an audit row is
    a claim. A service with no `actor` therefore cannot record a person even
    when a person is standing at the door; a service with a DEFAULTED `actor`
    is worse, because it looks attributed and files every row under nobody the
    moment a caller leaves it out. That is `sync_workforce_identity_config`'s
    lesson (ADR core-8) applied to the other half of the row.
    """
    parameters = inspect.signature(fn).parameters

    assert "actor" in parameters, f"{fn.__name__} records no person (ADR core-22)"
    actor = parameters["actor"]
    assert actor.kind is inspect.Parameter.KEYWORD_ONLY
    assert actor.default is inspect.Parameter.empty, "a defaulted actor files rows under nobody"


# --- the row exists, at both doors -------------------------------------------


def test_a_shell_revoke_writes_an_audit_row(tenant: Tenant, owner: User) -> None:
    """The shell door's row. Absent-case: on the pre-ruling tree this is zero."""
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="shell",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    from django.core.management import call_command

    call_command("revoke_token", user=owner.email, name="shell")

    rows = _deaths(token)
    assert len(rows) == 1, rows
    assert rows[0].door == "shell"
    assert rows[0].tenant_id == tenant.pk
    assert rows[0].outcome == AuditEntry.Outcome.OK
    assert rows[0].object_type == ApiToken._meta.label


def test_a_rest_self_revoke_writes_an_audit_row(api: Any, tenant: Tenant, owner: User) -> None:
    """The same row, through the door a person uses, saying `rest`."""
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="rest",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    api.force_login(owner)

    response = api.delete(f"/api/v1/tokens/{token.pk}/")
    assert response.status_code == 204, response.content

    rows = _deaths(token)
    assert len(rows) == 1, rows
    assert rows[0].door == "rest"
    assert rows[0].tenant_id == tenant.pk


def test_the_rest_rows_record_the_person_who_did_it(api: Any, tenant: Tenant, owner: User) -> None:
    """**The inversion.** A prior test pinned the gap; this asserts it closed.

    Its predecessor was `test_the_revoke_row_records_the_door_but_not_the
    _person`, a must-delete-when-fixed test whose docstring said in as many
    words: "this test fails the day somebody adds the actor, and the failure is
    the reminder to delete it and assert the person instead." This is that day,
    ADR core-22 is the ruling, and this is the assertion it asked for.

    A session call is `human` with `actor_user` set and `actor_token` None —
    ADR core-22's first actor semantic. Both halves of the pair are asserted,
    because a mint that recorded the person and a revocation that did not would
    leave the trail answering "who was given this" and not "who ended it",
    which is the exact asymmetry closed on the row's existence and on
    its content.
    """
    api.force_login(owner)
    minted = api.post(
        "/api/v1/tokens/",
        data={"name": "attributed", "scopes": ["*"]},
        content_type="application/json",
    )
    assert minted.status_code == 201, minted.content
    token = ApiToken.objects.get(pk=minted.json()["id"])

    assert api.delete(f"/api/v1/tokens/{token.pk}/").status_code == 204

    birth = _births(token)[0]
    death = _deaths(token)[0]
    for row in (birth, death):
        assert row.door == "rest"
        assert row.actor_kind == AuditEntry.Kind.HUMAN, "a person clicked this"
        assert row.actor_user_id == owner.pk, "and the trail says WHICH person"
        assert row.actor_token_id is None, "a session is not an agent"


def test_the_shell_row_is_system_with_no_person_and_that_is_the_contract(
    tenant: Tenant, owner: User
) -> None:
    """ADR core-22's absence (iv), asserted as contract rather than rediscovered.

    A management command's row is `door=shell, kind=system, actor_user` None,
    and that row IS the contract: the box's own access audit (ssh) owns *who
    held the shell*, and this table does not duplicate an authority it cannot
    verify. What the row does owe — the door, and the tenant acted on — the
    command now threads explicitly through `system_actor(tenant=…)`, so the
    shape is deliberate rather than defaulted from the bound context.

    The test exists so that a later reader meeting a null `actor_user` on a
    shell row can tell the contract from a defect without re-deriving the
    ruling, and so that "attribute the overnight command to somebody" fails
    here before it reaches the trail.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="shell-contract",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    from django.core.management import call_command

    call_command("revoke_token", user=owner.email, name="shell-contract")

    row = _deaths(token)[0]
    assert row.door == "shell"
    assert row.actor_kind == AuditEntry.Kind.SYSTEM
    assert row.actor_user_id is None, "absence (iv): ssh owns who held the shell"
    assert row.actor_token_id is None
    assert row.tenant_id == tenant.pk, "what the row DOES owe is threaded, not defaulted"


def test_a_bearer_revocation_records_the_machine_and_the_person(
    tenant: Tenant, owner: User
) -> None:
    """ADR core-22's second actor semantic: `agent` carries BOTH ids.

    "The person authorised the machine once, months ago, and 'a human clicked
    this' is not true of it" — `actor_from_request`'s own doctrine, which the
    ADR quotes. So a bearer call is not a session with a different label: the
    row names the credential as well as the person, and that is what tells a
    support agent's click from an integration's overnight sweep.

    Driven through the service with a bearer-shaped actor rather than over the
    wire, because a token revoking itself over `DELETE` is a separate property
    (`test_tokens.py` owns it) and this one is about what lands in the row.
    """
    agent_token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="agent-birth",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    victim, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="agent-death",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant, kind="agent", token=agent_token),
    )

    revoke_token(
        token=victim,
        tenant=victim.tenant,
        actor=actor_for(user=owner, tenant=tenant, kind="agent", token=agent_token),
    )

    for row in (_births(victim)[0], _deaths(victim)[0]):
        assert row.actor_kind == AuditEntry.Kind.AGENT
        assert row.actor_user_id == owner.pk
        assert row.actor_token_id == agent_token.pk


# --- the pin decides the population ------------------------------------------


def test_an_unpinned_tokens_death_joins_its_births_population(owner: User) -> None:
    """The null-tenant answer, asserted as the PAIR it is a claim about.

    A token pinned to no workspace is a real product state, not an absence
    (ADR core-8's own words about the mint). Its birth row is in the platform
    population; its death row must be beside it. Asserting only "the revoke row
    has tenant None" would pass just as well if the mint row had drifted
    somewhere else — the claim is that they are together.
    """
    token, _ = issue_token(
        user=owner,
        tenant=None,
        name="unpinned",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=None),
    )

    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )

    birth = _births(token)
    death = _deaths(token)
    assert len(birth) == 1 and len(death) == 1, (birth, death)
    assert birth[0].tenant_id is None
    assert death[0].tenant_id is None
    assert birth[0].tenant_id == death[0].tenant_id

    platform = set(AuditEntry.objects.for_platform().values_list("pk", flat=True))
    assert birth[0].pk in platform
    assert death[0].pk in platform


def test_a_pinned_tokens_death_joins_its_births_population(tenant: Tenant, owner: User) -> None:
    """The same pairing for the ordinary case, so the claim is not null-only."""
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="pinned",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )

    birth = _births(token)
    death = _deaths(token)
    assert [row.tenant_id for row in birth] == [tenant.pk]
    assert [row.tenant_id for row in death] == [tenant.pk]
    assert AuditEntry.objects.for_platform().filter(object_id=token.pk).count() == 0


# --- the parameter cannot lie ------------------------------------------------


def test_a_tenant_that_disagrees_with_the_pin_is_refused(
    tenant: Tenant, owner: User, other_tenant: Tenant
) -> None:
    """The row can never be filed under a workspace the credential was not in.

    Nothing is written and nothing moves; the trail still records the attempt,
    as the failed-call row `@service` already writes on a `DomainError`.

    **And that row names the credential** (ADR core-22).
    A refused call returns nothing, so `object_id` is `None` and always will
    be; what answers AU-3's "identity of associated … objects" here is the
    redacted `input`, which renders a `models.Model` argument
    as `<app_label>.<Model>:<pk>` whatever its parameter is called. Before it,
    the trail said a revocation had been refused and never *which* credential
    somebody had tried to kill — which is the half of the sentence a reviewer
    of a refused revocation actually needs.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="mismatch",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    with pytest.raises(Invalid):
        revoke_token(
            token=token,
            tenant=other_tenant,
            # The actor is the token's own person acting in the token's own
            # workspace; only the `tenant` ARGUMENT lies, which is the thing
            # under test. An actor built from `other_tenant` would be testing
            # two lies at once.
            actor=actor_for(user=token.user, tenant=token.tenant),
        )

    token.refresh_from_db()
    assert token.revoked_at is None

    rows = _failed_revokes()
    assert len(rows) == 1, rows
    assert rows[0].outcome == AuditEntry.Outcome.ERROR
    assert rows[0].error_code == "invalid"
    assert rows[0].object_id is None, "a refused call returned nothing to name"
    assert rows[0].input["token"] == f"{ApiToken._meta.label}:{token.pk}", rows[0].input
    assert rows[0].actor_user_id == owner.pk, "and WHO was refused"


def test_the_mismatch_refusal_files_nothing_under_the_wrong_tenant(
    tenant: Tenant, owner: User, other_tenant: Tenant
) -> None:
    """The failed row itself must not be the leak the guard exists to stop.

    **AUDIT-2 found this test passing for a reason it did not state, and the
    finding is booked rather than papered over.** It asserts that nothing is
    filed under `other_tenant` *about this token* — and on the pre-AUDIT-2 tree
    that held vacuously, because a refused call returns nothing, so `object_id`
    is `None` on every error row and the filter could never match whatever the
    row said.

    What the row actually does is file under the tenant the CALL NAMED:
    `@service` writes the failure row from `kwargs["tenant"]`, which on this
    path is the value the service just refused as a lie. So a refused
    revocation lands in the claimed workspace's trail, and since criterion 4
    the redacted `input` names the foreign token's primary key there. A pk is
    not a secret and the plaintext is never present by construction (ADR
    core-22), so this is noise rather than a capability — but "which population
    does a REFUSED call's row join" is a question the ADR's five absences do
    not answer, and AUDIT-2 hands it to the lead rather than ruling it from a
    builder's seat. The assertion below pins what is true today, and the second
    one pins the shape of the finding so it cannot be closed by accident.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="not-yours",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    with pytest.raises(Invalid):
        revoke_token(
            token=token,
            tenant=other_tenant,
            actor=actor_for(user=token.user, tenant=token.tenant),
        )

    assert AuditEntry.objects.filter(tenant=other_tenant, object_id=token.pk).count() == 0

    # The finding, pinned rather than asserted away: the refused call's row IS
    # in the claimed workspace's population, because the decorator files a
    # failure from the argument the service just refused. Nothing about the
    # credential travels except its label and primary key.
    claimed = AuditEntry.objects.filter(tenant=other_tenant, action=REVOKE)
    assert claimed.count() == 1, "the shape of the finding changed; re-read the docstring"
    assert claimed.get().input["token"] == f"{ApiToken._meta.label}:{token.pk}"
    assert token.key_hash not in str(claimed.get().input), "never the credential itself"


def test_an_unpinned_token_refuses_a_named_tenant(tenant: Tenant, owner: User) -> None:
    """The guard reads both directions: `None` disagrees with a real tenant."""
    token, _ = issue_token(
        user=owner,
        tenant=None,
        name="unpinned-guard",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=None),
    )

    with pytest.raises(Invalid):
        revoke_token(token=token, tenant=tenant, actor=actor_for(user=token.user, tenant=tenant))

    token.refresh_from_db()
    assert token.revoked_at is None


# --- the second revoke is an idempotent no-op --------------------------


def _counting_kick(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Divert the channel layer's `KICK` and count what reaches it.

    Only the `KICK` name is diverted, for the reason `test_socket_kick.py`
    gives: emptying `bridge.find` would take every other registration out of
    the process for whatever this order-randomised suite runs next.
    """
    kicked: list[UUID] = []
    real_find = bridge.find

    def counting(*, user_id: UUID, reason: str) -> None:
        kicked.append(user_id)

    def find(name: str) -> Any:
        return counting if name == bridge.KICK else real_find(name)

    monkeypatch.setattr(bridge, "find", find)
    return kicked


@pytest.mark.django_db(transaction=True)
def test_a_second_revoke_moves_nothing_and_kicks_nobody(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first call revokes and kicks; the second does neither.

    `transaction=True` because the kick rides `transaction.on_commit`, and a
    test that never commits would be counting a hook that never ran — which
    would make the second half pass for the wrong reason.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="twice",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    kicked = _counting_kick(monkeypatch)

    first = revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )
    moment = first.revoked_at
    assert moment is not None
    assert kicked == [owner.pk], kicked

    second = revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )

    assert second.revoked_at == moment, "the recorded moment moved"
    assert second.revoked_at is not None
    assert second.revoked_at.isoformat() == moment.isoformat(), "byte-equal, not merely close"
    token.refresh_from_db()
    assert token.revoked_at == moment
    assert kicked == [owner.pk], f"the no-op fired a kick: {kicked}"


def test_a_second_revoke_still_audits_the_call(tenant: Tenant, owner: User) -> None:
    """A no-op is not a non-event: the trail records that somebody asked again.

    The guard is idempotence, not silence — `@service` writes its row for every
    successful call, and two revocation attempts on one credential is exactly
    the kind of thing a trail is read for afterwards.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="asked-twice",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )
    revoke_token(
        token=token, tenant=token.tenant, actor=actor_for(user=token.user, tenant=token.tenant)
    )

    rows = _deaths(token)
    assert len(rows) == 2, rows
    assert {row.outcome for row in rows} == {AuditEntry.Outcome.OK}


def test_rest_delete_twice_answers_204_twice_and_the_moment_holds(
    api: Any, tenant: Tenant, owner: User
) -> None:
    """The CHANGED REST behaviour, pinned as its own test rather than inherited.

    `DELETE` is idempotent by HTTP law and this route has answered `204` on a
    re-delete since it landed — what changed under it is that the second call
    no longer overwrites `revoked_at`. Before the ruling the status code was
    the same and the timestamp moved, so a test that asserted only the status
    would have been green through the whole defect.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="rest-twice",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    api.force_login(owner)

    first = api.delete(f"/api/v1/tokens/{token.pk}/")
    assert first.status_code == 204, first.content
    token.refresh_from_db()
    moment = token.revoked_at
    assert moment is not None

    second = api.delete(f"/api/v1/tokens/{token.pk}/")
    assert second.status_code == 204, second.content

    token.refresh_from_db()
    assert token.revoked_at == moment, "the second DELETE moved the recorded moment"


# --- the docstring the ruling says goes stale --------------------------------


def test_declares_tenant_no_longer_lists_revoke_as_unaudited() -> None:
    """The prose list in `_declares_tenant` predicted its own staleness.

    It says so in as many words — "the list is prose and nothing checks it,
    which is exactly how it went stale" — and this ruling is the event it
    predicted.

    Scoped to the **parenthetical roll-call** and nothing else. The paragraph
    around it now discusses `revoke_token` at length — that it left, and why —
    and a test that searched the whole paragraph for the string would refuse
    the correction it exists to enforce. What must not name it is the list of
    services that are "unaudited before and unaudited now".
    """
    from apps.core.service import _declares_tenant

    doc = _declares_tenant.__doc__ or ""
    tail = doc.split("or declares no `tenant` at all (")[-1]
    roll_call = tail.split(")")[0]

    assert "create_user" in roll_call, "the roll-call moved; this test is reading the wrong text"
    assert "revoke_token" not in roll_call, (
        "`_declares_tenant`'s unaudited roll-call still names revoke_token, which "
        "now declares a tenant and is audited (ADR core-22)"
    )
