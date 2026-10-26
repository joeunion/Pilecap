"""The shell door: `issue_token`, `unlink_identity`, `verify_sso_domain`.

Two commands, one persona — somebody with ssh on the deployment — and one
contract they share: **every refusal exits non-zero and says why, and a refusal
that could not even look exits 2.** A door whose refusal path prints nothing and
exits 0 reads to a script, and to a person in a hurry, exactly like a success.
"""

from __future__ import annotations

import logging
from io import StringIO

import pytest
from allauth.socialaccount.models import SocialAccount
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.management.commands.grant_staff import Command as GrantStaffCommand
from apps.accounts.models import STAFF_REALM, ApiToken, SsoConnection, SsoDomain, SsoIdentity, User
from apps.accounts.selectors import get_connection_for_email
from apps.accounts.services import authenticate_token, create_user, record_identity
from apps.accounts.tests.conftest import subject_of
from apps.accounts.tests.test_rp_login import structured
from apps.core.actor import system_actor
from apps.core.api.scopes import effective_scopes
from apps.core.audit import AuditEntry
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

UNLINK_ACTION = "accounts.unlink_zitadel_identity"


def _run(**options: object) -> str:
    out = StringIO()
    call_command("issue_token", stdout=out, **options)
    return out.getvalue()


def _unlink(out: StringIO, **options: object) -> None:
    """`manage.py unlink_identity`, writing into a buffer the CALLER holds.

    The buffer is the caller's rather than this helper's return value because
    what a refusal printed BEFORE it raised is part of the refusal — the `--all`
    count is the whole reason that particular refusal is useful, and a helper
    that returned its output would lose it on exactly the cases that matter.
    """
    call_command("unlink_identity", stdout=out, **options)


def test_it_prints_a_token_that_works(tenant: Tenant, owner: User) -> None:
    printed = _run(email=owner.email, tenant=tenant.slug, name="laptop", scopes=["*"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[0] == owner
    assert resolved[1] == tenant

    token = ApiToken.objects.get(name="laptop")
    assert token.tenant_id == tenant.pk
    assert plaintext not in token.key_hash


def test_without_a_tenant_the_token_resolves_one_per_request(tenant: Tenant, owner: User) -> None:
    printed = _run(email=owner.email, name="unpinned", scopes=["*"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))
    assert ApiToken.objects.get(name="unpinned").tenant_id is None
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[1] == tenant


def test_it_refuses_an_unknown_user(tenant: Tenant) -> None:
    with pytest.raises(CommandError):
        _run(email="nobody@example.com", tenant=tenant.slug, name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


def test_it_refuses_an_unknown_tenant(owner: User) -> None:
    with pytest.raises(CommandError):
        _run(email=owner.email, tenant="not-a-tenant", name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


def test_it_refuses_a_tenant_the_user_does_not_belong_to(owner: User, other_tenant: Tenant) -> None:
    """The command cannot mint what the doors would refuse to honour."""
    with pytest.raises(CommandError):
        _run(email=owner.email, tenant=other_tenant.slug, name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


# --- the two lines about reach, and the one that used to lie ------------


def _line(printed: str, label: str) -> str:
    """The value on the `label:` line, or `""` when the command printed none."""
    for line in printed.splitlines():
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


def test_an_ordinary_write_mint_says_nothing_is_wrong(tenant: Tenant, owner: User) -> None:
    """The warning fired on every `:write` mint, naming nothing.

    The check was `set(usable) != set(token.scopes)`, and those two sets differ
    by design on any write mint: asking for `widgets:write` carries
    `widgets:read`, so `usable` is legitimately *larger*. The sentence was then
    built from `set(token.scopes) - set(usable)`, which is empty — so the shell
    printed "role cannot back  today" with a hole where the list should be, on a
    mint with nothing at all wrong with it.

    An owner can back both halves, so there is nothing to warn about and the
    command says nothing. That is the property: silence when it is fine.
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="agent", scopes=["widgets:write"])
    assert "note:" not in printed, printed
    assert "cannot back" not in printed, printed


def test_the_note_still_fires_and_names_the_dead_scope(tenant: Tenant, member: User) -> None:
    """And it did not stop warning — a member asking to write cannot, and is told.

    The sibling of the test above, and the reason the fix is not "delete the
    warning": this is the case it exists for. Writing needs an administrator
    under the default rule, so a plain member's `org-structure:write` is dead
    weight the moment the token is minted, and the list in the sentence is not
    empty.
    """
    printed = _run(
        email=member.email, tenant=tenant.slug, name="agent", scopes=["org-structure:write"]
    )
    assert "org-structure:write" in _line(printed, "note")


def test_the_shell_shows_the_expansion_the_wire_has_always_shown(
    tenant: Tenant, owner: User
) -> None:
    """`effective:` — the same echo `POST /tokens/` returns.

    The expansion is the fact that shrank a field test's list from twelve scopes
    to six: within a section the write scope carries the read, so an operator
    who asks for six write scopes has handed over twelve. The HTTP mint has
    echoed that since ADR ident-7; the shell — the door somebody setting a
    machine up actually stands at — printed only what was asked for.

    Asserted against `effective_scopes` itself rather than against a literal
    pair, so this test says "the shell prints the derivation" and cannot come to
    mean "the shell prints these two words".
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="agent", scopes=["widgets:write"])
    expected = effective_scopes(user=owner, tenant=tenant, scopes=["widgets:write"])
    assert expected is not None
    assert _line(printed, "effective") == ", ".join(expected)
    assert _line(printed, "scopes") == "widgets:write"


def test_an_unlimited_token_says_so_on_both_lines(tenant: Tenant, owner: User) -> None:
    """`--scope '*'` stores no ceiling, so there is nothing to expand or to trim.

    The line still prints. A missing one reads as "we did not work it out",
    which is not what happened.
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="wide", scopes=["*"])
    assert _line(printed, "scopes") == "(no limit)"
    assert _line(printed, "effective") == "(no limit)"
    assert "note:" not in printed


# --- the alarm that fired on every unpinned mint -----------------------

PER_REQUEST = "(per request — resolved at the door)"


def test_an_unpinned_mint_says_where_the_reach_is_worked_out(owner: User) -> None:
    """No `--tenant` means no role here to work a set out against.

    `effective_scopes` is derived from the role this person holds *in the
    token's tenant*. An unpinned token has no tenant at the mint — it resolves
    one per request, at the door, from whichever membership the request lands
    on — so the mint was asking a question it could not have an answer to, and
    `effective_scopes(user, tenant=None, ...)` obliged: no membership found,
    rank zero, the empty set. That is an answer about what the *command* does
    not know, and it was printed as an answer about what the *person* cannot
    do, under a `note:` naming every scope asked for.

    The red, on this very fixture: `owner` is an OWNER of `acme` — the role
    that backs everything there is — and the shell told them their role backs
    nothing, on a token that then authenticated, resolved `acme`, and carried
    exactly the scope they asked for. The alarm did not fire for `owner` in
    particular; it fired for *everybody*, on every unpinned mint with a
    ceiling, which is the whole of the defect: a warning that fires when
    nothing is wrong is a warning nobody reads the day something is.
    """
    printed = _run(email=owner.email, name="unpinned-reach", scopes=["widgets:read"])

    assert _line(printed, "tenant") == "(per request)"
    assert _line(printed, "effective") == PER_REQUEST
    assert "note:" not in printed, printed
    assert "cannot back" not in printed, printed
    assert "(nothing this role can back today)" not in printed, printed


def test_the_unpinned_token_the_mint_kept_quiet_about_actually_works(
    tenant: Tenant, owner: User
) -> None:
    """The other half: the token the false alarm was about is fine.

    A warning is only wrong if the thing it warns about is not true, so this is
    the test that makes the one above a defect report rather than a preference.
    The same mint, taken to the door: the token authenticates, the door resolves
    the tenant the mint declined to guess, and the scope the shell called dead
    is live against the role the door found.
    """
    printed = _run(email=owner.email, name="unpinned-works", scopes=["widgets:read"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved.tenant == tenant
    at_the_door = effective_scopes(
        user=resolved.user, tenant=resolved.tenant, scopes=resolved.token.scopes
    )
    assert at_the_door == ["widgets:read"]


def test_the_unpinned_line_does_not_depend_on_who_is_minting(nomad: User) -> None:
    """And it says the same thing for somebody who belongs nowhere — deliberately.

    `nomad` holds no membership at all, so their unpinned token really will find
    no tenant at the door. The mint still cannot say so: it does not know which
    request this token will arrive on, and "this person belongs nowhere" is a
    fact about the person that the *door* discovers, not one the mint may
    announce from an empty query. The line is about where the answer comes from,
    so it is the same line for everyone — which is exactly what stops it drifting
    back into a claim about a role.
    """
    printed = _run(email=nomad.email, name="hopeful", scopes=["widgets:read"])
    assert _line(printed, "effective") == PER_REQUEST
    assert "note:" not in printed, printed


def test_an_unpinned_unlimited_mint_still_says_no_limit(owner: User) -> None:
    """`--scope '*'` is outside the fix, and stays outside it.

    A token with no ceiling has nothing to expand and nothing to trim, so
    "(no limit)" is the whole truth whether a tenant was named or not. Pinned
    here because the tempting fix — branch on `tenant is None` and be done —
    would have replaced a complete answer with a vaguer one on this path.
    """
    printed = _run(email=owner.email, name="unpinned-wide", scopes=["*"])
    assert _line(printed, "scopes") == "(no limit)"
    assert _line(printed, "effective") == "(no limit)"
    assert "note:" not in printed


def test_naming_the_tenant_is_what_turns_the_computed_answer_on(
    tenant: Tenant, member: User
) -> None:
    """The contrast the rung is about, one person and one scope, both ways.

    With `--tenant` nothing changed: the set is computed from the role, and the
    `note:` still names what that role cannot back — this is `member` asking to
    write, the case the warning exists for. Without it, the same request gets
    the line that says where the answer is worked out, and no warning, because
    nothing was worked out to warn about.
    """
    pinned = _run(
        email=member.email, tenant=tenant.slug, name="pinned", scopes=["org-structure:write"]
    )
    unpinned = _run(email=member.email, name="not-pinned", scopes=["org-structure:write"])

    assert _line(pinned, "effective") == "org-structure:read"
    assert "org-structure:write" in _line(pinned, "note")

    assert _line(unpinned, "effective") == PER_REQUEST
    assert "note:" not in unpinned, unpinned


# --- `manage.py unlink_identity` — the road back from a refused subject -------
#
# The command whose whole purpose is to be survivable: once a differing standing
# subject is refused at the sign-in door, an issuer swap or a re-seed would lock
# out everybody it touched with no way back. These four cases are the ones a
# review found missing (V-R2F) — the confirmation wall, the sweep, the mistyped
# address, and the person there was nothing to do for.


def _joined(email: str, subject: str) -> User:
    """Somebody who has signed in: our column set, and allauth's row beside it."""
    person = create_user(email=email, password=None)
    record_identity(
        realm=STAFF_REALM,
        user=person,
        subject=subject,
        tenant=None,
        actor=system_actor(tenant=None),
    )
    SocialAccount.objects.create(user=person, provider="zitadel", uid=subject)
    return person


def test_unlink_identity_refuses_all_without_yes(owner: User) -> None:
    """The count is printed FIRST, and then the run refuses.

    `--all` unlinks every person who has ever signed in, and the next thing each
    of them does is sign in again. An operator should read that number before it
    happens rather than after, so the number goes to stdout before the refusal
    and the refusal costs exit 1 — a refusal, not a could-not-look.
    """
    _joined("one@example.com", "sub-one")
    _joined("two@example.com", "sub-two")
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _unlink(out, all=True, reason="issuer swapped")

    assert "people holding a subject: 2" in out.getvalue(), out.getvalue()
    assert "--yes" in str(refused.value)
    assert refused.value.returncode == 1
    # And nothing moved: a refusal that had already unlinked one of them would
    # be the worst of both answers.
    assert (
        SsoIdentity.objects.filter(connection__isnull=True).values("user").distinct().count() == 2
    )
    assert AuditEntry.objects.for_platform().filter(action=UNLINK_ACTION).count() == 0


def test_unlink_identity_all_prints_the_count_and_audits_each(owner: User) -> None:
    """The sweep: every join cut, every cut audited, and nobody else touched.

    `owner` holds no subject and is therefore outside the population by
    construction — the command asks for people holding one — which is what makes
    the printed count a claim about the sweep rather than about the table.
    """
    one = _joined("one@example.com", "sub-one")
    two = _joined("two@example.com", "sub-two")
    out = StringIO()

    _unlink(out, all=True, yes=True, reason="the identity platform was re-seeded")

    printed = out.getvalue()
    assert "people holding a subject: 2" in printed, printed
    assert "unlinked 2 person(s)" in printed, printed
    assert (
        SsoIdentity.objects.filter(connection__isnull=True).values("user").distinct().count() == 0
    )
    assert SocialAccount.objects.filter(provider="zitadel").count() == 0
    rows = AuditEntry.objects.for_platform().filter(action=UNLINK_ACTION, outcome="ok")
    assert rows.count() == 2
    assert {row.input.get("reason") for row in rows} == {"the identity platform was re-seeded"}
    assert {str(row.object_id) for row in rows} == {str(one.pk), str(two.pk)}


def test_unlink_identity_names_nobody_is_exit_two(owner: User) -> None:
    """A mistyped address is COULD NOT LOOK, and that is exit 2, not exit 1.

    The two are different answers to an operator and to a script: 1 says "I
    refused what you asked for", 2 says "I never found it to refuse". An
    operator who mistyped an address and read either a success or a plain
    refusal would believe a person had been freed. The idiom is the tree's own —
    `CommandError(..., returncode=2)`, as `core`'s `newapp` raises it.
    """
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _unlink(out, email="nobody@example.com", reason="typo")

    assert refused.value.returncode == 2
    assert "nobody@example.com" in str(refused.value)
    assert AuditEntry.objects.for_platform().filter(action=UNLINK_ACTION).count() == 0


def test_unlink_identity_on_a_person_with_no_subject_is_a_no_op(
    owner: User, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing to cut is not an act, and it must not be recorded as one.

    The command used to report success here, file an audit row for an unlink
    that did not happen, and close the person's sockets — three consequences for
    somebody nobody touched (V-R2F's minor). The service is simply not called,
    which is also why no kick is registered: `close_sockets_on_commit` runs
    inside `unlink_zitadel_identity`, so a service that never ran registered
    none. The absence of both its audit row and its own log line is the artifact
    for that; the socket instruments themselves live in `test_socket_kick.py`.
    """
    assert subject_of(owner) is None
    out = StringIO()

    caplog.clear()
    with caplog.at_level(logging.INFO):
        _unlink(out, email=owner.email, reason="just in case")

    assert "nothing to unlink" in out.getvalue(), out.getvalue()
    assert "unlinked:" not in out.getvalue(), out.getvalue()
    assert AuditEntry.objects.for_platform().filter(action=UNLINK_ACTION).count() == 0
    assert not [
        line for line in structured(caplog) if line.get("event") == "accounts.identity.unlinked"
    ]


# --- `manage.py verify_sso_domain` — the act that makes a claim route ---------
#
# the verified-claims routing law. Claiming a domain is something any tenant's administrator can
# do through the API and it reserves a name; making that claim ROUTE the
# platform sign-in for everybody at the domain is somebody else's act, and this
# is the door they stand at. The refusals are the point of the door: a mistyped
# slug and a domain that belongs to another tenant are different answers, and
# neither of them says whose the domain is.


def _verify(out: StringIO, **options: object) -> None:
    """`manage.py verify_sso_domain`, writing into a buffer the caller holds."""
    call_command("verify_sso_domain", stdout=out, **options)


def test_verify_sso_domain_prints_and_verifies(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """The operator's road: one command, and the claim answers afterwards."""
    out = StringIO()

    _verify(out, tenant=tenant.slug, domain="acme.com")

    printed = out.getvalue()
    assert "verified acme.com" in printed, printed
    assert unverified_sso_connection.name in printed, printed
    assert SsoDomain.objects.get(domain="acme.com").verified_at is not None
    assert get_connection_for_email("someone@acme.com") == unverified_sso_connection
    entry = AuditEntry.objects.for_tenant(tenant).get(action="accounts.verify_sso_domain")
    assert entry.outcome == AuditEntry.Outcome.OK
    assert entry.door == "shell"
    assert entry.actor_kind == "system"


def test_verify_sso_domain_a_second_time_says_already_and_exits_zero(
    unverified_sso_connection: SsoConnection, tenant: Tenant
) -> None:
    """Asking for a state that already holds is not a refusal, and says so plainly."""
    _verify(StringIO(), tenant=tenant.slug, domain="acme.com")
    was = SsoDomain.objects.get(domain="acme.com").verified_at
    out = StringIO()

    _verify(out, tenant=tenant.slug, domain="acme.com")

    assert "already verified" in out.getvalue(), out.getvalue()
    assert SsoDomain.objects.get(domain="acme.com").verified_at == was


def test_verify_sso_domain_refuses_another_tenants_claim_without_naming_it(
    sso_connection: SsoConnection, other_tenant: Tenant
) -> None:
    """The operator typed the wrong tenant — and the refusal is no directory.

    A terminal is not a reason to answer "which customer owns acme.com" for
    whoever is standing at it. Exit 1: it looked, and refused.
    """
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _verify(out, tenant=other_tenant.slug, domain="acme.com")

    # **The sentence is a function of what the OPERATOR TYPED and of nothing
    # this command looked up** — asserted as an equality rather than as a list
    # of absent words, because the tenant that holds `acme.com` is `acme` and a
    # "slug not in message" check would be satisfied by the domain the operator
    # typed themselves. What must not appear is anything the lookup found.
    message = str(refused.value)
    assert message == f"acme.com is not claimed by {other_tenant.slug}."
    assert sso_connection.name not in message
    assert str(sso_connection.pk) not in message
    assert refused.value.returncode == 1


def test_verify_sso_domain_unknown_tenant_is_exit_two(
    unverified_sso_connection: SsoConnection,
) -> None:
    """A slug that names nobody is COULD NOT LOOK — exit 2, not a refusal."""
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _verify(out, tenant="not-a-tenant", domain="acme.com")

    assert refused.value.returncode == 2
    assert "not-a-tenant" in str(refused.value)
    assert SsoDomain.objects.get(domain="acme.com").verified_at is None


# --- `manage.py grant_staff` — the one road to `is_staff` ---------------------
#
# ADR ident-4. `createsuperuser` is Django's road and it is the second
# credential store this deployment does not keep: it prompts for a password it
# writes into `User.password`, files no audit row, asks no policy, and hands out
# `is_superuser` as well. This is the road that replaces it — a service, a
# policy, an audit row — and the command's own help says so, because an operator
# reaching for the retired road reads the replacement at the moment they type it.

GRANT_STAFF_ACTION = "accounts.grant_staff"


def _grant(out: StringIO, **options: object) -> None:
    """`manage.py grant_staff`, writing into a buffer the caller holds."""
    call_command("grant_staff", stdout=out, **options)


def test_grant_staff_marks_the_person_and_audits_it(root: User, nomad: User) -> None:
    """The flag is set, and the setting of it is a row somebody can read later.

    `root` is the superuser the policy asks for and `nomad` is an ordinary
    person with no membership anywhere — which is the honest shape of the act:
    being staff is a fact about the deployment, not about a workspace.
    """
    out = StringIO()

    _grant(out, email=nomad.email, acting_email=root.email)

    nomad.refresh_from_db()
    assert nomad.is_staff is True
    printed = out.getvalue()
    assert nomad.email in printed, printed
    rows = AuditEntry.objects.for_platform().filter(action=GRANT_STAFF_ACTION, outcome="ok")
    assert rows.count() == 1
    assert str(rows.get().object_id) == str(nomad.pk)


def test_grant_staff_refuses_a_non_operator(owner: User, nomad: User) -> None:
    """A tenant's owner is the most privileged person their workspace has.

    They still may not hand out a key to the deployment's own admin: that is
    `identity_platform.configure`, which is `is_superuser` and not a role
    (`apps/accounts/policies.py` says why). The refusal costs exit 1 — it looked
    and said no — and the flag does not move.
    """
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _grant(out, email=nomad.email, acting_email=owner.email)

    assert refused.value.returncode == 1
    # The sentence, not just the status: without it `CommandError("Unknown
    # command")` from a command that does not exist yet satisfies the assertion
    # above, and the case passes before anything is built.
    assert "You may not change how this deployment signs people in." in str(refused.value)
    nomad.refresh_from_db()
    assert nomad.is_staff is False
    assert (
        not AuditEntry.objects.for_platform()
        .filter(action=GRANT_STAFF_ACTION, outcome="ok")
        .exists()
    )


def test_grant_staff_names_the_retired_road_in_its_own_help() -> None:
    """The help is where an operator meets the ADR, at the moment it applies.

    Somebody typing `manage.py help grant_staff` is somebody deciding how to make
    a person staff, which is exactly the moment `createsuperuser` is the wrong
    answer — so the help says which road was retired and why, rather than leaving
    that in an ADR they have no reason to be reading.
    """
    assert "createsuperuser" in GrantStaffCommand.help


def test_grant_staff_names_nobody_is_exit_two(root: User) -> None:
    """A mistyped address never found anybody to refuse: could-not-look, exit 2."""
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _grant(out, email="nobody@example.com", acting_email=root.email)

    assert refused.value.returncode == 2
    assert AuditEntry.objects.for_platform().filter(action=GRANT_STAFF_ACTION).count() == 0


def test_grant_staff_refuses_a_switched_off_account(root: User, nomad: User) -> None:
    """Staff on an account that cannot sign in is a key cut for a door that is bricked up.

    Not in the criteria set and added deliberately: `deactivate_user` and
    `erase_user` both clear `is_staff`, so the only way the pair could disagree
    is granting it AFTER one of them ran — which would leave an anonymised or
    switched-off row carrying admin access nobody could see being used.
    """
    nomad.is_active = False
    nomad.save(update_fields=["is_active"])
    out = StringIO()

    with pytest.raises(CommandError) as refused:
        _grant(out, email=nomad.email, acting_email=root.email)

    assert refused.value.returncode == 1
    assert "switched off" in str(refused.value)
    nomad.refresh_from_db()
    assert nomad.is_staff is False
