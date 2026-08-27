"""The identity ledger's last two gaps — one closed, one declared.

Two questions that look like one and are not.

**Does the identity join leave a trail?** It did not. `zitadel_sub` is the
column that decides which Zitadel account signs in as which of our people, it is
written on every login, and nothing recorded that it had been. It does now, in
the platform population, and the mechanism is ADR core-8's: the service declares
a `tenant` parameter, `@service` reads the declaration, and the row lands where
`AuditEntry.objects.for_platform()` can read it.

**Does a refused login leave one?** No, and that is the answer rather than
the gap. It is the same precedent (door refusals leave no audit row
BY DESIGN) applied to the workforce door: `@service` is the audit population's
one writer, and a refusal is a door turning somebody away before any write
exists. What it leaves instead is a structured log line, and the tests below
assert the ABSENCE of a row and the PRESENCE of the declaration that says the
absence is deliberate — because an undeclared absence and a bug read the same.
"""

from __future__ import annotations

import inspect

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from django.http import HttpRequest
from django.test import Client

from apps.accounts import adapter as adapter_module
from apps.accounts.adapter import GOOGLE_PROVIDER, SocialAccountAdapter
from apps.accounts.models import User
from apps.accounts.services import record_zitadel_identity
from apps.accounts.tests import test_identity_doors as doors
from apps.accounts.tests.conftest import assertion
from apps.accounts.tests.stub_issuer import StubIssuer
from apps.accounts.tests.test_rp_login import sign_in
from apps.core.actor import system_actor
from apps.core.audit import AuditEntry

pytestmark = pytest.mark.django_db

ACTION = "accounts.record_zitadel_identity"

#: The configured-workforce-door fixture, borrowed from the module whose whole
#: subject is that door rather than copied. A second copy of "both halves of the
#: Google configuration" is two fixtures that drift, and the refusal branches
#: below only mean anything against the real one.
workforce = doors.workforce


def platform_rows() -> int:
    return AuditEntry.objects.for_platform().filter(action=ACTION).count()


# --- the join is on the record ------------------------------------------


def test_recording_an_identity_writes_one_platform_audit_row(member: User) -> None:
    """The gap refined, closed. One call, one row, in the platform ledger."""
    before = platform_rows()

    record_zitadel_identity(
        user=member,
        subject="zitadel-subject-ledger-1",
        tenant=None,
        actor=system_actor(tenant=None),
    )

    assert platform_rows() == before + 1
    row = AuditEntry.objects.for_platform().filter(action=ACTION).latest("created_at")
    assert row.tenant_id is None
    assert str(row.object_id) == str(member.pk)


def test_the_row_count_tracks_the_call_count_including_the_no_op(member: User) -> None:
    """Idempotent write, non-idempotent ledger — and the ledger is right.

    `record_zitadel_identity` runs on EVERY login, not only the first, and the
    second call is a no-op against the column. It is not a no-op against the
    trail: "the platform asserted this identity again" is exactly the fact a
    ledger is asked for afterwards, and a row per call is what makes the count
    answerable.
    """
    before = platform_rows()

    for _ in range(3):
        record_zitadel_identity(
            user=member,
            subject="zitadel-subject-ledger-2",
            tenant=None,
            actor=system_actor(tenant=None),
        )

    assert platform_rows() == before + 3


def test_the_subject_never_reaches_the_row(member: User) -> None:
    """`subject` is not in this app's `LOG_KEYS`, so the trail says who, not what."""
    record_zitadel_identity(
        user=member,
        subject="zitadel-subject-ledger-3",
        tenant=None,
        actor=system_actor(tenant=None),
    )

    row = AuditEntry.objects.for_platform().filter(action=ACTION).latest("created_at")
    assert "zitadel-subject-ledger-3" not in str(row.input)


def test_a_real_login_leaves_the_row_the_adapter_path_owes(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """The adapter-driven path, end to end, not the service called by hand.

    `test_rp_login.py` drives allauth's real protocol implementation against a
    real in-process issuer; this asks the one new question of that flow — that
    the identity join it performs is on the record when it is over.
    """
    before = platform_rows()

    sign_in(api)

    assert platform_rows() == before + 1


# --- the refusal is silent, and says so ---------------------------------


@pytest.mark.parametrize(
    ("email", "verified"),
    [("outsider@gmail.example", True), ("insider@union.studio", False)],
    ids=["domain_not_allowed", "email_not_verified"],
)
def test_neither_workforce_refusal_writes_an_audit_row(
    workforce: None, login_request: HttpRequest, email: str, verified: bool
) -> None:
    """A population NON-diff, at BOTH refusal branches.

    The door refused; nothing was written, so nothing is recorded, and
    `@service` stays the one writer of `AuditEntry`. Driven through the adapter
    with the object allauth really hands it, the same way `test_identity_doors`
    drives it — a refusal is a control-flow fact and a stand-in that agreed with
    the code would prove nothing.
    """
    before = AuditEntry.objects.count()

    with pytest.raises(ImmediateHttpResponse) as raised:
        SocialAccountAdapter(login_request).pre_social_login(
            login_request,
            assertion(
                provider=GOOGLE_PROVIDER,
                subject="google-ledger",
                email=email,
                verified=verified,
            ),
        )

    assert raised.value.response.status_code == 403
    assert AuditEntry.objects.count() == before


def test_the_non_audit_is_declared_where_the_refusal_lives() -> None:
    """The declaration, asserted present. An absence nobody wrote down is a bug.

    Pinned on the docstring of the method that refuses, which is where a reader
    who has just found "no audit row" will be standing. The precedent is
    named because that is what makes this a ruling rather than an opinion.
    """
    doc = inspect.getdoc(SocialAccountAdapter._workforce_login) or ""

    assert "same precedent" in doc
    assert "BY DESIGN" in doc
    assert "no audit row" in doc.lower()


def test_the_refusal_still_has_its_structured_log_line() -> None:
    """House rule 19's half of the same ruling: silent in the ledger, not silent.

    Read off the source rather than captured at runtime, because the property is
    that the line EXISTS at both refusal branches — a log assertion at one of
    them proves nothing about the other.
    """
    source = inspect.getsource(SocialAccountAdapter._workforce_login)

    assert source.count('"accounts.workforce.refused"') == 2
    assert 'reason="domain_not_allowed"' in source
    assert 'reason="email_not_verified"' in source
    assert "log.warning" in source
    # And through `core.log`, never a bare `logging.getLogger` (rule 19).
    assert "from apps.core.log import" in inspect.getsource(adapter_module)
