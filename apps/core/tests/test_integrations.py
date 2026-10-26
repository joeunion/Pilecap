"""The census, and the one criterion that keeps it honest.

The owner's line, verbatim: *adding a new integration in any future rung appears
at all four surfaces with NO edit to any list.* Everything else about this
instrument is nice to have; that is the property, and it is the one that would
fail silently — a census that quietly needed a list edit would keep passing, and
the integration nobody edited it for would simply be missing from every report.

So the tooth is two halves and both are derived:

* **No surface holds a list.** Each of the four is read as text and must both
  reach `census()` and spell NO integration key of its own. The keys are taken
  from the live census rather than typed, so an integration added tomorrow is in
  the assertion tomorrow.
* **A planted integration arrives everywhere.** `apps/core/tests/integrations.py`
  is a real module with a real `register`, discovered through the production
  walk, and it must appear in the census, in the command, in the wall's refusal
  and in the prober's answer — with nothing in this repository edited to admit
  it beyond the module's own existence.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from apps.core import integrations as integrations_module
from apps.core.activities import probe_integrations
from apps.core.integrations import (
    Census,
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
    census,
)
from apps.core.tests.integrations import PLANTED

#: The four surfaces the owner's charge names, each as the file that IS it.
#: Named here because this test is the only place that has to know all four; no
#: surface knows about another, which is the property being protected.
SURFACES: dict[str, Path] = {
    "the setup epilogue": Path(settings.BASE_DIR) / "scripts" / "setup.sh",
    "manage.py integrations": (
        Path(settings.BASE_DIR) / "apps" / "core" / "management" / "commands" / "integrations.py"
    ),
    "the deploy wall": Path(settings.BASE_DIR) / "deploy" / "release.sh",
    "the standing prober": Path(settings.BASE_DIR) / "apps" / "core" / "activities.py",
}


#: The module the plant lives in. Pointed at through `declaring_modules`, which
#: is the walk's own seam — NOT by doubling `get_app_configs()`, which Django
#: also uses to find management commands and which it CACHES, so a doubled
#: registry escapes the test that did it and breaks the next one to run a
#: command. Found while writing this file, and recorded in `declaring_modules`.
PLANT_MODULE = "apps.core.tests.integrations"


@pytest.fixture
def planted(monkeypatch: pytest.MonkeyPatch) -> Census:
    """The production walk, pointed at one real module with a real `register`.

    `find_spec`, `import_module` and `register(registry)` are all untouched, so
    what is proven is the machinery and not a double of it.
    """
    monkeypatch.setattr(integrations_module, "declaring_modules", lambda: [PLANT_MODULE])
    return census()


# --- half one: no surface holds a list ---------------------------------------


def test_all_four_surfaces_exist_and_are_the_ones_the_charge_names() -> None:
    """A surface that quietly stopped existing would take its half of the
    criterion with it, and every remaining assertion would still pass."""
    missing = sorted(name for name, path in SURFACES.items() if not path.is_file())
    assert missing == [], missing


#: How a surface of each kind READS the census. Not the word "integrations" —
#: `step "integrations"` is a heading, and a heading over a body that reads
#: nothing was enough to satisfy the first version of this test while the
#: surface underneath it had been deleted (planted, and watched to pass).
_READER = {".sh": "manage.py integrations", ".py": "census"}


def _executable(path: Path) -> str:
    """A shell surface with its COMMENTS STRIPPED. The prose does not count.

    Found by planting this file's own severed-surface case and watching it pass:
    the comment above `setup.sh`'s epilogue explains the census and, in doing so,
    spells the invocation — so an assertion that merely searched the file was
    satisfied by a sentence ABOUT the surface after the surface itself had been
    deleted. That is the phantom-registration shape the house has been bitten by
    before — prose spelling a censused marker — arriving here as a tooth
    with no jaw.

    Python surfaces are read whole and deliberately: a docstring that listed
    integration keys IS a second list — it is what a reader believes — and the
    key half of this test should see one.
    """
    text = path.read_text()
    if path.suffix != ".sh":
        return text
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_every_surface_reads_the_census_rather_than_a_list_of_its_own() -> None:
    """The whole criterion, as an absence.

    A surface that spelled an integration key would be a second list — and the
    second list is the one that goes stale, because the first one is the one
    somebody remembers to edit. The keys are DERIVED from the live census, so
    this keeps meaning what it says as the census grows.
    """
    keys = {row.key for row in census().integrations}
    assert keys, "the census is empty; this test would pass vacuously"

    for name, path in SURFACES.items():
        text = path.read_text()
        assert _READER[path.suffix] in _executable(path), (
            f"{name} does not reach the census at all — it must name "
            f"{_READER[path.suffix]!r}. A heading that says `integrations` over a body "
            "that reads nothing is the surface having been deleted with its label left "
            "behind, which is how the first version of this assertion passed."
        )
        spelled = sorted(key for key in keys if key in text)
        assert spelled == [], (
            f"{name} ({path.name}) spells the integration key(s) {spelled}. That is a "
            "second list, and a new integration would reach the census and not this "
            "surface. Read `apps.core.integrations.census()` instead."
        )


def test_the_two_shell_surfaces_invoke_the_command_rather_than_reimplement_it() -> None:
    """`setup.sh` and `release.sh` cannot import Python, so this is how they read
    the census — and the wall is the one that carries `--wall`, because a first
    afternoon on a laptop is supposed to be standing on some fakes."""
    setup = _executable(SURFACES["the setup epilogue"])
    release = _executable(SURFACES["the deploy wall"])

    assert "manage.py integrations" in setup
    assert "manage.py integrations --wall" not in setup
    assert "manage.py integrations --wall" in release


# --- half two: a planted integration arrives everywhere ----------------------


def test_the_planted_integration_reaches_the_census(planted: Census) -> None:
    """The production walk, over a real module, with only its target repointed."""
    found = {row.key: row for row in planted.integrations}
    assert PLANTED.key in found
    assert found[PLANTED.key].status is IntegrationStatus.FAKE
    assert found[PLANTED.key].declared_by == "apps/core/tests/integrations.py"


def test_the_platform_declares_its_own_beside_the_planted_one(planted: Census) -> None:
    """The walk does not replace the platform seam, it adds to it.

    Without this, a plant that happened to shadow the platform's declarations
    would leave every other assertion here passing over a census of one row.
    """
    keys = {row.key for row in planted.integrations}
    assert "outbound-email" in keys


def test_the_command_reports_the_planted_integration_and_its_remedy(planted: Census) -> None:
    """Surface two, driven. The remedy travels with the row: a report that says
    something is missing and not what to type sends a person to the source."""
    out, err = StringIO(), StringIO()
    call_command("integrations", stdout=out, stderr=err)
    printed = out.getvalue()

    assert PLANTED.key in printed
    assert PLANTED.detail in printed
    assert PLANTED.remedy in printed


def test_the_wall_refuses_on_the_planted_integration(planted: Census) -> None:
    """Surface three's verdict. Exit 1: something is a fake, and it is named."""
    out, err = StringIO(), StringIO()
    with pytest.raises(SystemExit) as refusal:
        call_command("integrations", "--wall", stdout=out, stderr=err)

    assert refusal.value.code == 1
    assert PLANTED.key in err.getvalue()


@pytest.mark.django_db
def test_the_prober_answers_with_the_planted_integration(planted: Census) -> None:
    """Surface four. The activity's return value is the run's own report, so a
    planted integration is visible in the Temporal UI without a log search.

    `django_db` because the activity brackets its work with
    `close_old_connections()` at both ends — the house form for a sync activity,
    kept even though the platform seam queries nothing, because an app's own
    `register` may well read a `Connection` row to answer for a per-tenant
    credential.
    """
    assert probe_integrations()[PLANTED.key] == IntegrationStatus.FAKE.value


# --- the operator's acceptance, per key, against the live census ---------------
#
# THE RULING THIS DRIVES. "Silent fakes pass if declared" was rejected: every
# census-visible fake is declared BY CONSTRUCTION —
# `providers.DeclaresFakeness` is the only way fakeness reaches this census — so
# scoping the wall to "silent" fakes would delete it while keeping its name. What
# an operator gets instead is narrower and louder: **one named key at a time, and
# only a key that is FAKE right now**, announced on every release forever.
#
# The four properties below are the whole of what keeps that honest, and each one
# is the thing that would rot first if it were only in somebody's memory:
# per-key enumeration against the LIVE census (a new fake refuses again), a stale
# acceptance refusing rather than passing, exit 2 outranking an acceptance, and
# the report's own rows never learning the word.


@pytest.fixture
def real_mail(settings: Any) -> None:
    """Mail that leaves the process, so `outbound-email` is the CONFIGURED row.

    The test settings run a stand-in backend, which is correct for a test suite
    and makes the platform's own row FAKE — so without this every acceptance case
    below would be driving a census with a second unaccepted fake in it and
    refusing for a reason it never named.
    """
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


@pytest.fixture
def one_fake(real_mail: None, monkeypatch: pytest.MonkeyPatch) -> Census:
    """The plant's FAKE row beside the platform's CONFIGURED one, and nothing else."""
    monkeypatch.setattr(integrations_module, "declaring_modules", lambda: [PLANT_MODULE])
    return census()


@pytest.fixture
def three_statuses(real_mail: None, monkeypatch: pytest.MonkeyPatch) -> Census:
    """A census with one row of each status, through the production walk.

    `planted-telegraph` is FAKE, the platform seam's `outbound-email` is
    CONFIGURED, and `apps/search` declares NOT_CONFIGURED the moment its master
    key is empty — which is a real deployment state and not a double. All three
    reach the registry through `declaring_modules` → `import_module` →
    `register`, so what the acceptance is enumerated against is the census, not a
    stand-in for it.
    """
    from apps.search import engine as engine_module

    monkeypatch.setattr(engine_module, "meili_master_key", lambda: "")
    monkeypatch.setattr(
        integrations_module,
        "declaring_modules",
        lambda: [PLANT_MODULE, "apps.search.integrations"],
    )
    return census()


def _statuses(report: Census) -> dict[str, IntegrationStatus]:
    return {row.key: row.status for row in report.integrations}


def test_the_three_statuses_fixture_is_the_census_it_claims_to_be(
    three_statuses: Census,
) -> None:
    """Without this the acceptance cases below could each pass for the wrong
    reason — an absent key refuses exactly as a CONFIGURED one does."""
    assert _statuses(three_statuses) == {
        "outbound-email": IntegrationStatus.CONFIGURED,
        "planted-telegraph": IntegrationStatus.FAKE,
        "search-index": IntegrationStatus.NOT_CONFIGURED,
    }


def test_accepting_a_fake_key_lets_the_wall_pass_and_announces_it(one_fake: Census) -> None:
    """(a) The one case the flag exists for, and the loudness is half of it.

    A release that stood on an accepted fake and said nothing would be the
    silent-fake failure wearing a permission slip. The detail and the remedy
    travel with the announcement for the same reason every other refusal in this
    census carries them: whoever reads it must not have to go to the source.
    """
    out, err = StringIO(), StringIO()
    call_command("integrations", "--wall", "--accept-fake", PLANTED.key, stdout=out, stderr=err)
    printed = out.getvalue()

    assert "ACCEPTED FAKE" in printed
    assert PLANTED.key in printed
    assert PLANTED.detail in printed
    assert PLANTED.remedy in printed


def test_accepting_a_configured_key_is_refused_because_it_is_stale(
    three_statuses: Census,
) -> None:
    """(b) A key that became real is an acceptance nobody deleted.

    The dangerous shape is the opposite of the obvious one: an acceptance that
    quietly kept passing after the integration went real is a slot the operator
    believes is guarded and is not — the next fake to arrive under that key would
    walk straight through. So it refuses, and the fix it names is `delete`.
    """
    err = StringIO()
    with pytest.raises(SystemExit) as refusal:
        call_command(
            "integrations",
            "--wall",
            "--accept-fake",
            "outbound-email",
            stdout=StringIO(),
            stderr=err,
        )
    assert refusal.value.code == 1
    assert "outbound-email" in err.getvalue()
    assert "delete" in err.getvalue().lower()


def test_accepting_a_not_configured_key_is_refused_because_it_is_an_absence(
    three_statuses: Census,
) -> None:
    """(b) You cannot accept an absence. Nothing is standing in for it."""
    err = StringIO()
    with pytest.raises(SystemExit) as refusal:
        call_command(
            "integrations",
            "--wall",
            "--accept-fake",
            "search-index",
            stdout=StringIO(),
            stderr=err,
        )
    assert refusal.value.code == 1
    assert "search-index" in err.getvalue()


def test_accepting_a_key_no_census_row_carries_is_refused(three_statuses: Census) -> None:
    """(b) A typo must not be a wider wall.

    `--accept-fake comms-chanel-sms` that silently accepted nothing would leave
    the operator believing a fake was acknowledged and the release refusing for a
    reason they had already answered.
    """
    err = StringIO()
    with pytest.raises(SystemExit) as refusal:
        call_command(
            "integrations",
            "--wall",
            "--accept-fake",
            "no-such-integration",
            stdout=StringIO(),
            stderr=err,
        )
    assert refusal.value.code == 1
    assert "no-such-integration" in err.getvalue()


def test_an_acceptance_covers_its_own_key_and_no_other(three_statuses: Census) -> None:
    """Per-key enumeration, which is what makes a NEW fake refuse again.

    The property the ruling rests on: acceptance is not a mode. One key is
    acknowledged; everything else in the census is still a wall, and the refusal
    names the row that is still standing rather than the one that was answered.
    """
    err = StringIO()
    with pytest.raises(SystemExit) as refusal:
        call_command(
            "integrations",
            "--wall",
            "--accept-fake",
            PLANTED.key,
            stdout=StringIO(),
            stderr=err,
        )
    assert refusal.value.code == 1
    refusal_text = err.getvalue()
    assert "search-index" in refusal_text
    assert PLANTED.key not in refusal_text


def test_an_acceptance_never_turns_an_unreadable_seam_into_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) Exit 2 outranks everything, acceptance included.

    An operator can acknowledge a fake they have LOOKED at. Nobody can acknowledge
    a seam that would not answer — that is "I could not look", and an acceptance
    that flattened it into "it is fine" would be this instrument reporting a green
    deployment during an outage of its own probe.
    """
    import apps.core.tests.integrations as plant

    def explode(registry: IntegrationRegistry) -> None:
        raise RuntimeError("the telegraph office is closed")

    monkeypatch.setattr(integrations_module, "declaring_modules", lambda: [PLANT_MODULE])
    monkeypatch.setattr(plant, "register", explode)

    with pytest.raises(SystemExit) as refusal:
        call_command(
            "integrations",
            "--wall",
            "--accept-fake",
            PLANTED.key,
            stdout=StringIO(),
            stderr=StringIO(),
        )
    assert refusal.value.code == 2


def test_the_census_report_is_byte_identical_with_and_without_an_acceptance(
    one_fake: Census,
) -> None:
    """(d) The other three surfaces keep saying FAKE, and so does this one.

    An acceptance is the DEPLOY's verdict, not the census's finding. The moment a
    row learned the word, `scripts/setup.sh`'s epilogue, the standing prober and
    this report would start describing a deployment as less fake than it is — and
    the thing an operator accepted would stop being visible as a thing.
    """
    bare, accepting = StringIO(), StringIO()
    call_command("integrations", stdout=bare, stderr=StringIO())
    call_command("integrations", "--accept-fake", PLANTED.key, stdout=accepting, stderr=StringIO())
    assert bare.getvalue() == accepting.getvalue()
    assert "ACCEPTED FAKE" not in bare.getvalue()


def test_the_same_key_accepted_twice_is_one_acceptance(one_fake: Census) -> None:
    """`DJB_ACCEPTED_FAKES` is a hand-maintained string in a vault slot, so a
    repeated key is a typo and not a second opinion. It announces once."""
    out = StringIO()
    call_command(
        "integrations",
        "--wall",
        "--accept-fake",
        PLANTED.key,
        "--accept-fake",
        PLANTED.key,
        stdout=out,
        stderr=StringIO(),
    )
    assert out.getvalue().count("ACCEPTED FAKE") == 1


# --- the instrument checklist's own lines ------------------------------------


def test_an_unreadable_seam_is_reported_as_unreadable_and_not_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "I could not look" is not "I looked and it is not there".

    The whole reason the census returns two collections. A seam that raised must
    not shrink the report to a shorter one that looks complete — that is the
    shape in which an instrument reports a green deployment during an outage of
    its own probe.
    """
    import apps.core.tests.integrations as plant

    def explode(registry: IntegrationRegistry) -> None:
        raise RuntimeError("the telegraph office is closed")

    monkeypatch.setattr(integrations_module, "declaring_modules", lambda: [PLANT_MODULE])
    monkeypatch.setattr(plant, "register", explode)

    report = census()
    assert not report.is_readable
    assert [seam.module for seam in report.unreadable] == ["apps.core.tests.integrations"]
    assert "telegraph office is closed" in report.unreadable[0].reason
    # And the readable half is still reported, rather than withheld.
    assert {row.key for row in report.integrations} == {"outbound-email"}


def test_an_unreadable_seam_is_exit_2_with_or_without_the_wall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit 2 outranks every other verdict, and it is not a `--wall` opinion.

    The gate's own semantics (`CLAUDE.md`) and `scripts/goalpost_scan.py`'s:
    2 is enforcement broken, and a command that answered 0 because nobody asked
    it to be strict would be reporting a census it did not take.
    """
    import apps.core.tests.integrations as plant

    def explode(registry: IntegrationRegistry) -> None:
        raise RuntimeError("the telegraph office is closed")

    monkeypatch.setattr(integrations_module, "declaring_modules", lambda: [PLANT_MODULE])
    monkeypatch.setattr(plant, "register", explode)

    for argv in ([], ["--wall"]):
        with pytest.raises(SystemExit) as refusal:
            call_command("integrations", *argv, stdout=StringIO(), stderr=StringIO())
        assert refusal.value.code == 2


def test_a_status_that_is_not_configured_must_name_a_remedy() -> None:
    """Refused at construction, which is the tier the rest of this tree uses.

    A row that says something is missing and does not say what to type is the
    instrument checklist's named failure, and catching it at gate time would
    mean catching it after it had shipped.
    """
    with pytest.raises(ValueError, match="names no remedy"):
        Integration(
            key="silent",
            title="Silent",
            status=IntegrationStatus.NOT_CONFIGURED,
            detail="something is missing and this row will not say what to do.",
        )


def test_a_probe_word_outside_the_closed_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError, match="the vocabulary is"):
        Integration(
            key="vague",
            title="Vague",
            status=IntegrationStatus.CONFIGURED,
            detail="probed, sort of.",
            probe="partially",
        )


def test_two_apps_declaring_one_integration_differently_is_refused() -> None:
    """Import order is not a way to settle whether something is configured."""
    registry = IntegrationRegistry()
    registry.declare(PLANTED, source="apps.first.integrations")
    with pytest.raises(ValueError, match="was already declared by"):
        registry.declare(
            Integration(
                key=PLANTED.key,
                title=PLANTED.title,
                status=IntegrationStatus.CONFIGURED,
                detail="the other app is sure this one is real.",
            ),
            source="apps.second.integrations",
        )


# --- the platform's own two rows ---------------------------------------------


def test_the_platform_declares_only_what_no_app_can(planted: Census) -> None:
    """A structural boundary, held as an assertion.

    The charge named five seams; `apps/core` can declare none of them, because
    rule 48 fences the bucket, rule 33 fences the search engine, rule 27 fences
    the identity door, and the layer contract puts both registries above `core`.
    So the platform seam is one row — mail — and the other five are owed by the
    apps that own them.

    This asserts the boundary rather than the shortfall: if a future rung teaches
    `core` to declare somebody else's integration, it has gone around a house
    rule, and this is where that shows up.
    """
    platform = {
        row.key for row in planted.integrations if row.declared_by == "apps/core/integrations.py"
    }
    assert platform == {"outbound-email"}, (
        f"the platform seam declares {sorted(platform)}. Everything but the mail "
        "transport belongs to the app that owns it — rules 27, 33 and 48 and the "
        "layer contract each say so about one of them."
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
def test_the_console_mail_backend_is_the_fake_a_production_deploy_must_not_have() -> None:
    """The wall's most valuable single catch.

    A production release still carrying the console backend accepts every
    password reset and prints it to a log. It is not a missing feature; it is a
    silent one, which is the class this census exists for.
    """
    row = next(r for r in census().integrations if r.key == "outbound-email")
    assert row.status is IntegrationStatus.FAKE
    assert "never reaches anybody" in row.detail

    with pytest.raises(SystemExit) as refusal:
        call_command("integrations", "--wall", stdout=StringIO(), stderr=StringIO())
    assert refusal.value.code == 1


def test_the_census_declares_what_it_cannot_see() -> None:
    """The instrument checklist's line: the census declares its `does_not_cover`.

    Held as an assertion because a blind spot that is only in somebody's memory
    is a blind spot the next reader will not know about — and because the wall
    is a refusal, whoever is refused by it deserves to know what a clean report
    would still not have covered.
    """
    from apps.core import integrations as module

    doc = module.__doc__ or ""
    assert "What it cannot see" in doc
    for expected in ("misdeclares itself as real", "Probe depth varies", "readyz"):
        assert expected in doc, expected

    command_doc = _command_docstring()
    assert "What it cannot see" in command_doc


def _command_docstring() -> str:
    import apps.core.management.commands.integrations as command_module

    return command_module.__doc__ or ""


def test_the_prober_is_a_schedule_and_not_a_cron_line() -> None:
    """Anything periodic is a `ScheduleDeclaration` (the standing rule), which is
    also what puts the prober inside rule 31's reachability walk for free."""
    from apps.core.activities import SCHEDULES
    from apps.workflows.client import discovered_schedules

    assert [declaration.name for declaration in SCHEDULES] == ["core.probe-integrations"]
    assert "core.probe-integrations" in {d.name for d in discovered_schedules()}


def test_the_probers_workflow_id_is_deterministic_and_per_queue() -> None:
    """House rule 18. Two workers in one deployment derive the same id, so the
    second to ask is told the probe is already happening."""
    from apps.core.activities import PROBE_INTEGRATIONS

    def run_id(queue: str) -> str:
        return str(PROBE_INTEGRATIONS.schedule(queue).action.id)  # type: ignore[attr-defined]

    assert run_id("q") == run_id("q")
    assert run_id("q") != run_id("other")
    assert run_id("q") == PROBE_INTEGRATIONS.schedule_id("q") == "platform:core:integrations:q"


def test_the_prober_owns_no_run(monkeypatch: Any) -> None:
    """Rule 28's second population: a schedule started it and no service asked."""
    from apps.core.workflows import ProbeIntegrationsWorkflow

    assert ProbeIntegrationsWorkflow.owns_no_run is True


# --- the prober survives the thing it probes (wave 3) -------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_prober_completes_and_says_so_when_the_census_cannot_be_read() -> None:
    """**A rot detector must not die of the rot.**

    The defect this pins was found by
    `apps/workflows/tests/test_machinery_lifetime.py::test_the_sweeps_still_run_from_a_live_worker`
    — the live-worker organ test that drives every declared machine — and it was
    latent in production, not merely in the harness: the census contacts things
    outside this process, so a black-holed endpoint does not raise, it HANGS.
    The activity then died of its own `start_to_close_timeout` and took the run
    with it, which is exactly backwards: the run row said `failed`, no census
    was produced, and the outage the probe existed to notice became the reason
    nothing was noticed.

    So the run must COMPLETE and carry the bad news. Driven with a fake activity
    that refuses, which is the conventions' form for workflow decision logic —
    what is under test is the workflow's choice, not the census.
    """
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from apps.core.workflows import PROBE_ACTIVITY, ProbeIntegrationsWorkflow

    @activity.defn(name=PROBE_ACTIVITY)
    async def refusing_probe() -> dict[str, str]:
        raise RuntimeError("the bucket never answered")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="prober-refusal",
            workflows=[ProbeIntegrationsWorkflow],
            activities=[refusing_probe],
        ):
            outcome = await env.client.execute_workflow(
                ProbeIntegrationsWorkflow.run,
                id="prober-refusal-1",
                task_queue="prober-refusal",
            )

    assert outcome.statuses == {}
    assert not outcome.is_complete
    assert "the bucket never answered" in outcome.incomplete, (
        "the run completed but says nothing about WHY it could not look. "
        "Temporal's wrapper alone is `Activity task failed`, which is true and "
        "useless six weeks later — `reason_of` walks the cause chain for this."
    )
    assert " <- " in outcome.incomplete, outcome.incomplete


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_prober_carries_the_census_when_it_can_be_read() -> None:
    """The other half, so the test above cannot pass by the run always failing."""
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from apps.core.workflows import PROBE_ACTIVITY, ProbeIntegrationsWorkflow

    @activity.defn(name=PROBE_ACTIVITY)
    async def answering_probe() -> dict[str, str]:
        return {"outbound-email": "configured"}

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="prober-answer",
            workflows=[ProbeIntegrationsWorkflow],
            activities=[answering_probe],
        ):
            outcome = await env.client.execute_workflow(
                ProbeIntegrationsWorkflow.run,
                id="prober-answer-1",
                task_queue="prober-answer",
            )

    assert outcome.is_complete
    assert outcome.statuses == {"outbound-email": "configured"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_prober_completes_even_when_no_worker_ever_takes_the_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure that was actually observed, pinned.

    Not "the activity failed" — **the activity was never STARTED**: history
    ending at `activity_task_scheduled`, the execution still RUNNING, the client
    giving up. `start_to_close_timeout` cannot see that state, because it does
    not begin until a worker picks the task up; with `schedule_to_start` unset
    and therefore infinite, the run waits for ever on a queue nobody serves.

    Driven by running the workflow with **no matching activity registered at
    all**, which is that state exactly. `schedule_to_close_timeout` is the
    deadline that ends it, and the run completes saying it could not look.
    """
    from datetime import timedelta

    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    from apps.core import workflows as core_workflows
    from apps.core.workflows import ProbeIntegrationsWorkflow

    # The production deadline is two minutes, and waiting it out would make this
    # module a two-minute test — the time-skipping server does not skip an
    # activity deadline while a worker is polling. So the DEADLINE is shortened
    # and the BEHAVIOUR is unchanged: what is under test is that a deadline
    # exists and that the run completes when it fires, not its length. The
    # unsandboxed runner is what lets the patch reach the workflow, which
    # otherwise re-imports its module.
    monkeypatch.setattr(core_workflows, "PROBE_DEADLINE", timedelta(seconds=2))

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="prober-unserved",
            workflows=[ProbeIntegrationsWorkflow],
            activities=[],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            outcome = await env.client.execute_workflow(
                ProbeIntegrationsWorkflow.run,
                id="prober-unserved-1",
                task_queue="prober-unserved",
            )

    assert not outcome.is_complete
    assert outcome.statuses == {}
    assert outcome.incomplete, "the run completed but does not say it could not look"


def test_the_prober_asks_again_next_tick_rather_than_retrying_inside_one_run() -> None:
    """One attempt, and the schedule is the retry.

    Three attempts inside one run all measure the same half-minute: three
    timeouts to learn one fact. A probe that could not read the world at 06:00
    says so and asks again at 12:00.
    """
    from apps.core.workflows import PROBE_RETRY

    assert PROBE_RETRY.maximum_attempts == 1
