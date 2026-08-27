"""The compliance trail gets a reader, over both doors.

The absent-answer this closes: ADR core-8 gave
the deployment's own actions a population of their own
(`AuditEntry.objects.for_platform()`), and the only way to read it was to open
a Django shell and type the query. The one population that exists for
compliance was the one population with no door.

Half of that gap was already closed on this tree and this file pins it rather than
rebuilding it: `AuditEntryAdmin` exists, inherits `ReadOnlyModelAdmin` — which
IS a `ServiceModelAdmin`, house rule 21 — and offers no add, change or delete.
The new half is `manage.py audit_tail`.

**The rule-35 clause.** This command's two reads are the two dotted paths house
rule 35's registry already pins, so the command adds no new read shape and the
pinned plan holds unchanged. `test_the_command_adds_no_new_read_shape` asserts
that pairing: a future reader that needs a non-local column has to stop and
re-pin the plan rather than add a join and let the gate discover it.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.admin import AuditEntryAdmin, ServiceModelAdmin
from apps.core.audit import AuditEntry
from apps.core.management.commands import audit_tail
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(tenant: Tenant, other_tenant: Tenant) -> None:
    """A seeded PAIR: rows in a tenant, rows in another, rows in neither."""
    for index in range(3):
        AuditEntry.objects.create(tenant=tenant, action=f"core.here.{index}", door="shell")
    for index in range(2):
        AuditEntry.objects.create(tenant=other_tenant, action=f"core.there.{index}")
    for index in range(4):
        AuditEntry.objects.create(tenant=None, action=f"core.platform.{index}", door="shell")


def _run(*args: str) -> str:
    out = StringIO()
    call_command("audit_tail", *args, stdout=out)
    return out.getvalue()


# --- the two populations, asked for with two different words -----------------


def test_platform_prints_exactly_the_platform_population(seeded: None) -> None:
    """The command's count equals `for_platform()`'s, on a seeded pair."""
    expected = AuditEntry.objects.for_platform().count()
    output = _run("--platform")

    assert expected == 4
    assert output.splitlines()[0] == f"{expected} audit rows (platform)"
    assert len(output.splitlines()) == expected + 1
    for index in range(4):
        assert f"core.platform.{index}" in output


def test_tenant_prints_exactly_that_tenants_population(seeded: None, tenant: Tenant) -> None:
    expected = AuditEntry.objects.for_tenant(tenant).count()
    output = _run("--tenant", tenant.slug)

    assert expected == 3
    assert output.splitlines()[0] == f"{expected} audit rows (tenant {tenant.slug})"
    assert "core.there.0" not in output
    assert "core.platform.0" not in output


def test_the_two_populations_do_not_leak_into_each_other(seeded: None, tenant: Tenant) -> None:
    """`for_tenant(None)` returns nothing by design, and this door does not widen it."""
    assert "core.here.0" not in _run("--platform")
    assert "core.platform.0" not in _run("--tenant", tenant.slug)


def test_the_slug_is_matched_the_way_a_header_would_match_it(seeded: None, tenant: Tenant) -> None:
    assert f"(tenant {tenant.slug})" in _run("--tenant", f"  {tenant.slug.upper()}  ")


# --- refusals ----------------------------------------------------------------


def test_naming_no_population_is_refused() -> None:
    """There is no 'everything' read, so there is no default."""
    with pytest.raises(CommandError):
        call_command("audit_tail")


def test_naming_both_populations_is_refused(tenant: Tenant) -> None:
    with pytest.raises(CommandError):
        call_command("audit_tail", "--platform", "--tenant", tenant.slug)


def test_an_unknown_slug_says_what_a_slug_IS(db: None) -> None:
    with pytest.raises(CommandError, match="X-Tenant header names"):
        call_command("audit_tail", "--tenant", "nope")


def test_a_negative_limit_is_refused(db: None) -> None:
    with pytest.raises(CommandError, match="cannot be negative"):
        call_command("audit_tail", "--platform", "--limit", "-1")


# --- the tail is a tail ------------------------------------------------------


def test_limit_takes_the_newest_rows(seeded: None) -> None:
    """Newest-first is the model's own `Meta.ordering`, which is what the pinned
    indexes serve; the command adds no ordering of its own."""
    output = _run("--platform", "--limit", "2")
    assert output.splitlines()[0] == "2 audit rows (platform)"
    assert "core.platform.3" in output
    assert "core.platform.0" not in output


def test_limit_zero_means_everything(seeded: None) -> None:
    assert _run("--platform", "--limit", "0").splitlines()[0] == "4 audit rows (platform)"


def test_one_row_says_row_and_not_rows(tenant: Tenant) -> None:
    AuditEntry.objects.create(tenant=None, action="core.alone")
    assert _run("--platform").splitlines()[0] == "1 audit row (platform)"


# --- read-only, and no new read shape ----------------------------------------


def test_the_command_writes_nothing(seeded: None, tenant: Tenant) -> None:
    """Reads are not audited — here or anywhere. A trail that recorded its own
    readers would grow faster than the thing it records."""
    before = AuditEntry.objects.count()
    _run("--platform")
    _run("--tenant", tenant.slug)
    assert AuditEntry.objects.count() == before


def test_the_command_adds_no_new_read_shape() -> None:
    """**The rule-35 clause.** The pinned plan holds; nothing here re-pins it.

    Both reads are the dotted paths rule 35's registry already carries —
    `apps.core.audit.AuditEntry.objects.for_tenant` (`index_served` +
    `index_in_plan: auditentry_tenant_created`) and `...for_platform`
    (`no_seq_scan_on` + `index_in_plan: auditentry_platform_created`), both
    authorized by F1b's report. The command therefore may not re-order, may not
    join, and may not read a non-local column — and this test is what makes
    "may not" a fact rather than a comment. A future reader that needs one is a
    stop-and-report: re-pin the plan, do not add the join here.
    """
    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    rules = yaml.safe_load(path.read_text())["rules"]
    registry = next(rule for rule in rules if str(rule["id"]) == "35")["registry"]
    pinned = {
        entry["path"]: entry
        for entry in registry
        if entry["path"].startswith("apps.core.audit.AuditEntry.objects")
    }
    assert set(pinned) == {
        "apps.core.audit.AuditEntry.objects.for_tenant",
        "apps.core.audit.AuditEntry.objects.for_platform",
    }
    assert "auditentry_tenant_created" in str(
        pinned["apps.core.audit.AuditEntry.objects.for_tenant"]
    )
    assert "auditentry_platform_created" in str(
        pinned["apps.core.audit.AuditEntry.objects.for_platform"]
    )

    source = audit_tail.__doc__ or ""
    assert "no `order_by()`" in source
    local = {field.name for field in AuditEntry._meta.concrete_fields}
    assert set(audit_tail.COLUMNS) <= local


def test_a_page_costs_one_statement(seeded: None, django_assert_num_queries: object) -> None:
    """No `select_related`, no attribute hop: the tail is one statement.

    An N+1 in a compliance reader is the shape that makes somebody stop reading
    the trail, and it is the shape a `door` column plus a `tenant.name` would
    have had.
    """
    with django_assert_num_queries(1):  # type: ignore[operator]
        _run("--platform")


# --- the admin half, pinned rather than rebuilt -------------------------------


def test_the_audit_admin_is_a_service_model_admin() -> None:
    """House rule 21: every admin on a scoped model inherits `ServiceModelAdmin`."""
    assert issubclass(AuditEntryAdmin, ServiceModelAdmin)
    assert isinstance(admin.site._registry[AuditEntry], AuditEntryAdmin)


def test_the_audit_admin_offers_no_write_affordance(rf: object) -> None:
    """The S6 class: the screen offers nothing the model would refuse anyway."""
    registered = admin.site._registry[AuditEntry]
    request = rf.get("/admin/")  # type: ignore[attr-defined]
    assert registered.has_add_permission(request) is False
    assert registered.has_change_permission(request) is False
    assert registered.has_delete_permission(request) is False
