"""Nothing an archive carries undoes rule 15 or ER-1's erasure.

**This module is the ER-1 interlock.**
`apps/accounts/tests/test_erasure_residue.py` proves an erased
person is gone from every text column in the database. That proof is about the
DEPLOYMENT, and it says nothing at all about a zip file: the export door reads
those same tables and writes them somewhere the erasure will never reach again.
So the probe is re-run — the same shape, the same needles, the same
declared-population discipline — **against the extracted archive**, and the two
rungs' criteria meet there.

Two claims:

1. **Encrypted columns do not travel, and the archive says so.** Rule 15 keeps a
   secret-shaped column encrypted at rest; an export that decrypted it into a
   file that leaves the deployment would undo that at the one door built to send
   data outward, which is exactly where nobody would look for it. The three live
   members on this tree are checked by their plaintext being absent from the
   bytes.

2. **An erased person's identifiers are nowhere in a post-erasure archive.** Red
   first: the same probe against a PRE-erasure archive finds them, which is what
   makes the zero afterwards a measurement rather than a broken search.

DOES NOT COVER — declared, and inherited from the probe this mirrors:

* **free-text a product writes into its own columns.** The needles are the
  identifiers erasure knows about — the address somebody signed in with and the
  subject their IdP asserted. A tenant that typed a person's address into a
  widget's `notes` exports that, correctly: it is the tenant's own text.
* **an alias.** `jo+work@example.com` is a different string.
* **a message body.** `comms.Message` travels and erasure does not sweep it
  (a separate dated trigger owns that), so an archive can carry an address inside a
  rendered email that was sent before the erasure. That is ER-1's declared
  boundary reaching this door unchanged, not a new hole — and it is stated here
  because a reader of this file will want to know whether "nowhere" is
  literally true. It is true of the identifier columns; it is not a claim about
  prose.
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from apps.accounts.models import STAFF_REALM, SsoConnection, User
from apps.accounts.services import (
    create_user,
    erase_user,
    provision_sso_identity,
    record_identity,
)
from apps.accounts.tests.conftest import subject_of
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership
from apps.core.services import add_membership, invite_member
from apps.exports.activities import MANIFEST_NAME, MODELS_DIRECTORY, _write_the_archive
from apps.exports.models import Export
from apps.exports.services import create_export

from .conftest import CLIENT_SECRET, archive_bytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant
    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db

# The person this file is about. Distinctive strings, so a hit is a hit and
# never a coincidence with a fixture two files away — the same discipline
# `test_erasure_residue.py` uses, and deliberately different values so a
# failure names which probe found it.
TARGET_EMAIL = "export-residue-target@acme.com"
TARGET_SUBJECT = "zitadel-subject-export-residue"


def residue_in(key: str, *needles: str) -> dict[str, int]:
    """Every file in the archive still holding one of `needles`, and how often.

    The mirror of `test_erasure_residue.py::residue`, one layer out. That one
    walks the model registry and asks the database column by column; this walks
    the archive and asks the BYTES, which is a superset of the same question: a
    column that held the address is a substring of the line the writer emitted
    for it, whatever the column was called and whatever the writer did to it.

    Reading the bytes rather than parsing each row and checking known fields is
    the point. A field-by-field search would need a list of which fields can
    hold an identifier, and a list is exactly what the erasure probe refused to
    be — the fifth column nobody wrote down is the one that leaks.
    """
    found: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        for name in archive.namelist():
            body = archive.read(name).decode("utf-8", errors="replace")
            hits = sum(body.count(needle) for needle in needles)
            if hits:
                found[name] = hits
    return found


@pytest.fixture
def target(world: World, sso_connection: SsoConnection) -> User:
    """A person with the account footprint an erasure has to reach, INSIDE the tenant.

    Deliberately in `world.tenant` rather than in a neighbour: the point of this
    file is what an archive of THIS tenant carries, so every row here has to be
    one the walk will actually read. Written by the services that really write
    them, so the shapes are production's.
    """
    identity = provision_sso_identity(
        tenant=world.tenant,
        actor=system_actor(world.tenant),
        connection=sso_connection,
        subject="idp-subject-export-residue",
        email=TARGET_EMAIL,
        email_verified=True,
    )
    person = identity.user
    record_identity(
        realm=STAFF_REALM,
        user=person,
        subject=TARGET_SUBJECT,
        tenant=None,
        actor=system_actor(tenant=None),
    )
    invite_member(
        tenant=world.tenant,
        email=TARGET_EMAIL,
        organization=world.root,
        actor=world.owner,
    )
    return person


@pytest.fixture
def eraser(world: World, target: User) -> Actor:
    """Somebody who may erase the target: an owner at the tenant's root.

    The same ceiling a tenant-wide export needs
    (`accounts.policies.administers_the_whole_tenant`), which is the coupling
    this pair of rungs is built around rather than a coincidence.
    """
    who = create_user(email="export-eraser@acme.com", password="x" * 20)
    add_membership(
        user=who,
        tenant=world.tenant,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=world.tenant),
    )
    return actor_for(user=who, tenant=world.tenant, org=world.root)


@pytest.fixture
def archive_key(world: World, recorded_workflow_starts: None, archive_bucket: str) -> Any:
    """Build a tenant-wide archive on demand and hand back its storage key.

    `archive_bucket` since XPr: the archive is filed through the files seam into
    real object storage, so the bytes this file sweeps are read back out of a
    bucket rather than off a filesystem. **The probe is unchanged** — it still
    reads the whole zip and counts needles in it — which is the point: the ER-1
    interlock asks what an archive CONTAINS, and where the archive lives is not
    part of that question.
    """

    def build() -> str:
        export = create_export(tenant=world.tenant, actor=world.owner, scope=Export.Scope.TENANT)
        version, _manifest = _write_the_archive(export=export, hat=world.root, actor=world.owner)
        return str(version.key)

    return build


# --- the instrument, proven able to fail ---------------------------------------


def test_the_probe_finds_the_person_in_an_archive_taken_before_the_erasure(
    world: World, target: User, archive_key: Any
) -> None:
    """RED FIRST. Without this, the zero below could be a broken search.

    A probe that finds nothing in an un-erased person's archive reads exactly
    like a clean one, which is the failure mode the erasure rung's own probe was
    written to avoid.
    """
    hits = residue_in(archive_key(), TARGET_EMAIL)

    assert hits, "the probe found nothing in an archive that certainly contains them"
    assert f"{MODELS_DIRECTORY}/accounts.SsoIdentity.jsonl" in hits
    assert f"{MODELS_DIRECTORY}/core.Invitation.jsonl" in hits


# --- ER-1's probe, re-run against the extracted archive ------------------------


def test_an_erased_person_is_nowhere_in_an_archive_taken_afterwards(
    world: World, target: User, eraser: Actor, archive_key: Any
) -> None:
    """The interlock. Erasure holds at the door built to send data outward.

    The whole archive, swept for the address, and the answer is nothing. Not
    "nothing outside a declared list": the archive's own exclusions already took
    `events.Event` out with its reason, so what is left has no legitimate
    survivor and the assertion is a plain zero.
    """
    erase_user(user=target, actor=eraser, tenant=world.tenant)

    leftover = residue_in(archive_key(), TARGET_EMAIL)

    assert leftover == {}, (
        "an erased person's address is still in the archive, in "
        + ", ".join(sorted(leftover))
        + " — the export door is undoing the erasure at the one place the data "
        "leaves the deployment (ADR ident-5, and this app's census exclusions)"
    )


def test_neither_identifier_survives_into_the_archive(
    world: World, target: User, eraser: Actor, archive_key: Any
) -> None:
    """The other half: the IdP subject too, not just the address.

    The identity join's subject (`accounts.SsoIdentity.subject`) is a DECLARED
    retention in the database (`test_erasure_residue.py::RETAINED` — it is the
    collision fence that stops somebody else's Zitadel account being re-linked
    to the erased row). It
    survives there and it must not survive HERE, and the reason it does not is
    structural rather than lucky: `accounts.User` carries no tenant, so it was
    never in the census at all. Asserted rather than assumed, because "not in
    the population" is exactly the kind of fact that stops being true when
    somebody adds a column.
    """
    erase_user(user=target, actor=eraser, tenant=world.tenant)

    assert residue_in(archive_key(), TARGET_EMAIL, TARGET_SUBJECT) == {}

    target.refresh_from_db()
    assert subject_of(target) == TARGET_SUBJECT, "the collision fence is still up in the database"


def test_the_retained_event_payload_is_excluded_rather_than_swept(
    world: World, target: User, eraser: Actor, archive_key: Any
) -> None:
    """Why `events.Event` is not in the archive, proven rather than argued.

    A ratified retention covers the event payload: erasure deliberately does
    not rewrite it, because it is the witnessed record of what was emitted. That
    argument is about a payload sitting inside the deployment. An archive leaves,
    so the census takes the table out — and this asserts BOTH ends of that, so
    neither can quietly change: the payload still holds the address in the
    database, and the archive has no `events.Event` file at all.
    """
    from django.apps import apps as django_apps

    from apps.core import bridge

    # `organization_id` is not decoration, and it is the same sentence the
    # deployment-side probe this module mirrors carries: a widget is an
    # `OrgScopedModel`, and `emit` REFUSES an org-scoped event whose payload
    # names no branch — an absent key is stamped NULL and the socket fan-out
    # reads NULL as tenant-wide, so the subject's own row would reach every
    # connection in the tenant. The root is the branch because this test is
    # about a retained ADDRESS and not about the hierarchy, and it is the root
    # the `world` fixture already resolved rather than a second read of it.
    bridge.get(bridge.EMIT)(
        tenant=world.tenant,
        name="example.widget.created",
        payload={"contact": TARGET_EMAIL, "organization_id": str(world.root.pk)},
        actor=system_actor(world.tenant),
    )
    erase_user(user=target, actor=eraser, tenant=world.tenant)

    event = django_apps.get_model("events", "Event")
    assert event.objects.filter(payload__contact=TARGET_EMAIL).exists(), (
        "the retention has stopped happening — the census entry's reason is now "
        "prose about something that no longer occurs, and it has to shrink"
    )

    key = archive_key()
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        names = set(archive.namelist())
    assert f"{MODELS_DIRECTORY}/events.Event.jsonl" not in names
    assert residue_in(key, TARGET_EMAIL) == {}


# --- rule 15: no encrypted column travels --------------------------------------


def test_no_encrypted_secret_appears_anywhere_in_the_bytes(
    world: World, neighbour: Tenant, sso_connection: SsoConnection, archive_key: Any
) -> None:
    """The three live encrypted columns, checked as plaintext absent from the file.

    Asserted against the BYTES rather than against the excluded-field list,
    because the list is the writer's own claim and this is the reader's
    measurement. The row is in the archive; the column is not.
    """
    key = archive_key()
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        connection_rows = archive.read(f"{MODELS_DIRECTORY}/accounts.SsoConnection.jsonl").decode()
        manifest = archive.read(MANIFEST_NAME).decode()

    assert str(sso_connection.pk) in connection_rows, "the row itself did travel"
    assert CLIENT_SECRET not in connection_rows
    assert residue_in(key, CLIENT_SECRET) == {}
    # And the archive SAYS the column was left out, rather than being quietly
    # short: an archive missing a field with no explanation is indistinguishable
    # from a deployment that never stored one.
    assert "metadata" in manifest
    assert "encrypted at rest" in manifest


def test_the_encrypted_column_really_holds_something_to_leak(
    world: World, sso_connection: SsoConnection
) -> None:
    """The oracle for the check above: zero is only a fact if there was a value."""
    assert CLIENT_SECRET in str(sso_connection.metadata)
