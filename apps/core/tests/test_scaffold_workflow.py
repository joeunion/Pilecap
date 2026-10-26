"""`scaffold workflow --until`: the timer form, copied from `workflow.remind` onto a named field."""

# does-not-cover: a `--on` verb other than `update` landing in a product noun; the copy drives one.

from __future__ import annotations

import io
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.scaffold.arms.workflow import FORMS, agent_of, before_of, timer_lines

ROOT = Path(__file__).resolve().parents[3]
#: A field name well past the golden's `due_at`, so a long one is proved to fit the line length.
LABEL, NOUN, FIELD = "trips", "Outing", "scheduled_starts_at"
TIMER = ("--on", "update", "--until", FIELD, "--before", "1h")


def _scaffold(*argv: str) -> str:
    """`manage.py scaffold <argv>`'s standard output."""
    out = io.StringIO()
    call_command("scaffold", *argv, stdout=out)
    return out.getvalue()


def _tracked_product(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """The tracked tree copied whole, namespaced, `.env` beside it; the env its commands run in."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    root = tmp_path / "tree"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert copied.returncode == 0, copied.stderr
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", root / ".env")
    (root / "quality/local").mkdir(parents=True, exist_ok=True)
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: zzzk6w\n")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_NAME": f"djb_timer_{secrets.token_hex(3)}",
        "DATABASE_URL": "",
    }
    return root, env


@pytest.mark.parametrize(
    ("verb", "agent"),
    [
        ("remind", "reminder"),
        ("review", "reviewer"),
        ("notify", "notifier"),
        ("submit", "submitter"),
    ],
)
def test_a_timer_names_its_run_by_who_does_it(verb: str, agent: str) -> None:
    assert agent_of(verb) == agent


@pytest.mark.parametrize(
    ("said", "written"),
    [("2h", "timedelta(hours=2)"), ("30m", "timedelta(minutes=30)"), ("1d", "timedelta(days=1)")],
)
def test_a_lead_is_a_count_and_a_unit(said: str, written: str) -> None:
    assert before_of(said) == written
    assert before_of("soon") == before_of("0h") == ""


def test_a_date_field_says_its_test_moment_as_a_date() -> None:
    line = "    return datetime.now(UTC) + REMIND_BEFORE + timedelta(days=days)"
    said = timer_lines(line, "remind", LABEL, FIELD, "update", kind="date")
    assert said == "    return (datetime.now(UTC) + REMIND_BEFORE + timedelta(days=days)).date()"


def test_both_forms_say_which_fits_and_the_template_rechecks_both() -> None:
    timer = _scaffold(
        "workflow", "example", "Widget", "remind", "--on", "update", "--until", "due_at", "--check"
    )
    wait = _scaffold("workflow", "example", "Widget", "onboard", "--check")
    assert FORMS.format(said="the timer") in timer and "re-inserts line-for-line" in timer
    assert FORMS.format(said="the approval wait") in wait and "re-inserts line-for-line" in wait
    listed = [line for line in _scaffold("--list").splitlines() if line.startswith("workflow ")]
    assert len(listed) == 1 and "[--on <v> --until <field>]" in listed[0], listed


def test_the_timer_shape_refuses_a_wrong_field_or_verb() -> None:
    before = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/example"],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
    ).stdout
    cases = (
        (("--on", "update", "--until", "notes"), "`Widget.notes` is a `TextField`"),
        (("--on", "update", "--until", "nowhere"), "`Widget.nowhere` is no field on it"),
        (("--on", "touch", "--until", "due_at"), "`touch_widget` is not a service of the noun"),
        (("--on", "frobnicate", "--until", "due_at"), "`frobnicate_widget` is not a service"),
        (("--until", "due_at"), "takes both `--on <verb>`"),
        (("--on", "update", "--until", "due_at", "--before", "soon"), "'soon' is no duration"),
    )
    for flags, said in cases:
        with pytest.raises(CommandError) as refused:
            _scaffold("workflow", "example", "Widget", "remind", *flags, "--dry-run")
        assert refused.value.returncode == 2, flags
        assert said in str(refused.value), (flags, str(refused.value))
    after = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/example"],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
    ).stdout
    assert after == before


def test_the_timer_shape_renders_from_the_named_field(tmp_path: Path) -> None:
    root, env = _tracked_product(tmp_path)

    def run(*argv: str, python: tuple[str, ...] = ("manage.py",)) -> str:
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, *python, *argv], cwd=root, env=env, capture_output=True, text=True
        )
        assert done.returncode == 0, (argv, done.stdout[-4000:] + done.stderr[-4000:])
        return done.stdout

    run("newapp", LABEL)
    run("scaffold", "noun", LABEL, NOUN)
    run("scaffold", "field", LABEL, NOUN, f"{FIELD}:datetime?")
    shaped = run("roads", "shape", "workflow", LABEL, NOUN, "remind", *TIMER)
    assert FORMS.format(said="the timer") in shaped, shaped
    assert f"would migrate apps/{LABEL}/migrations/ named outing_reminded_at" in shaped, shaped
    said = run("scaffold", "workflow", LABEL, NOUN, "remind", *TIMER)
    assert f"migration: apps/{LABEL}/migrations/" in said, said
    app = root / "apps" / LABEL
    copied = {rel: (app / rel).read_text() for rel in ("workflows.py", "activities.py")}
    assert "REMIND_BEFORE = timedelta(hours=1)" in copied["workflows.py"]
    assert '@workflow.defn(name="OutingReminderWorkflow")' in copied["workflows.py"]
    assert f'@activity.defn(name="read_outing_{FIELD}"' in copied["activities.py"]
    services = (app / "services.py").read_text()
    update = services.index("def update_outing(")
    assert services.index("_remind_outing_on_commit(", update) < services.index(
        "    return locked\n\n", update
    )
    tests = (app / "tests/test_workflows.py").read_text()
    timer = "".join(
        (app / rel).read_text() for rel in (*copied, "types.py", "tests/test_workflows.py")
    )
    assert "due_at" not in timer and "Widget" not in timer and "onboard" not in timer.lower()
    assert tests.count("\nasync def test_") == 5, tests
    linted = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; no shell
        [str(Path(sys.executable).parent / "ruff"), "check", f"apps/{LABEL}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert linted.returncode == 0, linted.stdout + linted.stderr
    tested = run(
        f"apps/{LABEL}/tests/test_workflows.py",
        "-q",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        python=("-m", "pytest"),
    )
    assert "5 passed" in tested, tested


def test_the_approval_wait_copies_the_door_that_ends_it(tmp_path: Path) -> None:
    """A wait on `approve` with nothing that sends it ends unapproved: the door rides along."""
    root, env = _tracked_product(tmp_path)

    def run(*argv: str, python: tuple[str, ...] = ("manage.py",)) -> str:
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, *python, *argv], cwd=root, env=env, capture_output=True, text=True
        )
        assert done.returncode == 0, (argv, done.stdout[-4000:] + done.stderr[-4000:])
        return done.stdout

    run("newapp", LABEL)
    run("scaffold", "noun", LABEL, NOUN)
    said = run("scaffold", "workflow", LABEL, NOUN, "germinate")
    assert "door: POST /{id}/approve/ (`outing-approve`)" in said, said
    app = root / "apps" / LABEL
    services = (app / "services.py").read_text()
    assert "def approve_outing(" in services and "signal=OUTING_APPROVAL_SIGNAL" in services
    assert 'url_name="outing-approve"' in (app / "api.py").read_text()
    assert '@server.tool(name="approve_outing"' in (app / "mcp.py").read_text()
    policies = (app / "policies.py").read_text()
    assert '"outing.approve": may_archive,' in policies and "can_approve" not in policies
    assert '@workflow.signal(name="approve")' in (app / "workflows.py").read_text()
    tested = run(
        f"apps/{LABEL}/tests/test_api.py",
        "-q",
        "-k",
        "approv",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        python=("-m", "pytest"),
    )
    assert "9 passed" in tested, tested
    swept = run(
        f"apps/{LABEL}/tests/test_noun_authz.py",
        "-q",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        python=("-m", "pytest"),
    )
    assert " passed" in swept and "failed" not in swept, swept
    assert f"baseline: apps/{LABEL}/tests/outing_authz_baseline.json moved" in said, said
    assert "added outing.approve" in said, said
