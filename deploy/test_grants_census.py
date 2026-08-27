"""The census that keeps `grants.sql.py` honest about the population.

    uv run pytest deploy/test_grants_census.py

**Run by NAME, not by discovery**, exactly as `perf/measure_*.py` is (ADR
perf-1's boundary): `testpaths = ["apps"]` in `pyproject.toml`, so nothing
under `deploy/` is collected by the default suite, by `--loop`, or by a stray
`uv run pytest`. That is deliberate — the gate measures the product, and the
deployment's own instruments are run at the moment the deployment is built.
The runbook's release section names this command, so it runs where its answer
matters.

WHAT IT IS FOR. `grants.sql.py` claims to emit one REVOKE for every model that
declared `append_only = True`. The claim is only worth something if something
would notice it going wrong — a model declared after this was written, a
refactor that turned the registry scan into a list, a `managed = False` that
quietly dropped a member. So the assertion is made against the REGISTRY, from
the other end: parse the SQL this script actually printed, and compare the set
of tables it revoked on to the set of tables `core.models.append_only_models()`
discovers. Not a spot check on `AuditEntry`; the whole population, both ways.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

HERE = Path(__file__).resolve().parent

# `grants.sql.py` is not an importable module name — the dot in `grants.sql` is
# a package separator to Python, and the file is named for the artifact it
# produces (the pre-declared lexicon). Loading it by path is the whole of the
# workaround, and it is the same trick a build script gets loaded with anywhere.
GRANTS_PATH = HERE / "grants.sql.py"

# `REVOKE UPDATE, DELETE ON "public"."core_auditentry" FROM "djb_app";`
REVOKE = re.compile(
    r'^REVOKE\s+(?P<privileges>[A-Z, ]+?)\s+ON\s+"(?P<schema>[^"]+)"\."(?P<table>[^"]+)"'
    r'\s+FROM\s+"(?P<role>[^"]+)";$'
)
GRANT_ALL_TABLES = re.compile(
    r'^GRANT\s+(?P<privileges>[A-Z, ]+?)\s+ON ALL TABLES IN SCHEMA\s+"(?P<schema>[^"]+)"'
    r'\s+TO\s+"(?P<role>[^"]+)";$'
)


@pytest.fixture(scope="module")
def grants() -> ModuleType:
    """The emitter, loaded from its path. It calls no `django.setup()` at import.

    That is a property worth stating: `main()` does the bootstrap and `render()`
    is pure, which is why this test can drive it inside a pytest process that is
    already configured rather than shelling out and parsing a subprocess.
    """
    spec = importlib.util.spec_from_file_location("djb_deploy_grants", GRANTS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revoked_tables(sql: str) -> set[str]:
    return {m.group("table") for line in sql.splitlines() if (m := REVOKE.match(line))}


def test_the_revoked_set_is_exactly_the_declared_population(grants: ModuleType) -> None:
    """The census, in both directions.

    A member missing is a ledger the database will happily let somebody rewrite.
    A non-member present is a table the application can no longer update — an
    outage, arriving at the release step of a deploy, which is the worst
    possible moment to discover a typo in a hand-written list.
    """
    from apps.core.models import append_only_models

    declared = {
        model._meta.db_table
        for model in append_only_models()
        if model._meta.managed and not model._meta.proxy
    }

    sql = grants.render(role="djb_app")
    revoked = _revoked_tables(sql)

    assert revoked == declared, (
        "deploy/grants.sql.py and core.models.append_only_models() disagree about "
        f"the append-only population. Only in the SQL: {sorted(revoked - declared)}. "
        f"Only in the registry: {sorted(declared - revoked)}."
    )


def test_the_population_is_not_empty(grants: ModuleType) -> None:
    """Green-because-empty is not a pass — the gate's own floor discipline.

    `AuditEntry` is the first member and has been since rule 20 was written. A
    census that passed over an empty set would pass just as loudly the day the
    registry scan silently returned nothing, which is the failure this belt is
    least likely to survive and most likely to hide.
    """
    from apps.core.audit import AuditEntry

    sql = grants.render(role="djb_app")
    revoked = _revoked_tables(sql)

    assert revoked, "no REVOKE was emitted at all; the population scan found nothing"
    assert AuditEntry._meta.db_table in revoked


def test_a_newly_declared_ledger_appears_with_no_edit_here(
    grants: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole design is for, planted the way a canary is.

    A fake model is pushed through the same scan the emitter reads, and the
    emitter must produce its REVOKE without anybody having touched
    `grants.sql.py`, this file, or `rules.yaml`. If this ever fails, the
    population has quietly become a list again.
    """

    class _Meta:
        db_table = "product_ledgerentry"
        managed = True
        proxy = False

    class _FutureLedger:
        _meta = _Meta()
        append_only = True

    from apps.core import models as core_models

    real = core_models.append_only_models
    monkeypatch.setattr(core_models, "append_only_models", lambda: [*real(), _FutureLedger])

    revoked = _revoked_tables(grants.render(role="djb_app"))
    assert "product_ledgerentry" in revoked


def test_the_grant_is_the_complement_of_the_revoke(grants: ModuleType) -> None:
    """SELECT and INSERT survive; UPDATE and DELETE do not.

    Stated as a test because the two lists live in two constants and a belt
    that revoked SELECT would make the audit trail unreadable rather than
    unwritable — a failure that looks like a permissions bug for a week.
    """
    sql = grants.render(role="djb_app")

    grant_line = next(m for line in sql.splitlines() if (m := GRANT_ALL_TABLES.match(line)))
    granted = {p.strip() for p in grant_line.group("privileges").split(",")}
    assert granted == {"SELECT", "INSERT", "UPDATE", "DELETE"}

    revoke_line = next(m for line in sql.splitlines() if (m := REVOKE.match(line)))
    revoked = {p.strip() for p in revoke_line.group("privileges").split(",")}
    assert revoked == {"UPDATE", "DELETE"}
    assert granted - revoked == {"SELECT", "INSERT"}


def test_the_sql_is_deterministic(grants: ModuleType) -> None:
    """Two runs, one tree, byte-identical output.

    No timestamp, no hostname, no set iteration order leaking through. The
    release step diffs this against what it applied last time; a file that
    changed every run would make that diff worthless.
    """
    assert grants.render(role="djb_app") == grants.render(role="djb_app")


def test_the_role_is_quoted_not_interpolated(grants: ModuleType) -> None:
    """A role name with a quote in it cannot end the statement.

    Nobody will name a role `a"b`, which is exactly why nobody would notice the
    escaping being wrong until the day somebody did.
    """
    sql = grants.render(role='a"b')
    assert 'TO "a""b";' in sql
    assert 'FROM "a""b";' in sql
