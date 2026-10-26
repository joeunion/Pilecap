"""`manage.py retire_direct_google_links`: the direct road's leftovers, taken away safely.

The last step of a product's move off the retired direct-allauth Google road.
Every person that road created holds a `SocialAccount(provider="google")`; the
command deletes those rows only once EVERY holder has signed in through Zitadel
(holds a subject in the identity join), and otherwise refuses with exit 2 naming who has not
— deleting nothing, because a template never removes a product's identity rows
silently.
"""

from __future__ import annotations

from io import StringIO

import pytest
from allauth.socialaccount.models import SocialAccount
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.accounts.tests.conftest import join
from apps.core.audit import AuditEntry

pytestmark = pytest.mark.django_db


def _direct_road_person(email: str, *, subject: str | None) -> User:
    person = create_user(email=email, password=None)
    if subject:
        join(person, subject)
    SocialAccount.objects.create(user=person, provider="google", uid=f"google|{email}")
    return person


def test_every_holder_joined_retires_every_direct_link_and_nothing_else() -> None:
    joined = _direct_road_person("a@union.studio", subject="zitadel|a")
    _direct_road_person("b@union.studio", subject="zitadel|b")
    SocialAccount.objects.create(user=joined, provider="zitadel", uid="zitadel|a")
    out = StringIO()

    call_command("retire_direct_google_links", stdout=out)

    assert "retired      2 direct Google link(s)" in out.getvalue()
    assert not SocialAccount.objects.filter(provider="google").exists()
    # The platform's own row is a different road's, and stays.
    assert SocialAccount.objects.filter(provider="zitadel", user_id=joined.pk).count() == 1
    row = AuditEntry.objects.for_platform().filter(action="accounts.retire_direct_google_links")
    assert row.count() == 1 and row.get().outcome == "ok"


def test_one_unjoined_holder_refuses_the_whole_run_naming_them() -> None:
    _direct_road_person("a@union.studio", subject="zitadel|a")
    _direct_road_person("not-yet@union.studio", subject=None)

    with pytest.raises(CommandError) as refused:
        call_command("retire_direct_google_links")

    assert refused.value.returncode == 2
    assert "not-yet@union.studio" in str(refused.value)
    assert SocialAccount.objects.filter(provider="google").count() == 2


def test_the_dry_run_counts_names_and_deletes_nothing() -> None:
    _direct_road_person("a@union.studio", subject="zitadel|a")
    out = StringIO()

    call_command("retire_direct_google_links", "--dry-run", stdout=out)
    assert "would retire  1 direct Google link(s)" in out.getvalue()

    _direct_road_person("not-yet@union.studio", subject=None)
    with pytest.raises(CommandError) as refused:
        call_command("retire_direct_google_links", "--dry-run", stdout=StringIO())
    assert refused.value.returncode == 2
    assert "not-yet@union.studio" in str(refused.value)
    assert SocialAccount.objects.filter(provider="google").count() == 2


def test_nothing_left_behind_is_a_clean_zero() -> None:
    out = StringIO()
    call_command("retire_direct_google_links", stdout=out)
    assert "retired      0 direct Google link(s)" in out.getvalue()
