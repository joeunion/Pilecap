"""The join between a person here and a subject at the identity platform.

One column, `User.zitadel_sub`, and one writer — `record_identity`. This
module is about the writer's own law rather than about any door: what it does
with each of the four states a (person, subject) pair can be in, and what the
operator does when the identity platform legitimately hands out new subjects for
everybody at once.

**Why the subject and not the address.** An address is a label an employer can
reassign; a subject is the account. Keying the join on the address is how
somebody inherits their predecessor's access along with their desk — and, worse,
how anybody who can make the trusted issuer assert a chosen verified address
under a FRESH subject walks into the account standing at that address. The
writer's docstring has said so since it was written; these cases are that
sentence made executable.
"""

from __future__ import annotations

import logging

import pytest
from allauth.socialaccount.models import SocialAccount
from django.http import HttpRequest

from apps.accounts.adapter import SocialAccountAdapter
from apps.accounts.models import STAFF_REALM, User
from apps.accounts.selectors import get_platform_provider_id
from apps.accounts.services import record_identity, unlink_zitadel_identity
from apps.accounts.tests.conftest import assertion, join, subject_of
from apps.accounts.tests.test_rp_login import structured
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict

pytestmark = pytest.mark.django_db


def platform_actor() -> Actor:
    """The altitude the adapter calls the writer at: no tenant, no person."""
    return system_actor(tenant=None)


# --- the four states of (this person, this subject) ---------------------------


def test_the_writer_refuses_a_second_subject(owner: User) -> None:
    """A DIFFERING standing subject is a refusal, and nothing is written.

    The state the writer used to take silently. `owner` has signed in before, so
    the column holds the subject the platform gave them; an assertion carrying a
    different one is not an update — it is a claim that this account belongs to
    somebody the platform has not seen here before, and the only honest answers
    are "no" and "an operator cut the old join on purpose" (the road below).
    """
    join(owner, "sub-original")

    with pytest.raises(Conflict) as refused:
        record_identity(
            realm=STAFF_REALM,
            user=owner,
            subject="sub-impostor",
            tenant=None,
            actor=platform_actor(),
        )

    # The sentence is the writer's own, and it names no account.
    assert "already linked to a different account" in refused.value.detail
    owner.refresh_from_db()
    assert subject_of(owner) == "sub-original"
    # The refusal keeps its receipt: a service's ordinary error row.
    refusals = AuditEntry.objects.for_platform().filter(
        action="accounts.record_identity", outcome="error"
    )
    assert refusals.count() == 1


def test_the_same_subject_is_a_no_op_and_still_audited(owner: User) -> None:
    """Every login calls this, not only the first, so the no-op is the common case.

    The row is written anyway: "the platform asserted this identity again" is
    the fact the ledger is being asked for.
    """
    join(owner, "sub-original")

    record_identity(
        realm=STAFF_REALM, user=owner, subject="sub-original", tenant=None, actor=platform_actor()
    )

    owner.refresh_from_db()
    assert subject_of(owner) == "sub-original"
    assert (
        AuditEntry.objects.for_platform()
        .filter(action="accounts.record_identity", outcome="ok")
        .count()
        == 1
    )


def test_a_free_subject_on_an_unlinked_account_is_recorded(owner: User) -> None:
    """The first-login path, and the only one that writes the column."""
    assert subject_of(owner) is None

    record_identity(
        realm=STAFF_REALM, user=owner, subject="sub-new", tenant=None, actor=platform_actor()
    )

    owner.refresh_from_db()
    assert subject_of(owner) == "sub-new"


def test_a_subject_held_by_somebody_else_is_refused(owner: User, member: User) -> None:
    """The fourth state, and the one direction the writer always refused.

    Kept beside its three siblings rather than left alone in the door's module:
    the four together are the population, and a reader who sees three of them
    would have to go looking for the fourth to know the law is complete.
    """
    join(owner, "a-subject-that-is-taken")

    with pytest.raises(Conflict):
        record_identity(
            realm=STAFF_REALM,
            user=member,
            subject="a-subject-that-is-taken",
            tenant=None,
            actor=platform_actor(),
        )

    member.refresh_from_db()
    assert subject_of(member) is None


# --- the legitimate road: an operator cuts the join -------------------------


def test_unlinking_clears_the_subject_and_leaves_an_audit_row_with_the_reason(
    owner: User,
) -> None:
    """The act that makes a refusal survivable.

    Once a differing subject is refused, an issuer swap or a re-seed — which
    changes every subject at once — would lock the whole deployment out with no
    way back. This is the way back, and it is an operator's audited act rather
    than a flag on the sign-in road: a door that takes accounts over on a flag
    is the hole, wearing a switch.
    """
    join(owner, "sub-old")

    unlink_zitadel_identity(
        user=owner,
        actor=system_actor(tenant=None),
        tenant=None,
        reason="the identity platform was re-seeded",
    )

    assert subject_of(owner) is None
    row = (
        AuditEntry.objects.for_platform()
        .filter(action="accounts.unlink_zitadel_identity")
        .order_by("-created_at")
        .first()
    )
    assert row is not None
    assert row.outcome == "ok"
    assert row.input.get("reason") == "the identity platform was re-seeded"


def test_a_re_seeded_subject_is_recorded_after_an_unlink(owner: User) -> None:
    """The whole road, end to end, in the order an operator walks it."""
    record_identity(
        realm=STAFF_REALM, user=owner, subject="sub-old", tenant=None, actor=platform_actor()
    )

    unlink_zitadel_identity(
        user=owner,
        actor=system_actor(tenant=None),
        tenant=None,
        reason="issuer swap",
    )
    record_identity(
        realm=STAFF_REALM, user=owner, subject="sub-new", tenant=None, actor=platform_actor()
    )

    owner.refresh_from_db()
    assert subject_of(owner) == "sub-new"


def test_unlinking_removes_the_allauth_row_too(
    owner: User, member: User, caplog: pytest.LogCaptureFixture
) -> None:
    """A cut join leaves no handle behind — and takes only the platform's rows.

    **The test this replaces asserted the opposite**, on the reading that
    `SocialAccount` is allauth's table and "is replaced by the next successful
    sign-in". It is not replaced: a sign-in ADDS a row, the old one stays, and
    allauth resolves `(provider, uid)` itself after the adapter has finished —
    so the subject an operator just cut still signs somebody in as this person
    (V-R2F drove it: 302, a session as the owner). The claim was the hole.

    A workforce row is left alone in the same call, because this is about one
    identity platform's join and not about the person: taking Google's row with
    it would be an erasure wearing an unlink's name.
    """
    join(owner, "sub-old")
    SocialAccount.objects.create(user=owner, provider="zitadel", uid="sub-old")
    SocialAccount.objects.create(user=owner, provider="google", uid="g|owner")
    # Somebody else's platform row, to prove the filter is on this person too.
    SocialAccount.objects.create(user=member, provider="zitadel", uid="sub-member")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        unlink_zitadel_identity(
            user=owner, actor=system_actor(tenant=None), tenant=None, reason="issuer swap"
        )

    assert SocialAccount.objects.filter(uid="sub-old", user_id=owner.pk).count() == 0
    assert SocialAccount.objects.filter(provider="google", user_id=owner.pk).count() == 1
    assert SocialAccount.objects.filter(uid="sub-member", user_id=member.pk).count() == 1
    row = (
        AuditEntry.objects.for_platform()
        .filter(action="accounts.unlink_zitadel_identity")
        .order_by("-created_at")
        .first()
    )
    assert row is not None and row.outcome == "ok"
    # **How many went, on the line that can carry it.** The criterion asked for
    # this number on the audit row's `input`, and `@service` builds that payload
    # from the CALL's keyword arguments before the body runs — a count the body
    # computes has no seam into it without a change in `apps/core/service.py`,
    # which is another rung's territory. Flagged there, asserted here.
    unlinked = [
        line for line in structured(caplog) if line.get("event") == "accounts.identity.unlinked"
    ]
    assert len(unlinked) == 1, structured(caplog)
    assert unlinked[0]["social_accounts_removed"] == 1
    assert unlinked[0]["user_id"] == str(owner.pk)


def test_a_person_from_the_direct_google_road_is_joined_at_their_first_zitadel_sign_in(
    platform_provider: None, login_request: HttpRequest
) -> None:
    """The fold's step two: somebody the retired direct road created, arriving through Zitadel.

    Their row predates the platform join — no `zitadel_sub` — and carries the
    direct road's own `SocialAccount(provider="google")`, keyed on Google's
    subject rather than Zitadel's. Through Zitadel's Google button they arrive
    as a platform assertion with a subject nobody holds, at their verified
    address, OUTSIDE any configured workforce domain (a deployment may have
    changed the list since). The door's rule — the subject resolves the person,
    the address introduces one while nothing already speaks for either — JOINS
    them: the same row, the subject recorded, no second account and no wall,
    because an existing person is not a signup.
    """
    person = User.objects.create(email="staff@moved-domain.example")
    SocialAccount.objects.create(user=person, provider="google", uid="google-sub-1")

    login = assertion(
        provider=get_platform_provider_id(), subject="zitadel-sub-1", email=person.email
    )
    SocialAccountAdapter(login_request).pre_social_login(login_request, login)

    assert login.user is not None and login.user.pk == person.pk
    person.refresh_from_db()
    assert subject_of(person) == "zitadel-sub-1"
    assert User.objects.filter(email=person.email).count() == 1
    # The direct road's row is left where it was; it signs nobody in any more.
    assert SocialAccount.objects.filter(provider="google", user_id=person.pk).count() == 1
