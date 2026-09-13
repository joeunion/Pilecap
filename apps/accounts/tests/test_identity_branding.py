"""The hosted sign-in screen has an intent row, and the console is a window.

The entrance survey measured five styling regimes in one eight-screen sign-in
chain. Four of them were closed inside this codebase; the fifth was always
going to need a row, because the screen that mismatched is not ours to render —
it is Zitadel's, and the only thing this side can do about it is *state what it
should look like* and send that statement over the management API.

So this module is about house rule 27 in its purest form. **The row is the
intent; the console is a window, not a door.** Somebody with console access can
repaint the login page in thirty seconds; nothing here can stop them, and
pretending otherwise would be the fiction rule 27's declared blind spot exists
to refuse. What the rule buys is that the disagreement becomes *visible* — there
is now something to disagree with, and `zitadel_audit` says so.

The properties pinned here, each a property rather than a mechanism:

* the intent row is written through a service and by nothing else, and the
  service defers the management call past commit (criterion 5 — the C2 classic:
  an external call inside the transaction is a Zitadel hiccup rolling back a
  legitimate row);
* the activity's dispatch KNOWS the kind, where it used to refuse it by name;
* `ensure_label_policy` is idempotent in the way this surface actually demands —
  which is not the way the other eight `ensure_*` are, because Zitadel's PUT
  refuses a no-op;
* the deployment default is DERIVED from the same two settings the entrance
  templates read, so the page before the hosted step and the page after it
  cannot disagree (criterion 3, the one-declared-value law).

Nothing here dials Zitadel. `FakeZitadel` is the socket, and the label-policy
routes are layered on in THIS module rather than added to the shared fake, for
the reason `test_zitadel_console_surfaces.py` gives about its own two: the
shared fake is every identity test's fixture, and these routes are this module's
subject.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import services, zitadel
from apps.accounts.models import IdentityBranding, SsoConnection
from apps.accounts.services import SYNC_IDENTITY_CONFIG_WORKFLOW
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    IdentityConfigApplied,
    IdentityConfigSync,
)
from apps.core.actor import actor_for, system_actor
from apps.core.models import Tenant
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

# The instance default, as the pinned build answers it — MEASURED by a
# read-only probe against the live Zitadel this repository runs against, not
# copied off a doc page. The top-level `isDefault` is the whole news: it is
# present when the org has never been branded and ABSENT once somebody has
# branded it, which is the same by-omission shape `login_policy` carries and
# the shape most likely to be read wrong once.
INSTANCE_DEFAULT: dict[str, Any] = {
    "isDefault": True,
    "policy": {
        "backgroundColor": "#fafafa",
        "backgroundColorDark": "#111827",
        "details": {
            "changeDate": "2026-08-24T00:32:31.898945Z",
            "creationDate": "2026-08-24T00:32:31.898945Z",
            "resourceOwner": "387613333072642054",
            "sequence": "24",
        },
        "fontColor": "#000000",
        "fontColorDark": "#ffffff",
        "isDefault": True,
        "primaryColor": "#5469d4",
        "primaryColorDark": "#2073c4",
        "themeMode": "THEME_MODE_AUTO",
        "warnColor": "#cd3d56",
        "warnColorDark": "#ff3b5b",
    },
}


class LabelPolicy:
    """Zitadel's label-policy surface, as a little state machine.

    A holder rather than loose dicts because the interesting states are states —
    "this org has never been branded", "somebody branded it", "the draft was
    never activated" — and a test that can put the surface INTO a state is the
    only way those are provable rather than asserted about a code path nobody
    ran.

    **Booleans are absent when false**, which is measured: proto3 omits its zero
    values, so `disableWatermark: False` never appears in a real answer. The
    fake omits them too, because a fake that sent `false` would let a reader
    that keys on presence pass here and fail against the real thing.
    """

    def __init__(self) -> None:
        self.custom: dict[str, Any] | None = None
        self.activated = False
        self.readable = True
        self.sequence = 24

    def answer(self) -> dict[str, Any]:
        if self.custom is None:
            deep_copy: dict[str, Any] = json.loads(json.dumps(INSTANCE_DEFAULT))
            return deep_copy
        policy = {
            key: value
            for key, value in self.custom.items()
            if not (isinstance(value, bool) and value is False)
        }
        policy["details"] = {
            "resourceOwner": "387613333072707590",
            "sequence": str(self.sequence),
        }
        policy["themeMode"] = "THEME_MODE_AUTO"
        return {"policy": policy}


@pytest.fixture
def label(instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch) -> LabelPolicy:
    """`FakeZitadel` plus the four label-policy routes, measured off the real API."""
    surface = LabelPolicy()
    original: Callable[[str, str, dict[str, Any]], dict[str, Any]] = instance._route

    def routed(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "/policies/label":
            if not surface.readable:
                raise KeyError(path)
            if method == "GET":
                return surface.answer()
            if method == "POST":
                surface.custom = dict(body)
                surface.sequence += 1
                return {"details": {"sequence": str(surface.sequence)}}
            if method == "PUT":
                # MEASURED: an unchanged PUT answers 400 `Org-8nfSr`. The fake
                # refuses it too, because an `ensure_*` that PUT unconditionally
                # would pass against a lenient fake and fail on its SECOND real
                # call — which is exactly the call Temporal's at-least-once
                # delivery guarantees will happen.
                if surface.custom == dict(body):
                    raise AssertionError("PUT with no change — Zitadel answers 400 Org-8nfSr here")
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
def operator(db: None, tenant: Tenant, owner: Any) -> Any:
    """Somebody who may configure the deployment's identity platform."""
    owner.is_superuser = True
    owner.save(update_fields=["is_superuser"])
    return actor_for(user=owner, tenant=tenant)


# --- criterion 1: the intent row, and the dispatch that used to refuse it ----


def test_the_activity_no_longer_refuses_the_branding_kind(
    label: LabelPolicy, operator: Any
) -> None:
    """The red-first, closed: `apply_identity_config` used to refuse this by name.

    Before the branding kind existed the dispatch's else-branch raised
    `ValueError` naming the kind and pointing at `types.py`'s
    vocabulary. The vocabulary now holds it.
    """
    from apps.accounts.activities import apply_identity_config

    row = services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")

    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk))
    )

    assert applied.kind == KIND_IDENTITY_BRANDING
    assert label.custom is not None
    assert label.custom["primaryColor"] == "#3f4a5a"


def test_an_unknown_kind_is_still_refused_by_name(label: LabelPolicy) -> None:
    """The else-branch still guards: widening the vocabulary did not open it.

    The sibling of the test above, and the reason it exists: a dispatch that
    stopped refusing anything would pass the test above for the wrong reason.
    """
    from apps.accounts.activities import apply_identity_config

    with pytest.raises(ValueError, match="does not know the config kind"):
        apply_identity_config(IdentityConfigSync(kind="not_a_kind", key="x"))


def test_the_branding_row_is_deployment_level_and_not_tenant_scoped() -> None:
    """The lead's scoping ruling, asserted against the model rather than assumed.

    One Zitadel instance, one login screen: a tenant-scoped table would promise
    per-tenant branding the single shared LabelPolicy cannot deliver. Per-tenant
    is the recorded ADR trigger, not something built here.
    """
    fields = {field.name for field in IdentityBranding._meta.get_fields()}
    assert "tenant" not in fields
    assert "organization" not in fields


def test_only_one_branding_row_is_active_at_a_time(label: LabelPolicy, operator: Any) -> None:
    """Two intents for one screen would mean whichever ran last wins, silently.

    Enforced by a partial unique index rather than by convention, so it is
    unrepresentable and not merely discouraged.
    """
    first = services.set_identity_branding(actor=operator, tenant=None, accent="#111111")
    second = services.set_identity_branding(actor=operator, tenant=None, accent="#222222")

    first.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert IdentityBranding.objects.filter(is_active=True).count() == 1
    # And the superseded row is still readable — what the screen used to look
    # like stays answerable.
    assert first.accent == "#111111"


# --- criterion 3: the one-declared-value law ---------------------------------


def test_the_default_derives_from_the_settings_the_entrance_css_reads(
    label: LabelPolicy, operator: Any, settings: Any
) -> None:
    """One declared value, two consumers — so regime 3 collapses by construction.

    `PRODUCT_NAME` and `BRAND_ACCENT` are the SAME two settings
    `apps/accounts/templatetags/entrance.py` reads into the entrance token
    block. If the hosted screen derived from anywhere else, the page before the
    hop and the page after it could disagree while both were "correct".
    """
    settings.PRODUCT_NAME = "Sett"
    settings.BRAND_ACCENT = "#0b7285"

    row = services.set_identity_branding(actor=operator, tenant=None)

    assert row.product_name == "Sett"
    assert row.accent == "#0b7285"


def test_the_built_payload_carries_the_declared_accent(
    label: LabelPolicy, operator: Any, settings: Any
) -> None:
    """The criterion's own instrument: what Zitadel is SENT equals the setting.

    Asserted on the payload that reached the API rather than on the row, because
    the row agreeing with settings and the API being sent something else is
    exactly the failure this is meant to exclude.
    """
    from apps.accounts.activities import apply_identity_config

    settings.BRAND_ACCENT = "#0b7285"
    row = services.set_identity_branding(actor=operator, tenant=None)

    apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)))

    assert label.custom is not None
    assert label.custom["primaryColor"] == "#0b7285"


def test_an_unset_brand_accent_flows_the_shipped_neutral_to_both_consumers(
    label: LabelPolicy, operator: Any, settings: Any
) -> None:
    """The absent case the criterion names, and it is the common one.

    A clone that has never set `BRAND_ACCENT` gets the restrained neutral, and
    it gets the SAME one on both sides — the settings default is what the
    entrance templatetag falls back to and what this row is built from, so
    "unset" is one value, not two.
    """
    from apps.accounts.templatetags.entrance import DEFAULT_ACCENT
    from config.settings.base import DEFAULT_BRAND_ACCENT

    settings.BRAND_ACCENT = DEFAULT_BRAND_ACCENT

    row = services.set_identity_branding(actor=operator, tenant=None)

    assert row.accent == DEFAULT_BRAND_ACCENT
    assert row.accent == DEFAULT_ACCENT


# --- criterion 5: transaction discipline -------------------------------------


def test_the_service_writes_the_row_and_calls_zitadel_from_nowhere(
    label: LabelPolicy, operator: Any
) -> None:
    """The C2 classic: no management call inside the service's transaction.

    Asserted on the CALL LOG, which is the only place the property is visible: a
    service that dialled Zitadel and happened to succeed would leave a row that
    looked identical to one that deferred properly.
    """
    before = len(label.answer())  # touch nothing; just prove the fixture is live
    assert before

    services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")

    assert label.custom is None, "the service reached Zitadel inside its own transaction"


def test_the_service_leaves_the_row_pending_until_the_activity_runs(
    label: LabelPolicy, operator: Any
) -> None:
    """`pending` means "we have said what we want and Zitadel has not been told".

    The gap between intent and materialisation, said out loud on the row — the
    same column and the same vocabulary `SsoConnection` uses for it.
    """
    from apps.accounts.activities import apply_identity_config

    row = services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")
    assert row.sync_state == SsoConnection.SyncState.PENDING

    apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)))

    row.refresh_from_db()
    assert row.sync_state == SsoConnection.SyncState.APPLIED


def test_the_write_back_goes_through_the_service(label: LabelPolicy, operator: Any) -> None:
    """House rule 10: the activity learned a fact, the service records it.

    Proved by calling the service's record mode directly and seeing the state
    move — the same two-mode shape `sync_identity_config` has.
    """
    row = services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")

    services.set_identity_branding(
        actor=system_actor(),
        tenant=None,
        branding=row,
        applied=IdentityConfigApplied(
            kind=KIND_IDENTITY_BRANDING, key=str(row.pk), resource_id="1", created=False
        ),
    )

    row.refresh_from_db()
    assert row.sync_state == SsoConnection.SyncState.APPLIED


# --- criterion 2: ensure_label_policy joins the family -----------------------


def test_the_first_call_creates_and_activates(label: LabelPolicy) -> None:
    """A staged-but-unactivated policy is the failure that looks like success.

    Zitadel stores the values and the login screen does not change. So the
    activate call is not conditional on anything, and this is what says so.
    """
    resource = zitadel.ensure_label_policy(accent="#3f4a5a")

    assert resource.created is True
    assert label.custom is not None
    assert label.activated is True


def test_the_same_input_twice_leaves_one_object_and_reports_not_created(
    label: LabelPolicy,
) -> None:
    """The family contract, and here it is load-bearing rather than tidy.

    Zitadel's PUT answers 400 on an unchanged policy (MEASURED: `Org-8nfSr`), so
    an `ensure_*` that wrote unconditionally would FAIL on its second call — and
    the second call is the one Temporal's at-least-once delivery guarantees.
    The comparison is the idempotence, not an optimisation.
    """
    first = zitadel.ensure_label_policy(accent="#3f4a5a")
    second = zitadel.ensure_label_policy(accent="#3f4a5a")

    assert first.created is True
    assert second.created is False
    assert label.custom is not None
    assert label.custom["primaryColor"] == "#3f4a5a"


def test_a_changed_accent_updates_rather_than_creating_a_second(label: LabelPolicy) -> None:
    """The other half: a real change goes through, by PUT, and is activated."""
    zitadel.ensure_label_policy(accent="#3f4a5a")
    label.activated = False

    resource = zitadel.ensure_label_policy(accent="#0b7285")

    assert resource.created is False
    assert label.custom is not None
    assert label.custom["primaryColor"] == "#0b7285"
    assert label.activated is True


def test_the_watermark_switch_reaches_zitadel_under_its_own_name(label: LabelPolicy) -> None:
    """Our column is `is_watermark_disabled`; Zitadel's key is `disableWatermark`.

    The naming grammar (house rule 16) says a boolean says it is one, and the
    translation belongs at this edge with every other name Zitadel uses.
    """
    zitadel.ensure_label_policy(accent="#3f4a5a", is_watermark_disabled=True)

    assert label.custom is not None
    assert label.custom["disableWatermark"] is True


def test_the_ensure_family_is_what_the_module_declares() -> None:
    """The population is DERIVED off the module, never typed from a plan.

    A floor rather than an equality on a number written here: the point is that
    the new function joined the family under the family's own naming, and that
    a future `ensure_*` is not silently absent from it.
    """
    import inspect

    family = sorted(
        name
        for name, value in vars(zitadel).items()
        if name.startswith("ensure_") and inspect.isfunction(value)
    )
    assert "ensure_label_policy" in family
    assert len(family) >= 9
    for name in family:
        signature = inspect.signature(getattr(zitadel, name))
        assert signature.return_annotation in {"Resource", zitadel.Resource}, name
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        ), f"{name} takes a positional argument; the family is keyword-only"


# `ensure_label_policy` reaching for `ZITADEL_PAT` directly, or a new caller
# importing `apps.accounts.zitadel` from outside the activity or the
# `zitadel_*` commands, is exactly what house rule 27's own gate check
# (`quality.checks.zitadel_client`, run every `--loop`) exists to catch — with
# the AST-based recogniser, the correct scope (tests and migrations excluded,
# `quality/rules.yaml`'s own allow-lists honoured) and its own canaries and
# floors. A SECOND, hand-rolled re-implementation of that check belongs here
# only if it can be trusted to match the real one's scope exactly; a first
# draft of one did not (it flagged this file's own probe string, and the
# baseline's `settings.ZITADEL_PAT = "test-pat"` fixture lines in
# `conftest.py`, `test_workflows.py` and `test_zitadel.py`, none of which the
# real check flags, because `SKIP_PARTS` excludes `tests/` from its scope).
# The gate is the authority on this property; `--loop` is where it is proven,
# not a parallel copy here that can drift from it silently.


# --- criterion 4: the drift tripwire -----------------------------------------


def _audit(capsys: Any, *, expect_exit: int = 0) -> str:
    capsys.readouterr()
    if expect_exit == 0:
        call_command("zitadel_audit")
    else:
        with pytest.raises(SystemExit) as exit_info:
            call_command("zitadel_audit")
        assert exit_info.value.code == expect_exit
    return str(capsys.readouterr().out)


def test_with_no_row_the_screen_is_unmanaged_and_not_drift(label: LabelPolicy, capsys: Any) -> None:
    """Nobody ever asked is a different fact from somebody changed it.

    The same distinction `SyncState.UNMANAGED` draws for a connection, and the
    reason the audit does not simply call an unbranded instance drift.
    """
    out = _audit(capsys, expect_exit=0)

    assert "unmanaged   sign-in branding" in out
    assert "DRIFT       sign-in branding" not in out


def test_a_console_repaint_is_reported_as_drift(
    label: LabelPolicy, operator: Any, capsys: Any
) -> None:
    """THE criterion. Somebody edits the screen in the console; the audit says so.

    This is the move house rule 27 says no check can see, made visible by the
    only thing that can see it: a row stating what the screen was supposed to
    look like.
    """
    from apps.accounts.activities import apply_identity_config

    row = services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")
    apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)))

    # …and now somebody opens the console and picks a different colour.
    assert label.custom is not None
    label.custom["primaryColor"] = "#ff00ff"

    out = _audit(capsys, expect_exit=1)

    assert "DRIFT       sign-in branding" in out
    assert "primaryColor" in out
    assert "#3f4a5a" in out
    assert "#ff00ff" in out


def test_an_agreeing_screen_is_reported_as_agreeing(
    label: LabelPolicy, operator: Any, capsys: Any
) -> None:
    """The sibling that stops the clause from being "always drift"."""
    from apps.accounts.activities import apply_identity_config

    row = services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")
    apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)))

    out = _audit(capsys, expect_exit=0)

    assert "agrees      sign-in branding" in out


def test_a_row_against_an_unbranded_org_is_drift(
    label: LabelPolicy, operator: Any, capsys: Any
) -> None:
    """A stated intent and no policy at all: the sync never landed, or was reset.

    Reported rather than passed over, because "we asked for this and Zitadel is
    showing its own default" is precisely the silent state the rung exists to
    end.
    """
    services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")

    out = _audit(capsys, expect_exit=1)

    assert "DRIFT       sign-in branding" in out
    assert "NO label policy of its own" in out


def test_an_unreadable_surface_is_not_called_drift(
    label: LabelPolicy, operator: Any, capsys: Any
) -> None:
    """Could-not-look is not a console edit, and must not send somebody hunting."""
    services.set_identity_branding(actor=operator, tenant=None, accent="#3f4a5a")
    label.readable = False

    out = _audit(capsys, expect_exit=0)

    assert "could not    sign-in branding" in out
    assert "DRIFT       sign-in branding" not in out


# --- the shell door: manage.py zitadel_brand ---------------------------------


def test_the_command_sets_branding_and_starts_the_run(
    operator: Any, owner: Any, tenant: Tenant, capsys: Any
) -> None:
    """The intent-writing half `set_identity_branding` had no caller for.

    Before this command the service had exactly one production caller —
    `apply_identity_config`, recording an OUTCOME — and nothing that could ever
    ask for one. This is that door, the same shape `sync_workforce_idp` is for
    `sync_workforce_identity_config`.
    """
    capsys.readouterr()
    call_command(
        "zitadel_brand",
        "--accent",
        "#0b7285",
        "--product-name",
        "Acme",
        "--as",
        owner.email,
        "--tenant",
        tenant.slug,
    )

    printed = capsys.readouterr().out
    assert "identity branding" in printed
    assert "#0b7285" in printed

    row = IdentityBranding.objects.get(is_active=True)
    assert row.accent == "#0b7285"
    assert row.product_name == "Acme"
    assert row.sync_state == SsoConnection.SyncState.PENDING

    run = WorkflowRun.objects.for_platform().get(type=SYNC_IDENTITY_CONFIG_WORKFLOW)
    assert run.workflow_id.startswith("platform:accounts:identity_config:branding-")


def test_the_command_only_turns_the_watermark_off_never_back_on(operator: Any, owner: Any) -> None:
    """No `--enable-watermark`: a plain flag cannot tell "leave it" from "turn it
    back on", so this one only ever means OFF, and omitting it means "unchanged".
    """
    call_command("zitadel_brand", "--accent", "#111111", "--disable-watermark", "--as", owner.email)
    call_command("zitadel_brand", "--accent", "#222222", "--as", owner.email)

    row = IdentityBranding.objects.get(is_active=True)
    assert row.accent == "#222222"
    assert row.is_watermark_disabled is True


def test_the_command_refuses_an_unknown_tenant_slug(operator: Any, owner: Any) -> None:
    """Optional is not ignored: a named audit anchor that is not there is a refusal."""
    with pytest.raises(CommandError):
        call_command("zitadel_brand", "--accent", "#0b7285", "--tenant", "not-a-tenant")

    assert not IdentityBranding.objects.exists()


def test_the_command_refuses_an_unknown_operator_email(operator: Any) -> None:
    """The same shape: naming somebody who is not there is a refusal, not a no-op."""
    with pytest.raises(CommandError):
        call_command("zitadel_brand", "--accent", "#0b7285", "--as", "nobody@example.com")

    assert not IdentityBranding.objects.exists()


def test_the_command_refuses_a_non_operator(owner: Any) -> None:
    """`identity_platform.configure` is a superuser, not a tenant's owner — an
    ordinary tenant owner asking (an ordinary `User`, not `operator`'s
    superuser) is the same refusal a tenant-scoped door would give.
    """
    with pytest.raises(CommandError):
        call_command("zitadel_brand", "--accent", "#0b7285", "--as", owner.email)

    assert not IdentityBranding.objects.exists()
