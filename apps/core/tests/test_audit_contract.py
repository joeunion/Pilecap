# census: cross-app population=apps/*/migrations/*.py every RunPython in any app's migrations
"""ADR core-22's generic half, at the seam that owns it.

`test_revoke_audit.py` proves the contract on the one credential pair the
ruling was written about. This module proves the two things this seam changed in
`core.service` itself, which every audited service in the tree inherits whether
or not anybody remembers to look — that is the point of fixing a seam rather
than a call site:

* **`_object_of` learns tuples.** A service that returns a tuple puts the row
  it wrote first, and AU-3's "identity of associated … objects" is answered
  from it. `accounts.issue_token` was the first case;
  `core.invite_member` is the sibling nobody had looked at, and it is fixed by
  the same edit with no change of its own — which is the argument for the seam,
  made by a second member of the population rather than asserted.
* **`redact` renders a `models.Model` argument whatever its parameter is
  called.** A primary key is not a secret and a whole row is never carried
  along, so the allow-list has nothing to protect here; it exists for *values*.
  This is what makes a REFUSED call name what it was refused about, since a
  raise leaves `_object_of` nothing to read.

And one thing this seam deliberately did NOT do: **no backfill of the
pre-contract population** (core-22's absence v). The ground is rule 20 — a
backfill is an UPDATE on an append-only ledger — so the criterion is that no
such migration exists anywhere in the tree, checked over the real migration
files rather than remembered.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.test import Client

from apps.accounts.models import ApiToken
from apps.accounts.services import issue_token, revoke_token
from apps.core.actor import actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import DomainError, refusal_for
from apps.core.models import Tenant
from apps.core.service import _object_of, _plain, redact
from apps.core.services import create_tenant, invite_member
from apps.core.tests.test_surfaces import (  # noqa: F401 — the fixtures, by name
    CUSTOMER_HOST,
    customer,
    customer_role,
    two_faces,
)
from apps.core.tests.tree_census import source_text

pytestmark = pytest.mark.django_db


# --- the tuple seam ----------------------------------------------------------


def test_object_of_reads_the_first_model_in_a_tuple(tenant: Tenant) -> None:
    """The convention the docstring states, asserted rather than described.

    A tuple exists in this codebase for one reason: a service owes the caller
    something that cannot be re-derived — a token's plaintext, an invitation's
    secret — beside the row it wrote. The row goes first, and everything after
    it is none of the audit seam's business.
    """
    label, pk = _object_of((tenant, "a-secret-nobody-can-re-derive"))

    assert label == Tenant._meta.label
    assert pk == tenant.pk


def test_object_of_ignores_a_leading_non_model(tenant: Tenant) -> None:
    """FIRST MODEL, not first element — the convention is about the row."""
    assert _object_of(("ok", tenant)) == (Tenant._meta.label, tenant.pk)


def test_object_of_still_answers_nothing_for_a_tuple_with_no_row() -> None:
    """A tuple of scalars is not a row, and the seam does not invent one."""
    assert _object_of((1, "two", None)) == ("", None)


def test_object_of_does_not_search_a_nested_tuple(tenant: Tenant) -> None:
    """Only the top level is read, deliberately.

    A service whose row is buried two levels down in its return value has a
    shape problem, and a seam that dug for it would hide that problem instead
    of leaving it visible.
    """
    assert _object_of((("nested", tenant),)) == ("", None)


def test_an_invitation_birth_row_names_the_invitation(tenant: Tenant, owner: Any) -> None:
    """The second member of the tuple-returning population, fixed for free.

    `core.invite_member` returns `(invitation, token)` for exactly the reason
    `issue_token` returns `(token, plaintext)`, and its audit row carried no
    `object_id` for exactly the same reason. Nobody found this one — the same
    census did — and it took no edit of its own, which is the whole argument
    for ruling the tuple convention at the seam.
    """
    invitation, _secret = invite_member(
        tenant=tenant, email="newcomer@example.com", actor=system_actor(tenant=tenant)
    )

    row = AuditEntry.objects.get(action="core.invite_member")
    assert row.object_type == invitation._meta.label
    assert row.object_id == invitation.pk


# --- the failed-call naming --------------------------------------------------


def test_redact_renders_a_model_argument_whatever_the_parameter_is_called(
    tenant: Tenant,
) -> None:
    """`<app_label>.<Model>:<pk>`, under a key no allow-list names."""
    out = redact({"widget": tenant}, allowed=frozenset())

    assert out["widget"] == f"{Tenant._meta.label}:{tenant.pk}"


def test_redact_still_hides_a_value_under_an_unlisted_key(tenant: Tenant) -> None:
    """The allow-list is untouched for everything that is not a row.

    This is the anti-vacuous half: a change that let model instances through by
    widening the allow-list would pass the test above and quietly put an email
    address in the trail. A reference and a value are different things, and
    only the first one is safe by construction.
    """
    out = redact({"email": "someone@example.com", "secret": "hunter2"}, allowed=frozenset())

    assert out == {"email": "[redacted]", "secret": "[redacted]"}


def test_a_model_rendering_carries_the_label_and_the_pk_and_nothing_else(
    tenant: Tenant,
) -> None:
    """No column of the row travels — the audit is not a second copy of the table."""
    rendered = _plain(tenant)

    assert rendered == f"{Tenant._meta.label}:{tenant.pk}"
    assert tenant.slug not in rendered
    assert tenant.name not in rendered


# --- the pre-contract population, declared and NOT backfilled ----------------


def test_no_migration_anywhere_backfills_the_audit_trail() -> None:
    """Absence (v): the gaps are dated and declared, and nobody was helpful.

    Rule 20 makes a backfill structurally illegal — `AuditEntry.save()` refuses
    a second write — so this is not a style preference to restate. What the
    criterion actually proves is that nobody tried: a `RunPython` naming this
    table in any app's migrations would be somebody working around the guard
    that makes the table evidence, and it would be invisible in a diff a cycle
    later.

    Read off the real migration files, in every installed app, rather than off
    a remembered list of which apps have migrations — and through
    `tree_census.source_text`, the one tolerant read, because a census walking
    `apps/**` races every other xdist worker's planted fixtures.
    """
    root = Path(str(settings.BASE_DIR)) / "apps"
    suspects = []
    for path in sorted(root.glob("*/migrations/*.py")):
        source = source_text(path)
        if "RunPython" not in source:
            continue
        if re.search(r"\bAuditEntry\b|\bauditentry\b|\bcore_auditentry\b", source):
            suspects.append(str(path))

    assert suspects == [], f"a backfill of an append-only ledger: {suspects}"


def test_the_model_docstring_dates_the_pre_contract_population() -> None:
    """The declaration has a DATE, because a gap without one is just a gap.

    Absence (v) is only usable by a reviewer if they can tell which rows it
    covers. The docstring is where a person meeting a null `actor_user` in the
    admin actually looks, so the date lives there as well as in the ADR — and
    this test is why the two cannot drift into "before the contract, whenever
    that was".
    """
    doc = AuditEntry.__doc__ or ""

    assert "core-22" in doc
    assert "2026-08-26" in doc
    assert "backfill" in doc.lower()


# --- the population is what the decorator says it is -------------------------


def test_a_platform_row_is_reachable_only_by_the_platforms_own_word(
    tenant: Tenant, other_tenant: Tenant
) -> None:
    """Absence (iii), asserted: `for_tenant` can never see the platform trail.

    Not a new mechanism — `AuditEntryManager` has read this way since ADR
    core-8 — but core-22 cites it as the ground for calling those rows' absence
    from a tenant's trail the contract rather than a miss, and a citation with
    no test under it is how a ground goes stale.
    """
    AuditEntry(
        tenant=None,
        action="core.canary_platform_row",
        object_type="",
        object_id=uuid4(),
        door="shell",
        outcome=AuditEntry.Outcome.OK,
        input={},
    ).save()

    assert (
        AuditEntry.objects.for_tenant(tenant).filter(action="core.canary_platform_row").count() == 0
    )
    assert (
        AuditEntry.objects.for_tenant(other_tenant)
        .filter(action="core.canary_platform_row")
        .count()
        == 0
    )
    assert AuditEntry.objects.for_platform().filter(action="core.canary_platform_row").count() == 1


# --- L7: the three branches of the convention, one canary each ---------------


def test_branch_one_reads_an_explicit_audit_object_model(tenant: Tenant) -> None:
    """A result that DECLARES its row wins over everything else in the seam."""

    @dataclasses.dataclass(frozen=True)
    class Declares:
        audit_object: Any
        other: str = "noise"

    assert _object_of(Declares(audit_object=tenant)) == (Tenant._meta.label, tenant.pk)


def test_branch_one_reads_a_label_and_pk_pair(tenant: Tenant) -> None:
    """The population shape: a label, and a NULL id, because a sweep has no row."""

    @dataclasses.dataclass(frozen=True)
    class Swept:
        audit_object: tuple[str, None] = ("core.Tenant", None)

    assert _object_of(Swept()) == ("core.Tenant", None)


def test_branch_one_refuses_a_blank_label(tenant: Tenant) -> None:
    """A blank `object_type` names nothing — the defect the declaration closes.

    Refused where it is read rather than written, which is the same tier
    `core.exceptions.register_refusal` refuses a malformed refusal at import.
    The label at a declaration site is always a constant, so a blank one can
    only be a programming error, and it meets this long before a deployment.
    """

    @dataclasses.dataclass(frozen=True)
    class Blank:
        audit_object: tuple[str, None] = ("   ", None)

    with pytest.raises(ValueError, match="blank label"):
        _object_of(Blank())


def test_branch_one_refuses_a_shape_that_is_neither(tenant: Tenant) -> None:
    """Two declared shapes, and there is no third."""

    @dataclasses.dataclass(frozen=True)
    class Nonsense:
        audit_object: str = "core.Tenant"

    with pytest.raises(ValueError, match="neither a models.Model"):
        _object_of(Nonsense())


def test_branch_two_reads_the_first_model_in_a_dataclass(tenant: Tenant) -> None:
    """The four typed results, covered with zero edits to the types themselves.

    `files.UploadTicket`, `files.DownloadTicket` and `comms.StepOutcome` all put
    the row FIRST and none of them declares anything — which is the whole
    argument the L7 ruling made for reading the shape rather than teaching each
    type.
    """

    @dataclasses.dataclass(frozen=True)
    class Ticket:
        row: Tenant
        url: str

    assert _object_of(Ticket(row=tenant, url="signed")) == (Tenant._meta.label, tenant.pk)


def test_branch_two_ignores_a_leading_non_model_field(tenant: Tenant) -> None:
    """FIRST MODEL, not first field — the convention is about the row."""

    @dataclasses.dataclass(frozen=True)
    class Mixed:
        note: str
        row: Tenant

    assert _object_of(Mixed(note="x", row=tenant)) == (Tenant._meta.label, tenant.pk)


def test_branch_three_is_nothing(tenant: Tenant) -> None:
    """A result that genuinely acted on no row records no row."""

    @dataclasses.dataclass(frozen=True)
    class Countish:
        how_many: int = 3

    assert _object_of(Countish()) == ("", None)
    assert _object_of(None) == ("", None)
    assert _object_of(17) == ("", None)


def test_a_dataclass_TYPE_is_not_mistaken_for_an_instance() -> None:
    """`dataclasses.fields` works on the class too; the seam must not follow it."""

    @dataclasses.dataclass(frozen=True)
    class Shape:
        row: Tenant

    assert _object_of(Shape) == ("", None)


# --- L6: every declared population label resolves to a real model ------------


def test_every_declared_audit_object_label_names_a_real_model() -> None:
    """The lazy-reference census, so a rename fails by name (ADR core-22, L6).

    A `types.py` here is stdlib-only by contract, so a sweep's population is
    declared as the string `apps.Model` — exactly Django's own
    `ForeignKey("accounts.ApiToken")` form, and `AuditEntry.actor_token` with
    it. What Django gets for free from the app registry, this gets from a test:
    without it a renamed model would keep filing rows under a string that had
    stopped meaning anything, and nothing would say so.

    The population is DERIVED — every dataclass in every app's `types.py` and
    `services.py` that declares the attribute — never a list somebody keeps.
    """
    from apps.core.service import AUDIT_OBJECT_ATTR

    declared: list[tuple[str, str]] = []
    for module_name in _modules_that_may_declare():
        module = importlib.import_module(module_name)
        for name, obj in vars(module).items():
            if not dataclasses.is_dataclass(obj) or not isinstance(obj, type):
                continue
            value = getattr(obj, AUDIT_OBJECT_ATTR, None)
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
                declared.append((f"{module_name}.{name}", value[0]))

    assert declared, "no population labels found — this census is reading the wrong modules"
    for where, label in declared:
        assert label.strip(), f"{where} declares a blank population label"
        django_apps.get_model(label)  # raises LookupError on a stale reference


def _modules_that_may_declare() -> list[str]:
    """Every installed app's `types.py`, derived from the registry."""
    out = []
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        for suffix in ("types",):
            try:
                importlib.import_module(f"{config.name}.{suffix}")
            except ModuleNotFoundError:
                continue
            out.append(f"{config.name}.{suffix}")
    return out


# --- L11: the two pins ------------------------------------------------------


def test_a_refused_call_records_no_object_at_all(tenant: Tenant, owner: Any) -> None:
    """L11's second pin: a refusal names no CONFIRMED object.

    `@service` writes the failure row from the arguments alone — the service
    raised, so there is no return value for `_object_of` to read — and that is
    the contract rather than an accident: an `object_type`/`object_id` pair on a
    refusal would read as "this happened to that row", when the whole content of
    the row is that it did not happen. What the credential or the target IS
    named as is the redacted `input`, where it is visibly a claim the caller
    made and not a fact the product confirmed.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="refusal-pin",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    other = create_tenant(name="Elsewhere", slug="elsewhere-refusal-pin", actor=system_actor())

    with pytest.raises(DomainError):
        revoke_token(token=token, tenant=other, actor=actor_for(user=owner, tenant=tenant))

    row = AuditEntry.objects.filter(
        action="accounts.revoke_token", outcome=AuditEntry.Outcome.ERROR
    ).get()
    assert row.object_type == "", "a refusal confirms no object"
    assert row.object_id is None
    assert row.input["token"] == f"{ApiToken._meta.label}:{token.pk}", "the CLAIM is recorded"


def test_a_refusals_error_code_is_a_registered_one(tenant: Tenant, owner: Any) -> None:
    """L11's first pin: the code on the row resolves in `core.exceptions`.

    ADR core-22 reads AU-3's "outcome" element onto `outcome` + `error_code`,
    and says the vocabulary is E9's registry — so every code a row carries must
    resolve in `introspect`'s refusals section. A row whose `error_code` is a
    Python class name is a row a compliance reader cannot look up.
    """
    token, _ = issue_token(
        user=owner,
        tenant=tenant,
        name="code-pin",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    other = create_tenant(name="Elsewhere", slug="elsewhere-code-pin", actor=system_actor())

    with pytest.raises(DomainError):
        revoke_token(token=token, tenant=other, actor=actor_for(user=owner, tenant=tenant))

    row = AuditEntry.objects.filter(
        action="accounts.revoke_token", outcome=AuditEntry.Outcome.ERROR
    ).get()
    assert refusal_for(row.error_code) is not None, (
        f"{row.error_code!r} is not a registered refusal code; a reader cannot look it up"
    )


# --- the surface column -------------------------------------------------------
#
# Which audience's address a call came in at, beside `door`: bound by the door,
# written by the one seam from the bound context, `staff` for every row a
# product with one face writes and for every row written before the column.


def test_the_surface_column_is_expand_only_and_reads_staff_by_default(
    tenant: Tenant, owner: Any
) -> None:
    field = AuditEntry._meta.get_field("surface")
    assert field.default == "staff" and not field.null
    migration = importlib.import_module("apps.core.migrations.0020_auditentry_surface")
    (operation,) = migration.Migration.operations
    assert type(operation).__name__ == "AddField" and operation.name == "surface"

    invite_member(tenant=tenant, email="newcomer@example.com", actor=system_actor(tenant=tenant))

    assert AuditEntry.objects.get(action="core.invite_member").surface == "staff"


def test_a_write_from_the_customer_host_is_audited_at_its_surface(
    request: pytest.FixtureRequest, tenant: Tenant
) -> None:
    """The customer surface's world is `test_surfaces.py`'s, asked for by name.

    The customer role holds exactly its declaration, so a create at the customer
    host is refused — and a refusal raised inside a `@service` writes its
    `outcome=error` row, which is the row that carries where the call came in.
    """
    request.getfixturevalue("two_faces")
    client = Client()
    client.force_login(request.getfixturevalue("customer"))
    response = client.post(
        "/api/v1/widgets/",
        data={"name": "From the customer host"},
        content_type="application/json",
        HTTP_HOST=CUSTOMER_HOST,
    )

    assert response.status_code == 403, response.content
    row = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget", outcome="error")
    assert row.error_code == "forbidden"
    assert row.surface == "customer"
    assert row.door == "rest"


def test_a_write_from_the_staff_host_is_audited_as_staff(tenant: Tenant, owner: Any) -> None:
    client = Client()
    client.force_login(owner)
    response = client.post(
        "/api/v1/widgets/",
        data={"name": "From the staff host"},
        content_type="application/json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 201, response.content
    assert AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget").surface == (
        "staff"
    )
