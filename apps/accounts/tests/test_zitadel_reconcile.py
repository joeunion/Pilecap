"""`manage.py zitadel_reconcile` — the audit's read, and the ask that closes it.

**Why there is a second command and not a flag on the first.** `zitadel_audit`
is read-only, and that is a property its own tests hold it to: every call it
makes is a `GET` or a `_search`, and the instance is byte-identical afterwards.
A `--repair` flag on it would put a writing path inside the one command a deploy
step and a cron line already trust to change nothing. So the reconciler is its
own door, it reads through the audit's own section functions — one read, not two
— and it prints the audit's lines before it prints a single ask.

**What it may ask for, and what it may not.** The ownership table in the
command's docstring is the whole of it: one entry per identity fact, saying who is
authoritative, why a copy exists, which way a disagreement is settled, and what
kind of ask closes it. A fact with no `kind` is a fact this command prints and
never touches — the instance's SMTP sender, the org's other login-policy fields,
the organisation count, a person's identity join. The test below is what keeps
the table and the code from drifting apart.

**The ask is a service call, never a management call.** House rules 10 and 27
both: the reconciler is a shell door, so it calls a service, the service writes
the intent and starts a run on commit, and the run's activity is the only thing
that reaches Zitadel. That is what makes `--dry-run` cheap to be sure of — there
is no write to suppress, only an ask not to make — and it is why a reconcile
that finds ten disagreements leaves ten runs behind rather than ten management
calls inside one transaction (principle 8).

**The digest that makes a repair askable at all.** A run's id is deterministic
(house rule 18), so asking twice for the same intent is one run — which is
exactly right until the thing that changed is not our intent but Zitadel's copy
of it. Then the intent is byte-identical, the key is byte-identical, the run has
already completed, and `record_run` refuses the ask as a repeat. The
reproduction is `test_a_re_ask_under_the_same_key_is_the_conflict_it_always_was`.
`observed` is the way out: the reconciler hands the service what it SAW, that
goes into the key, and a different observation is a different run while the same
observation twice is still one.

Nothing here dials Zitadel or Temporal: `FakeZitadel` is the socket (ADR
ident-5(a)), and `instance` brings `recorded_workflow_starts`, so the
`WorkflowRun` row is written and the client call is not. The live end-to-end —
a real instance, a real worker, a real repaint — is the verifier's hand run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import services
from apps.accounts import zitadel as zitadel_module
from apps.accounts.management.commands import zitadel_reconcile
from apps.accounts.management.commands.zitadel_audit import (
    APPLICATIONS_KIND,
    IDENTITY_HOME_KIND,
    LOGIN_CLIENT_KIND,
)
from apps.accounts.models import IdentityBranding, SsoConnection, User
from apps.accounts.services import IDENTITY_HOME_WORKFLOW
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.tests.test_identity_branding import LabelPolicy
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
)
from apps.core.actor import Actor, actor_for
from apps.core.models import Tenant
from apps.workflows.models import WorkflowRun


# The project name this deployment declares, READ rather than typed. It
# defaults to `PRODUCT_NAME` and a checkout that seeds a project of its own —
# which is the road `.env.example` prints for a second checkout, and the road
# every rung in lane A is proven on — sets `ZITADEL_PROJECT_NAME` to something
# else. Four cases below used to spell the default, and on exactly those
# checkouts they failed: a platform test that reds because the operator
# followed the operator's instructions. Same shape as F14, different key.
def _declared_project() -> str:
    return str(django_settings.ZITADEL_PROJECT_NAME)


pytestmark = pytest.mark.django_db(transaction=True)

WORKFORCE_DOMAIN = "union.studio"


# --- the world these cases are set in ----------------------------------------


@pytest.fixture
def label(instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch) -> LabelPolicy:
    """`FakeZitadel` plus the label-policy routes, so a screen can be repainted.

    The state machine itself is `test_identity_branding.LabelPolicy`, imported
    rather than copied: its answer shapes were MEASURED off the pinned build,
    including the `PUT`-with-no-change refusal, and a second copy here would be
    a second set of measurements to keep in step with somebody else's. The
    routing is written out because a fixture is not importable and this is the
    honest way to say which paths this module's world answers.
    """
    surface = LabelPolicy()
    original: Callable[[str, str, dict[str, Any]], dict[str, Any]] = instance._route

    def routed(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "/policies/label":
            if not surface.readable:
                raise KeyError(path)
            if method == "GET":
                return surface.answer()
            if method in ("POST", "PUT"):
                surface.custom = dict(body)
                surface.sequence += 1
                return {"details": {"sequence": str(surface.sequence)}}
        if method == "POST" and path == "/policies/label/_activate":
            surface.activated = True
            surface.sequence += 1
            return {"details": {"sequence": str(surface.sequence)}}
        return original(method, path, body)

    monkeypatch.setattr(instance, "_route", routed)
    return surface


@pytest.fixture
def operator(db: None, tenant: Tenant, owner: User) -> Actor:
    """Somebody who may configure the deployment's identity platform.

    A superuser, because `identity_platform.configure` is a platform operator's
    permission and not a tenant owner's — the deployment's own sign-in screen is
    not one customer's to repaint (`apps/accounts/policies.py`).
    """
    owner.is_superuser = True
    owner.save(update_fields=["is_superuser"])
    return actor_for(user=owner, tenant=tenant)


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment whose workforce door is configured — both halves."""
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]


@pytest.fixture
def posture_open(instance: FakeZitadel) -> FakeZitadel:
    """One of the three sign-in doors back open, as a console edit leaves it.

    `conftest.instance` closes all three so that every other identity test's
    audit is about its own subject; this puts one back, which is the state a
    posture drift actually is. The road out of it is `zitadel_seed`, and that is
    exactly why this case exists here — it is the delta the reconciler prints
    and does not close.
    """
    instance.restrictions.pop("disallowPublicOrgRegistration", None)
    return instance


def _branded(operator: Actor, accent: str = "#3f4a5a") -> IdentityBranding:
    """A stated intent, materialised — the state a console edit can then break."""
    from apps.accounts.activities import apply_identity_config
    from apps.accounts.types import IdentityConfigSync

    row = services.set_identity_branding(actor=operator, tenant=None, accent=accent)
    apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)))
    row.refresh_from_db()
    return row


def _run(capsys: Any, *args: str, expect_exit: int = 0) -> str:
    """Run the reconciler, assert the exit status, return what it printed.

    Three exits and three shapes, so the helper cannot quietly accept the wrong
    one: 0 is an ordinary return, 1 is the `SystemExit` the audit already uses
    for "the report said everything", and 2 is a `CommandError` carrying
    `returncode=2` — the could-not-look class, which is the one an automated
    caller must be able to tell from a disagreement.
    """
    capsys.readouterr()
    if expect_exit == 0:
        call_command("zitadel_reconcile", *args)
    elif expect_exit == 1:
        with pytest.raises(SystemExit) as exit_info:
            call_command("zitadel_reconcile", *args)
        assert exit_info.value.code == 1
    else:
        with pytest.raises(CommandError) as error_info:
            call_command("zitadel_reconcile", *args)
        assert error_info.value.returncode == 2
    return str(capsys.readouterr().out)


def _audit(capsys: Any, *, expect_exit: int = 0) -> str:
    capsys.readouterr()
    if expect_exit == 0:
        call_command("zitadel_audit")
    else:
        with pytest.raises(SystemExit) as exit_info:
            call_command("zitadel_audit")
        assert exit_info.value.code == expect_exit
    return str(capsys.readouterr().out)


def _platform_runs() -> list[WorkflowRun]:
    """The platform runs this module's asks start — never a tenant's realm, asked at its birth."""
    return list(
        WorkflowRun.objects.for_platform()
        .exclude(type=IDENTITY_HOME_WORKFLOW)
        .order_by("created_at")
    )


# --- I3.1 · the ownership table is in the tree -------------------------------


def test_the_ownership_table_names_every_kind_the_command_repairs(
    instance: FakeZitadel,
) -> None:
    """Principle 9, as a thing that can fail rather than a paragraph.

    Every fact this command can ask about has a row saying who owns it, why the
    copy exists, how a disagreement is settled and how staleness is noticed. The
    table is in the command's own docstring rather than in a document, because a
    reader deciding whether to run this is reading `--help`, and because a table
    a test can read is a table that cannot quietly stop describing the code.

    The SMTP row is named explicitly: it is the fact that decides who every
    identity mail on this instance comes from, it is the one this deployment
    states NO intent for, and a table that dropped it would be a table that had
    gone back to calling somebody else's sender agreement.
    """
    table = zitadel_reconcile.__doc__ or ""

    for kind in zitadel_reconcile.REPAIRED_KINDS:
        assert f"`{kind}`" in table, kind
    assert "smtp" in table.lower()
    # And the two the table declares OUT of this command's reach are in it as
    # rows rather than as absences: a fact with no row is indistinguishable
    # from a fact nobody thought about.
    assert "identity join" in table
    assert "applications" in table


def test_every_repaired_kind_is_either_a_run_or_the_declared_seed_road(
    instance: FakeZitadel,
) -> None:
    """Two roads exist and every repaired kind is on exactly one of them.

    Three kinds are asks: a service writes the intent and
    `SyncIdentityConfigWorkflow` materialises it, so their kind has to be a
    member of `types.py`'s vocabulary or the dispatch would refuse it by name —
    inside a run, where nobody is watching, rather than at the door. The other
    two have no row and no service: their declared values are settings and the
    design, the seed's writers are the one door onto both, so they are on the
    seed road and deliberately NOT in that vocabulary.

    A tenant's realm is a third road: its run is `EnsureTenantIdentityHomeWorkflow`
    rather than the configuration sync, so its kind is the audit's own spelling
    and not `types.py`'s, and its ask is `services.start_identity_home`.

    Asserted as a partition rather than as a list, because the failure this
    catches is a kind added to `REPAIRED_KINDS` with no road behind it at all.
    """
    assert set(zitadel_reconcile.REPAIRED_KINDS) == {
        IDENTITY_HOME_KIND,
        KIND_SSO_CONNECTION,
        KIND_WORKFORCE_PROVIDER,
        KIND_IDENTITY_BRANDING,
        APPLICATIONS_KIND,
        LOGIN_CLIENT_KIND,
    }
    runs = set(zitadel_reconcile.REPAIRED_KINDS) - set(zitadel_reconcile.SEED_ROAD_KINDS)
    assert runs == {
        IDENTITY_HOME_KIND,
        KIND_SSO_CONNECTION,
        KIND_WORKFORCE_PROVIDER,
        KIND_IDENTITY_BRANDING,
    }
    assert set(zitadel_reconcile.SEED_ROAD_KINDS) == {APPLICATIONS_KIND, LOGIN_CLIENT_KIND}
    assert not {APPLICATIONS_KIND, LOGIN_CLIENT_KIND} & {
        KIND_SSO_CONNECTION,
        KIND_WORKFORCE_PROVIDER,
        KIND_IDENTITY_BRANDING,
    }


# --- I3.2 · one read, not two ------------------------------------------------


def test_the_reconcile_prints_the_audits_own_lines_for_a_drifting_kind(
    label: LabelPolicy, operator: Actor, capsys: Any
) -> None:
    """The same sentence, byte for byte, out of both commands.

    Two readers of one instance that phrase what they saw differently is two
    tripwires to keep in step, and the one that drifts is the one nobody runs
    weekly. So the audit's sections ARE the reconciler's read: the line below is
    produced once, by one function, and printed by both.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"

    audited = _audit(capsys, expect_exit=1)
    reconciled = _run(capsys, "--dry-run", expect_exit=1)

    drift_line = next(line for line in audited.splitlines() if line.startswith("DRIFT"))
    assert "sign-in branding" in drift_line
    assert drift_line in reconciled.splitlines()


def test_the_reconcile_prints_the_blind_spot_paragraph_too(
    instance: FakeZitadel, capsys: Any
) -> None:
    """What a clean verdict does not cover is what a clean REPAIR does not cover.

    The paragraph is the audit's, and it is at least as load-bearing here: a
    person who has just watched this command fix three things is the person most
    likely to believe it saw everything.
    """
    out = _run(capsys)

    assert "does not cover" in out
    assert "House rule 27 fences this codebase. It cannot fence the console." in out


# --- I3.3 · the observed digest moves the key, and only the key --------------


def test_a_re_ask_under_the_same_key_is_the_conflict_it_always_was(
    label: LabelPolicy, operator: Actor
) -> None:
    """The reproduction `observed` exists to route around, pinned as a property.

    A reconciler re-asks for an intent nobody changed, so its key is the key the
    finished run already wore and `record_run` refuses it: "running the same
    work again is a new job, not a repeat of that one". That refusal is right in
    general — re-running landed work IS a decision about a new key — and it is
    what made a repairer impossible to write at all before `observed`, because on the
    baseline the branding service had no way to be asked about a standing row at
    all: it superseded, so the ask carried a new primary key and was a different
    question.

    Both halves are here. The refusal is INTACT under an unchanged key, which is
    what keeps the digest from being a way around the family's own discipline;
    and the next observation gets its own run.
    """
    from apps.core.exceptions import Conflict

    row = _branded(operator)
    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-A")
    landed = WorkflowRun.objects.for_platform().get(
        workflow_id__endswith=services._branding_run_key(row, observed="saw-A")
    )
    landed.status = WorkflowRun.Status.COMPLETED
    landed.save(update_fields=["status"])

    with pytest.raises(Conflict):
        services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-A")

    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-B")
    assert (
        WorkflowRun.objects.for_platform()
        .filter(workflow_id__endswith=services._branding_run_key(row, observed="saw-B"))
        .exists()
    )


def test_an_empty_observation_leaves_every_key_byte_identical(
    label: LabelPolicy, workforce: None, operator: Actor, sso_connection: SsoConnection
) -> None:
    """The default is the old behaviour, for all three services, exactly.

    `observed=""` is what every existing caller passes by not passing it —
    `zitadel_brand`, `sync_workforce_idp`, `create_sso_connection`'s
    materialisation — so the key it builds has to be the key those callers have
    always built. Asserted by building each key both ways rather than by pinning
    a literal, which would pass the day the key changed shape on both sides.
    """
    row = services.set_identity_branding(actor=operator, tenant=None, accent="#123456")

    assert services._with_observed("anything", "") == "anything"
    assert services._branding_run_key(row, observed="") == services._branding_run_key(row)
    assert services._identity_config_key(sso_connection, observed="") == (
        services._identity_config_key(sso_connection)
    )
    assert services._workforce_config_key(observed="") == services._workforce_config_key()


def test_the_same_observation_twice_is_one_run(label: LabelPolicy, operator: Actor) -> None:
    """Idempotence survives the digest: one drift asked about twice is one ask.

    This is the property principle 16 buys — a reconciler is exactly the kind of
    thing an operator runs twice in a minute because they were not sure the
    first one took.
    """
    row = _branded(operator)
    before = len(_platform_runs())

    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-A")
    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-A")

    assert len(_platform_runs()) == before + 1


def test_a_different_observation_is_a_second_run(label: LabelPolicy, operator: Actor) -> None:
    """And a drift that changed since last time is a different question.

    Without this the second console edit of the week would be refused as a
    repeat of the first, which is the failure `observed` exists to end.
    """
    row = _branded(operator)
    before = len(_platform_runs())

    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-A")
    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="saw-B")

    assert len(_platform_runs()) == before + 2


def test_a_changed_branding_row_is_a_new_run_without_any_observation(
    label: LabelPolicy, operator: Actor
) -> None:
    """The key says WHICH INTENT this is, and that half owes nothing to `observed`.

    `set_identity_branding` supersedes rather than overwrites, so a second call
    with different colours is a second intent — and it gets its own run because
    the key carries a digest of the stated fields, the same shape
    `_identity_config_key` has always carried.
    """
    first = services.set_identity_branding(actor=operator, tenant=None, accent="#111111")
    second = services.set_identity_branding(actor=operator, tenant=None, accent="#222222")

    keys = {run.workflow_id for run in _platform_runs()}
    assert len(keys) == 2
    assert services._branding_run_key(first) != services._branding_run_key(second)


def test_the_observation_never_reaches_the_workflow_id_in_the_clear(
    label: LabelPolicy, operator: Actor
) -> None:
    """A digest, not the sentence — the same discipline the client secret gets.

    An observed line names whatever Zitadel answered, and Temporal's history is
    not the place for an unbounded string somebody else's console wrote.
    """
    row = _branded(operator)

    services.set_identity_branding(
        actor=operator, tenant=None, branding=row, observed="DRIFT  primaryColor: #ff00ff"
    )

    ids = [run.workflow_id for run in _platform_runs()]
    assert not any("#ff00ff" in one for one in ids), ids
    assert not any(" " in one for one in ids), ids


# --- I3.4 · the state table, driven, with and without --dry-run --------------


def test_an_agreeing_instance_asks_for_nothing(
    label: LabelPolicy, operator: Actor, seeded: FakeZitadel, capsys: Any
) -> None:
    """The negative the whole command is measured against.

    Every other case here plants a disagreement. Without this one, a reconciler
    that asked for every kind on every run would pass all of them.

    The world is SEEDED, and that is what the applications section added to this
    case: an instance with no project at all is not an agreeing instance, it is
    a deployment nobody can sign in to, and reading it as agreement was the
    whole of the gap that section closes.
    """
    _branded(operator)
    before = len(_platform_runs())

    out = _run(capsys, expect_exit=0)

    assert len(_platform_runs()) == before
    assert "0 asked" in out


def test_a_branding_drift_is_asked_for_and_the_run_is_the_receipt(
    label: LabelPolicy, operator: Actor, capsys: Any
) -> None:
    """The kind with a row: somebody repainted the screen, and this asks again.

    The `WorkflowRun` row is the instrument — there is nothing else to point at,
    because the management call happens later in an activity and this command
    never makes one.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"
    before = len(_platform_runs())

    out = _run(capsys, expect_exit=0)

    runs = _platform_runs()
    assert len(runs) == before + 1
    assert "asked" in out
    assert runs[-1].workflow_id.startswith("platform:accounts:identity_config:branding-")


def test_a_dry_run_asks_for_nothing_and_says_the_count(
    label: LabelPolicy, operator: Actor, capsys: Any
) -> None:
    """The half that makes this safe to run on a deployment nobody owns yet.

    Exit 1, like the audit's, because the disagreement is still there — a
    `--dry-run` that exited 0 over an open delta would be a green light nobody
    earned.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"
    before = len(_platform_runs())

    out = _run(capsys, "--dry-run", expect_exit=1)

    assert len(_platform_runs()) == before
    assert "would ask" in out
    assert "--dry-run" in out


def test_a_workforce_door_missing_from_zitadel_is_asked_for(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """The environment says the door is on and Zitadel holds no provider.

    The first of the two directions the ownership table calls "env wins BOTH
    ways", and the one that was already reachable: staff cannot sign in, and the
    ask materialises the provider.
    """
    before = len(_platform_runs())

    out = _run(capsys, expect_exit=0)

    runs = _platform_runs()
    assert len(runs) == before + 1
    assert "workforce" in out
    assert runs[-1].workflow_id.startswith("platform:accounts:identity_config:workforce-")


def test_a_workforce_door_switched_off_is_asked_to_come_down(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The direction that had no road at all until the take-down landed.

    `GOOGLE_WORKSPACE_DOMAINS` empty is the door OFF, and a live Google provider
    over an off door is worse than a missing one: it looks open, Zitadel signs
    people in through it, and this product refuses every address it asserts. The
    audit has reported it as drift since the workforce section landed; nothing
    could act on the report, because the service refused an ask it read as
    "materialise a provider with no restriction".
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    instance.idps["9"] = {
        "id": "9",
        "name": "Workforce Google",
        "googleConfig": {"clientId": "google-client-id"},
    }
    before = len(_platform_runs())

    out = _run(capsys, expect_exit=0)

    runs = _platform_runs()
    assert len(runs) == before + 1
    assert "workforce" in out
    assert runs[-1].workflow_id.startswith("platform:accounts:identity_config:workforce-")


def test_the_workforce_door_off_fails_loudly_over_a_live_provider(
    instance: FakeZitadel, settings: Any
) -> None:
    """The door off meets a provider this build cannot deactivate — and says so.

    MEASURED on the pinned build (2026-09-30): the legacy `/idps/{id}/_deactivate`
    answers a provider TEMPLATE `400 Errors.Org.IDPConfig.NotActive (Org-BBmd0)`
    while it is ACTIVE, and the templates have no deactivation of their own. The
    client used to read "NotActive" as already done and report a release over a
    live provider; it now reads the provider back and fails the run naming it.
    The workforce door's real release is a road not built yet (recorded for the
    defects lane); what is pinned here is that nothing claims it happened.
    """
    from apps.accounts import zitadel
    from apps.accounts.activities import apply_identity_config
    from apps.accounts.types import IdentityConfigSync

    settings.GOOGLE_WORKSPACE_DOMAINS = []
    instance.idps["9"] = {
        "id": "9",
        "name": "Workforce Google",
        "googleConfig": {"clientId": "google-client-id"},
        "state": "IDP_STATE_ACTIVE",
    }

    with pytest.raises(zitadel.ZitadelError, match="still IDP_STATE_ACTIVE"):
        apply_identity_config(
            IdentityConfigSync(kind=KIND_WORKFORCE_PROVIDER, key="workforce-abc123")
        )

    assert "9" not in instance.deactivated_idps


def test_a_connection_drift_is_asked_for_against_its_own_tenant(
    instance: FakeZitadel, sso_connection: SsoConnection, capsys: Any
) -> None:
    """A customer's provider, renamed in the console, re-asked under its tenant.

    The run is the TENANT's here and not the platform's — this is one customer's
    configuration — which is the asymmetry `_start_identity_run` documents and
    the reason the reconciler cannot reach for one actor for everything.
    """
    sso_connection.zitadel_idp_id = "77"
    sso_connection.sync_state = SsoConnection.SyncState.APPLIED
    sso_connection.save(update_fields=["zitadel_idp_id", "sync_state"])
    instance.idps["77"] = {"id": "77", "name": "somebody-renamed-this", "oidcConfig": {}}

    out = _run(capsys, expect_exit=0)

    assert "asked" in out
    runs = WorkflowRun.objects.for_tenant(sso_connection.tenant)
    assert runs.count() >= 1


def test_an_unreadable_judged_surface_refuses_and_asks_for_nothing(
    label: LabelPolicy, operator: Actor, workforce: None, capsys: Any
) -> None:
    """Could-not-look is exit 2, and it stops the whole run — every kind.

    Principle 4 and the gate's own grammar: a partial read is not a small read.
    The workforce door is ALSO drifting in this case and would otherwise be
    asked for; a reconciler that repaired what it could see while blind to one
    surface is a reconciler nobody can reason about afterwards.
    """
    _branded(operator)
    label.readable = False
    before = len(_platform_runs())

    out = _run(capsys, expect_exit=2)

    assert len(_platform_runs()) == before
    assert "could not" in out


def test_an_unreadable_OBSERVED_surface_does_not_stop_the_run(
    label: LabelPolicy, operator: Actor, capsys: Any
) -> None:
    """And the declared exception to the line above, which is not a loophole.

    The console's own surfaces are printed and judged by nothing — there is no
    intent for them to disagree with — so a sender this command could not read
    is a line it could not print, not a fact a repair could be wrong about. The
    default `FakeZitadel` answers no SMTP route at all, which is exactly that
    state, and every other case in this module runs in it.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"

    out = _run(capsys, expect_exit=0)

    assert "smtp" in out
    assert "asked" in out


def test_kind_narrows_what_is_asked_for_and_the_rest_still_exits_one(
    label: LabelPolicy, operator: Actor, workforce: None, capsys: Any
) -> None:
    """`--kind` is a narrowing, and a narrowing is not a clean bill of health.

    Two drifts, one named kind: the named one is asked for, the other is printed
    as left, and the exit stays 1. An operator repairing one surface at a time
    on a shared deployment is the case this flag exists for, and the exit is how
    they find out they are not finished.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"
    before = len(_platform_runs())

    out = _run(capsys, "--kind", KIND_IDENTITY_BRANDING, expect_exit=1)

    assert len(_platform_runs()) == before + 1
    assert f"asked       {KIND_IDENTITY_BRANDING}" in out
    assert f"--kind {KIND_IDENTITY_BRANDING} did not select {KIND_WORKFORCE_PROVIDER}" in out


# --- I3.5 · exit codes -------------------------------------------------------


def test_an_unconfigured_deployment_is_could_not_look(settings: Any, capsys: Any) -> None:
    """No issuer and no credential is not "nothing to reconcile"."""
    settings.ZITADEL_ISSUER = ""
    settings.ZITADEL_PAT = ""

    with pytest.raises(CommandError) as error_info:
        call_command("zitadel_reconcile")

    assert error_info.value.returncode == 2


def test_a_delta_with_no_road_leaves_the_exit_at_one(
    instance: FakeZitadel, posture_open: None, capsys: Any
) -> None:
    """A disagreement this command cannot close still has to be visible.

    The posture's road is the seed's writers, not this command (the ownership
    table says so), so a posture drift is reported, left alone, and the exit
    stays 1 — the audit's own answer. Exiting 0 because "we asked for everything
    we could" is how a reconciler comes to certify an instance it did not fix.
    """
    out = _run(capsys, expect_exit=1)

    assert "DRIFT       posture" in out
    assert "zitadel_seed" in out


# --- I3.6 · who may, and the receipt ----------------------------------------


def test_an_ordinary_owner_may_not_reconcile_the_deployments_own_screen(
    label: LabelPolicy, operator: Actor, owner: User, capsys: Any
) -> None:
    """`identity_platform.configure` is a platform operator's, not a tenant's.

    Driven through `--as` because that is the only door this command has, and
    because a refusal that only ever happens for the system actor is a refusal
    nobody can reach.
    """
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"
    owner.is_superuser = False
    owner.save(update_fields=["is_superuser"])
    before = len(_platform_runs())

    with pytest.raises(CommandError):
        call_command("zitadel_reconcile", "--as", owner.email)

    assert len(_platform_runs()) == before


def test_the_named_operator_is_on_the_audit_row(
    label: LabelPolicy, operator: Actor, owner: User, capsys: Any
) -> None:
    """The receipt: who asked, and which run it produced.

    `@service` writes the row; what this pins is that the command hands it a
    person rather than the system when `--as` names one, because on a shared
    deployment "the shell did it" is the least useful audit line there is.
    """
    from apps.core.audit import AuditEntry

    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"

    _run(capsys, "--as", owner.email, expect_exit=0)

    entry = (
        AuditEntry.objects.filter(action="accounts.set_identity_branding")
        .order_by("-created_at")
        .first()
    )
    assert entry is not None
    assert entry.actor_user_id == owner.pk
    assert entry.actor_kind == "human"


def test_an_unknown_operator_email_is_a_refusal(instance: FakeZitadel) -> None:
    """Naming somebody who is not there is a refusal, not a fall back to system."""
    with pytest.raises(CommandError):
        call_command("zitadel_reconcile", "--as", "nobody@example.com")


# --- I3.7 · the re-ask after failure ----------------------------------------


def test_a_failed_run_is_reopened_rather_than_refused(
    label: LabelPolicy, operator: Actor, capsys: Any
) -> None:
    """D1's fifth answer, used by the first caller that needed it.

    A materialisation that failed — Zitadel down, a credential rotated — leaves
    a finished run under the intent's own key. Without the re-ask, the honest
    retry is refused as a repeat and the only way forward is to change the
    intent, which is the opposite of what the operator wants.
    """
    row = _branded(operator)
    run = WorkflowRun.objects.for_platform().exclude(type=IDENTITY_HOME_WORKFLOW).get()
    run.status = WorkflowRun.Status.FAILED
    run.error = "zitadel said no"
    run.save(update_fields=["status", "error"])

    services.set_identity_branding(actor=operator, tenant=None, branding=row, observed="")

    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING


# --- I3.8 · the scheduled reconciler stays unbuilt --------------------------


def test_the_command_prints_the_trigger_for_scheduling_itself(
    instance: FakeZitadel, capsys: Any
) -> None:
    """Shop-the-price, printed where the person who would want it is reading.

    A Temporal Schedule around this is one `ScheduleDeclaration`, and it is
    deliberately not written: a scheduled repairer of drift that only a console
    can cause, on a deployment whose console has one operator, guards nothing
    and repaints a screen at 3am. The trigger is named so the decision is
    reversible by evidence rather than by somebody's afternoon.
    """
    out = _run(capsys)

    assert "not built" in out
    assert "schedule" in out.lower()


# --- the command changes nothing in Zitadel ---------------------------------


def test_the_reconciler_makes_no_management_write_on_the_service_roads(
    label: LabelPolicy, operator: Actor, seeded: FakeZitadel, capsys: Any
) -> None:
    """House rules 10 and 27, as a property of the CALLS this process made.

    On the three kinds that have a row or an environment intent the repair is an
    ask and the run is what reaches Zitadel, so the repairing path leaves the
    instance byte-identical at the end of THIS process and the only requests in
    the log are the reads the audit was already allowed.

    **Driven with `--kind` for the one declared exception.** The applications
    road runs `manage.py zitadel_seed`, which IS a management writer — named in
    this command's docstring rather than hidden, and the reason this case says
    which roads it is about instead of claiming the whole command writes
    nothing. The case below drives that road and asserts the write.
    """
    instance = seeded
    _branded(operator)
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"
    before = json.dumps(instance.idps, sort_keys=True)
    instance.requests.clear()

    _run(capsys, "--kind", KIND_IDENTITY_BRANDING, expect_exit=0)

    assert all(method == "GET" or path.endswith("_search") for method, path in instance.requests), (
        instance.requests
    )
    assert json.dumps(instance.idps, sort_keys=True) == before


# --- the applications: the deployment's own project, read and repaired -------
#
# The audit walked rows, then the workforce door, then the branding row and the
# posture — and never once looked at the project and applications the seed
# makes. Its own `does not cover` paragraph admitted "any project or application
# no row of ours names", and the deployment's OWN browser client is exactly
# that: the object every person signs in through. A one-field console edit to
# its redirect URI reads as agreement, and the person signing in lands on raw
# JSON at the identity platform, upstream of any page of ours.


@pytest.fixture
def seeded(instance: FakeZitadel, settings: Any, capsys: Any) -> FakeZitadel:
    """The project and its three applications, made by the declared writer.

    Built by running the seed rather than by hand-planting objects in the fake:
    the audit's whole job here is to compare the live objects against the values
    the seed declares, and a world assembled by a test is a world that can
    agree with the audit while disagreeing with the writer.
    """
    settings.PUBLIC_BASE_URL = "http://localhost:8000"
    call_command("zitadel_seed", "--skip-user")
    capsys.readouterr()
    return instance


def _browser(instance: FakeZitadel) -> dict[str, Any]:
    return next(row for row in instance.apps.values() if row["name"] == "Web")


def test_a_console_moved_redirect_uri_is_drift(seeded: FakeZitadel, capsys: Any) -> None:
    """THE criterion, and the move is the one that was made live.

    `PUT /management/v1/projects/<mine>/apps/<mine>/oidc_config redirectUris:
    ["http://127.0.0.1:1/hijacked/"]` — the audit answered exit 0, "Zitadel
    agrees with every row. Nothing changed." The line now names both values, so
    a reader can see which one is ours without opening the console.
    """
    _browser(seeded)["oidcConfig"]["redirectUris"] = ["http://127.0.0.1:1/hijacked/"]

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       applications"))
    assert "redirectUris" in drift
    assert "127.0.0.1:1/hijacked" in drift
    assert "localhost:8000/accounts/oidc/zitadel/login/callback/" in drift
    assert "1 disagreement(s). Nothing was changed." in out


def test_an_agreeing_project_is_reported_as_agreeing(seeded: FakeZitadel, capsys: Any) -> None:
    """The sibling that stops the clause above from being "always drift"."""
    out = _audit(capsys, expect_exit=0)

    assert "agrees      applications" in out
    assert "DRIFT       applications" not in out


def test_a_missing_project_is_drift_naming_the_seed(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """A CONFIGURED deployment whose project is gone: the remedy is the seed.

    The environment names a client id, which is this deployment claiming a
    browser client exists — so the project's absence makes that claim false and
    nobody can sign in. A remedy that does not work is worse than none, so the
    line names `zitadel_seed`, which is the command that exists and the one door
    onto these objects.
    """
    settings.ZITADEL_CLIENT_ID = "a-client-id-this-deployment-signs-in-with"

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       applications"))
    assert _declared_project() in drift
    assert "manage.py zitadel_seed" in drift


def test_a_missing_application_is_drift_naming_the_seed(seeded: FakeZitadel, capsys: Any) -> None:
    """The project is there and one application is gone — deleted in the console."""
    del seeded.apps[_browser(seeded)["id"]]

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       applications"))
    assert "Web" in drift
    assert "manage.py zitadel_seed" in drift


def test_an_unreadable_applications_surface_is_could_not(
    seeded: FakeZitadel, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Could-not-look is not a console edit, here as everywhere in this report."""

    def refuse(**_kwargs: Any) -> list[dict[str, Any]]:
        raise zitadel_module.ZitadelError("the instance would not answer")

    monkeypatch.setattr(zitadel_module, "projects", refuse)

    out = _audit(capsys, expect_exit=0)

    assert "could not   applications" in out
    assert "DRIFT       applications" not in out


def test_a_second_project_bearing_the_declared_name_is_named_not_renamed(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """ADR platform-1: a second object is a delta to print, never a rename.

    Two projects bearing the declared name is what a sibling checkout's seed
    leaves behind when somebody changes `ZITADEL_PROJECT_NAME` and back, and
    renaming either of them would break whichever deployment is pointing at the
    other. So it is drift the report NAMES — both ids — and does not touch.
    """
    seeded.projects["9999"] = {"id": "9999", "name": _declared_project()}

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       applications"))
    assert "2 projects" in drift
    assert "9999" in drift
    assert "rename" in drift.lower()


def test_the_reconciler_refuses_the_applications_kind_while_a_second_project_exists(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """And the repairer will not guess which of two projects is the deployment's.

    A writer aimed at the wrong one of two same-named projects reconfigures a
    sibling deployment's sign-in. There is no safe automatic answer, so the
    reconciler refuses the kind, says why, and leaves the delta open — exit 1,
    not a repair.
    """
    seeded.projects["9999"] = {"id": "9999", "name": _declared_project()}
    before = len(seeded.bodies)

    out = _run(capsys, "--kind", "applications", expect_exit=1)

    assert not [
        one for one in seeded.bodies[before:] if one[0] in ("PUT", "POST") and "oidc" in one[1]
    ]
    assert "left" in out
    assert "two projects" in out.lower() or "2 projects" in out


def test_an_env_client_id_that_names_no_live_app_is_drift(
    seeded: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """`.env`'s copy of a minted id, beside the live one.

    Zitadel mints the browser client's id; `.env` keeps a copy because that is
    the only way the RP can name it. Nothing reconciles the copy — a command
    that wrote `.env` would be a command editing the operator's environment —
    so the honest thing is to print both and call a difference drift with the
    remedy beside it.
    """
    settings.ZITADEL_CLIENT_ID = "a-client-id-from-some-other-project"

    out = _audit(capsys, expect_exit=1)

    line = next(line for line in out.splitlines() if "client id" in line)
    assert "a-client-id-from-some-other-project" in line
    assert "ZITADEL_CLIENT_ID" in line
    assert "DRIFT" in line


def test_an_audience_naming_a_dead_project_is_drift(
    seeded: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """A re-seeded checkout's MCP door points at a resource that is gone.

    `setup.sh` writes the audience only when the slot is empty, so a checkout
    whose project was recreated keeps the previous project's id — and the MCP
    OAuth door then refuses every token, silently, because the `aud` it demands
    names nothing.
    """
    settings.ZITADEL_MCP_AUDIENCE = ["387613333072642054"]

    out = _audit(capsys, expect_exit=1)

    line = next(
        line
        for line in out.splitlines()
        if line.strip().startswith(("audience", "DRIFT       audience"))
    )
    assert "387613333072642054" in line
    assert "ZITADEL_MCP_AUDIENCE" in line
    # The dead-pointer half of the sentence, asserted rather than assumed: the
    # id resolves to no project the instance holds, and that is what the line
    # is allowed to say. Its sibling below holds the other half.
    assert "387613333072642054 names nothing on this instance" in line
    assert "names project" not in line


def test_an_audience_naming_another_project_on_the_instance_names_it(
    seeded: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """A LIVE pointer aimed at somebody else's project, not a dead one.

    Found live, not imagined: a deployment's `ZITADEL_MCP_AUDIENCE` named a
    NEIGHBOURING project on the shared instance rather than its own. The door
    refuses every token either way, so it is drift either way — but the
    operator told "names nothing on this instance" goes looking for an object
    that is sitting in the console. The audit already read every project to
    find its own, so naming the one it resolves to costs no management call.
    """
    seeded.projects["4242"] = {"id": "4242", "name": "Neighbour"}
    settings.ZITADEL_MCP_AUDIENCE = ["4242"]

    out = _audit(capsys, expect_exit=1)

    line = next(
        line
        for line in out.splitlines()
        if line.strip().startswith(("audience", "DRIFT       audience"))
    )
    assert "DRIFT" in line
    assert "4242 names project Neighbour (4242) on this instance" in line
    assert "which is not this deployment's" in line
    assert "names nothing on this instance" not in line


def test_an_audience_naming_the_live_project_agrees(
    seeded: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The negative: either the project id or the resource's client id is legal.

    `.env.example` says so, and both are what Zitadel actually puts in `aud`, so
    a census that accepted only one of them would call a working deployment
    drift.
    """
    project = next(row for row in seeded.projects.values() if row["name"] == _declared_project())
    settings.ZITADEL_MCP_AUDIENCE = [project["id"]]

    out = _audit(capsys, expect_exit=0)

    assert "agrees      audience" in out


def test_an_unconfigured_checkout_reads_as_unmanaged_and_not_as_drift(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Nothing seeded and nothing claiming it is: the branding section's own word.

    A fresh clone before `scripts/setup.sh` runs is in this state, and so is
    every rung worktree on this machine — `grep -c '^ZITADEL_CLIENT_ID=.\\+' .env`
    is 0 in the one this was built in. Reading that as a broken deployment would
    make the report's exit status useless on exactly the checkouts that run it
    most, and "we cannot disagree with an intent nobody has stated" is the same
    distinction `SyncState.UNMANAGED` draws for a connection nobody synced.
    """
    settings.ZITADEL_CLIENT_ID = ""
    settings.ZITADEL_MCP_AUDIENCE = []

    out = _audit(capsys, expect_exit=0)

    assert "unmanaged   applications" in out
    assert "DRIFT" not in out


def test_an_unset_env_copy_is_printed_and_never_drift(
    seeded: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Unset is a deployment that has not configured that door, not a disagreement.

    This very checkout is in that state, which is the reason the distinction has
    to be in the code rather than in a reader's head: a rung worktree with no
    browser sign-in must not read as a broken deployment.
    """
    settings.ZITADEL_CLIENT_ID = ""
    settings.ZITADEL_MCP_AUDIENCE = []

    out = _audit(capsys, expect_exit=0)

    assert "unset" in out
    assert "DRIFT" not in out


def test_the_reconciler_closes_an_applications_drift_by_running_the_declared_writer(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """The road for this kind is the seed's own writer, and the reconciler runs it.

    Unlike the three kinds whose repair is a service ask and a run, the
    applications' writer is a shell door: there is no row to state an intent on,
    the declared values are settings, and `manage.py zitadel_seed` is the one
    thing that writes them. So this is the one road on which the reconciler's
    own process reaches Zitadel, and it says so on the line it prints.
    """
    _browser(seeded)["oidcConfig"]["redirectUris"] = ["http://127.0.0.1:1/hijacked/"]

    out = _run(capsys, "--kind", "applications", expect_exit=0)

    assert _browser(seeded)["oidcConfig"]["redirectUris"] == [
        "http://localhost:8000/accounts/oidc/zitadel/login/callback/"
    ]
    assert "asked       applications" in out
    assert "zitadel_seed" in out


def test_a_dry_run_leaves_the_hijacked_uri_alone(seeded: FakeZitadel, capsys: Any) -> None:
    """The half that makes the road above safe to look at first."""
    _browser(seeded)["oidcConfig"]["redirectUris"] = ["http://127.0.0.1:1/hijacked/"]

    out = _run(capsys, "--dry-run", "--kind", "applications", expect_exit=1)

    assert _browser(seeded)["oidcConfig"]["redirectUris"] == ["http://127.0.0.1:1/hijacked/"]
    assert "would ask   applications" in out


# --- design C-9 · the login version, judged and repaired both ways -----------
#
# `loginVersion` decides where `GET /oauth/v2/authorize` sends a person before
# any page of ours renders. It is not a field the URI writer touches — it is
# carried back byte-identical on purpose — so nothing in this report saw it,
# and a console-set v2 pointed everybody at a host this deployment does not
# serve while the audit said "Zitadel agrees with every row".


CONSOLE_V2 = {"loginV2": {"baseUri": "http://somebody-elses-host.test/accounts"}}


def test_a_console_declared_login_v2_is_drift_and_reconcile_clears_it(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """A2.3, both halves in one case, because they are one road.

    The plant is the console move: one field on the deployment's own browser
    client. The audit has to SEE it — the line names the live declaration, what
    this deployment declares instead, and what reads it — and the reconciler
    has to CLOSE it, through the declared writer, leaving the application with
    no declaration at all. The reverse direction is the one the consumer
    lacked: they could declare v2 and not withdraw it, and an owner spent a
    morning locked out of a deployment because of it.
    """
    _browser(seeded)["oidcConfig"]["loginVersion"] = dict(CONSOLE_V2)

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       applications"))
    assert "loginVersion" in drift
    assert "v2 at http://somebody-elses-host.test/accounts" in drift
    assert "none (the identity platform's own page)" in drift
    assert "/oauth/v2/authorize" in drift

    asked = _run(capsys, "--kind", "applications")

    assert "would ask" not in asked
    assert "asked       applications" in asked
    assert "zitadel_seed" in asked
    assert zitadel_module.login_version_of(_browser(seeded)) is None
    assert "agrees      applications" in _audit(capsys, expect_exit=0)


def test_a_dry_run_names_the_login_version_and_declares_nothing(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """The control: `--dry-run` prints the ask and touches the declaration.

    Not a restatement of the dry-run case above — that one proves no service is
    asked. This proves the LIVE OBJECT is untouched on the one road that runs a
    management-writing command rather than a service, which is the road where a
    dry run could most easily forget it was a dry run.
    """
    _browser(seeded)["oidcConfig"]["loginVersion"] = dict(CONSOLE_V2)

    out = _run(capsys, "--dry-run", expect_exit=1)

    would = next(line for line in out.splitlines() if line.startswith("would ask   applications"))
    assert "loginVersion" in would
    assert zitadel_module.login_version_of(_browser(seeded)) == CONSOLE_V2


def test_a_login_version_on_the_mcp_client_is_drift_too(seeded: FakeZitadel, capsys: Any) -> None:
    """Both OIDC clients are judged, not only the browser RP.

    The MCP native client is a door a person signs in through — an assistant's
    OAuth round trip ends on the same page — so a declaration on it sends those
    people somewhere else while the browser client reads as agreeing. The MCP
    *resource* is deliberately absent: it is an API application with no OIDC
    config, and a login version on an object nobody logs in through would be a
    finding nobody can act on.
    """
    client = next(row for row in seeded.apps.values() if row["name"] == "MCP Client")
    client["oidcConfig"]["loginVersion"] = dict(CONSOLE_V2)

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if "loginVersion" in line)
    assert "MCP Client" in drift
    assert "DRIFT" in drift
    # And the resource, which has no OIDC config at all, is not reported on.
    assert "MCP (" not in drift


# --- design I-A fact 2 · the role the finalize needs -------------------------


def test_a_missing_login_client_role_is_drift_naming_the_finalize(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """A2.4's judgement: `IAM_OWNER` is not enough, and the line says why.

    Its absence is invisible from everywhere else — every seed, every audit and
    every sync keeps working, and sign-in fails at the last hop with a refusal
    that names no role. So the line has to carry the whole diagnosis: which
    user, which role, which call, and the error id Zitadel answers with.
    """
    seeded.instance_members[str(seeded.machine["id"])] = ["IAM_OWNER"]

    out = _audit(capsys, expect_exit=1)

    drift = next(line for line in out.splitlines() if line.startswith("DRIFT       login client"))
    assert "djb-platform" in drift
    assert "IAM_LOGIN_CLIENT" in drift
    assert "AUTH-AWfge" in drift
    assert "/v2/oidc/auth_requests" in drift
    assert "zitadel_seed" in drift


def test_the_reconciler_grants_the_login_client_role_under_its_own_kind(
    seeded: FakeZitadel, capsys: Any
) -> None:
    """And `--kind` selects it without selecting the applications.

    The two share a road — the seed's writers — and that is exactly why they
    are separate kinds: a flag named `applications` that also granted a manager
    role on the instance would be a flag whose name does not say what it does.
    """
    machine = str(seeded.machine["id"])
    seeded.instance_members[machine] = ["IAM_OWNER"]

    out = _run(capsys, "--kind", LOGIN_CLIENT_KIND)

    assert "asked       login client" in out
    assert seeded.instance_members[machine] == ["IAM_OWNER", "IAM_LOGIN_CLIENT"]
    assert "agrees      login client" in _audit(capsys, expect_exit=0)


def test_an_unreadable_login_client_surface_refuses_the_whole_run(
    seeded: FakeZitadel, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Could not look means nothing is asked for, for any kind (principle 4).

    A surface this command JUDGES that would not answer stops the run: a
    partial read is not a small read. Asserted on the new section because a
    section added without the unreadable branch is a section that would let a
    repair proceed while blind to the permission that decides whether sign-in
    works at all.
    """

    def refuse() -> dict[str, Any]:
        raise zitadel_module.ZitadelError("Zitadel GET /auth/v1/users/me answered 503: gateway")

    monkeypatch.setattr(zitadel_module, "machine_user", refuse)
    before = len(seeded.bodies)

    out = _run(capsys, expect_exit=2)

    assert "could not   login client" in out
    # No WRITE, on any road. `POST` is how Zitadel spells a search, so the
    # census is over the paths a writer uses rather than over the verb.
    assert not [
        one
        for one in seeded.bodies[before:]
        if one[0] == "PUT" or (one[0] == "POST" and not one[1].endswith("_search"))
    ]


def test_a_stale_staff_join_is_retired_and_its_realm_row_kept(
    label: LabelPolicy,
    operator: Actor,
    seeded: FakeZitadel,
    tenant: Tenant,
    owner: User,
    capsys: Any,
) -> None:
    """A `staff` row whose subject also holds a tenant-realm row is a rollback's leftover."""
    from apps.accounts.models import STAFF_REALM, SsoIdentity

    _branded(operator)
    SsoIdentity.objects.filter(user=owner, connection__isnull=True).delete()
    for realm, row_tenant in ((STAFF_REALM, None), ("realm-777", tenant)):
        SsoIdentity.objects.create(
            user=owner,
            realm=realm,
            subject="sub-twice",
            tenant=row_tenant,
            connection=None,
            email=owner.email,
        )

    dry = _run(capsys, "--dry-run", expect_exit=0)
    assert "would retire" in dry
    assert SsoIdentity.objects.filter(realm=STAFF_REALM, subject="sub-twice").exists()

    out = _run(capsys, expect_exit=0)
    assert "retired" in out
    rows = SsoIdentity.objects.filter(subject="sub-twice", connection__isnull=True)
    assert list(rows.values_list("realm", flat=True)) == ["realm-777"]
