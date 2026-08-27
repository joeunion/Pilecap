"""This app's row in the integrations census, in all three of its worlds.

`apps/core/tests/test_integrations.py` proves the MECHANISM — the walk, the
registry, the four surfaces, the exit codes — against a planted module that
declares a telegraph. This proves the FACT: that `apps/files/integrations.py`
answers "does this deployment have object storage" correctly when there is none,
when there is one that does not answer, and when there is one that does.

**The property that matters most here is the one that is easiest to lose.** A
census row is only worth having if a store that has fallen over produces a ROW
saying so rather than an unreadable seam — `register` raising would be recorded
as "I could not look at what `files` talks to", which is true of the seam and
false of the deployment, and it would take the whole app's declaration out of the
report at exactly the moment somebody is reading it. So every world below asserts
`census().is_readable` as well as the row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from apps.core.integrations import IntegrationStatus, census, declaring_modules
from apps.files import integrations, storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from typing import Any

    from apps.core.integrations import Integration

#: A port nothing listens on. `9` is the discard service and is never bound here,
#: so a connection to it is refused immediately rather than hanging — which is
#: what makes "the store did not answer" a fast test instead of a timeout.
NOWHERE = "http://127.0.0.1:9"


def _storage_row() -> Integration:
    """This app's row out of the live census. Fails loudly if it is not there."""
    report = census()
    assert report.is_readable, [(seam.module, seam.reason) for seam in report.unreadable]
    found = [row for row in report.integrations if row.key == integrations.KEY]
    assert len(found) == 1, [row.key for row in report.integrations]
    return found[0]


def test_the_census_walk_finds_this_module_with_no_list_edited() -> None:
    """The owner's criterion, from this app's side: no list was edited to add it.

    `declaring_modules()` is derived from `get_app_configs()` and a filename. This
    module exists, so it is in the walk; nothing in `apps/core` was told about it.
    """
    assert "apps.files.integrations" in declaring_modules()


def test_a_deployment_with_no_bucket_says_so_and_says_what_to_type(settings: Any) -> None:
    """The fresh-clone world. **The remedy is the half a report is judged on.**"""
    settings.AWS_STORAGE_BUCKET_NAME = ""

    row = _storage_row()

    assert row.status is IntegrationStatus.NOT_CONFIGURED
    assert row.remedy == storage.CONFIGURE_BUCKET_REMEDY
    assert storage.BUCKET_SETTING in row.remedy
    # `declared`, because nothing was contacted: there was nothing to contact.
    assert row.probe == "declared"
    assert row.declared_by == integrations.SOURCE


def test_a_bucket_that_does_not_answer_is_reported_live_and_never_as_configured(
    settings: Any,
) -> None:
    """The world this row exists for: a name in `.env` and nothing behind it.

    A census that read the setting and stopped would call this `configured` — the
    slot is filled, after all — and a deployment would go to production with a
    bucket that was deleted, renamed or moved to another account, with the
    platform's own instrument vouching for it. The probe is what makes the
    difference, and the row says `live` because we really asked.
    """
    settings.AWS_STORAGE_BUCKET_NAME = "a-bucket-nothing-is-listening-for"
    settings.AWS_S3_ENDPOINT_URL = NOWHERE

    row = _storage_row()

    assert row.status is IntegrationStatus.NOT_CONFIGURED
    assert row.probe == "live"
    assert row.remedy == storage.UNREACHABLE_BUCKET_REMEDY


def test_a_store_that_is_down_produces_a_row_and_never_an_unreadable_seam(
    settings: Any,
) -> None:
    """`register` must not raise. The whole app's declaration rides on it.

    An unreadable seam is `manage.py integrations` exit 2 and a report that says
    nothing about object storage — which is the correct answer when a seam is
    broken and the wrong one when the seam worked perfectly and the ANSWER is
    bad news. This is the assertion that keeps the two apart.
    """
    settings.AWS_STORAGE_BUCKET_NAME = "a-bucket-nothing-is-listening-for"
    settings.AWS_S3_ENDPOINT_URL = NOWHERE

    report = census()

    assert report.unreadable == ()
    assert any(row.key == integrations.KEY for row in report.integrations)


def test_a_real_bucket_is_configured_and_the_probe_really_reached_it(bucket: str) -> None:
    """The third world, against the compose MinIO. **An organ test, and it has to be.**

    Everything above proves what the row says when the answer is no. Only a real
    store can prove that `head_bucket` is a probe rather than a call that happens
    to be spelled like one — the same reason `apps/core/health.py`'s readiness
    test reaches the organ instead of asserting about a mock.
    """
    row = _storage_row()

    assert row.status is IntegrationStatus.CONFIGURED
    assert row.probe == "live"
    assert bucket in row.detail
    # A configured row carries no remedy, and the constructor would have refused
    # one that did not on any other status. Asserted from this side too, because
    # a remedy on a healthy row is a report telling somebody to fix nothing.
    assert row.remedy == ""


def test_the_wall_refuses_a_deployment_with_no_object_storage(settings: Any) -> None:
    """`deploy/release.sh --wall` reads `unmet`; this is what it would see.

    Asserted here rather than only in `apps/core` because the wall's whole value
    is that a REAL row reaches it. The census mechanism can be perfect while this
    app declares nothing, and then a production release passes a wall that never
    had an opinion about object storage.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""

    unmet = {row.key for row in census().unmet}

    assert integrations.KEY in unmet


@pytest.mark.parametrize(
    "remedy",
    [storage.CONFIGURE_BUCKET_REMEDY, storage.UNREACHABLE_BUCKET_REMEDY],
)
def test_every_remedy_this_app_prints_is_long_enough_to_be_one(remedy: str) -> None:
    """The registry refuses a remedy shorter than a shrug; this is the pin.

    Both strings live in `apps/files/storage.py` rather than here or in the
    census module, because house rule 48 fences the variable names they contain
    to the seam. A pin on their length is a pin on that arrangement still
    producing sentences.
    """
    assert len(remedy.strip()) > 40
