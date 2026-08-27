#!/usr/bin/env python
"""The belt, at the only layer that cannot be talked out of it: the database.

    python deploy/grants.sql.py --role djb_app > grants.sql
    psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f grants.sql

House rule 20 says an append-only model may have rows created and nothing
anywhere updates or deletes one, and the gate proves that about the CODE — the
services, the doors, the admin. What the gate cannot see is a shell. `manage.py
shell`, a psql session, a library that reaches past the ORM: every one of them
is outside every check in `quality/`, and a ledger that only holds while
everybody uses the front door is not a ledger.

So the deployment revokes the privilege. The app's database role gets SELECT,
INSERT, UPDATE and DELETE on the schema, and then loses UPDATE and DELETE on
exactly the append-only tables. After that an `UPDATE core_auditentry` is not a
policy violation somebody has to notice; it is an error Postgres returns.

**THE POPULATION IS READ, NEVER TYPED.** `core.models.append_only_models()`
discovers every model that declared `append_only = True`, and this script emits
one REVOKE per member. A product that declares a second ledger gets the revoke
in the same commit, with no edit to this file and no edit to `rules.yaml` — the
same discipline that turned rule 20 from a rule about one model's name into a
question about a registry. `deploy/test_grants_census.py` is the census that
holds this to it.

**WHAT THIS DOES NOT GUARD, stated rather than discovered.** The revoke binds
the APP's role. A superuser session — the RDS master, a DBA, a restore job —
can still update a ledger row, because a superuser can do anything and a
database has no layer above itself. The belt is for the application's own
paths, which is where the risk actually lives; the master credential's custody
is the secrets doctrine's problem, not this file's.

**RE-RUN IT AFTER EVERY MIGRATE.** `GRANT ... ON ALL TABLES` binds the tables
that exist when it runs, so a migration that creates a table leaves the app
role without privileges on it, and a migration that creates an append-only
table leaves it with too many. The runbook's release step is `migrate` then
this, in that order, every time — which is also why the SQL is idempotent:
re-applying it is the normal case, not the recovery case.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def django_root() -> Path:
    """Where `config` and `apps` live, from wherever this script was invoked.

    NOT simply `Path(__file__).parent.parent`. In a checkout that is the
    repository root and right; in the deployment it is `/`, because
    `deploy/compose.yaml` mounts this directory at `/deploy` while the tree
    lives at `/app`. The script that emits the release step's SQL has to work
    in both places, so it looks for `manage.py` rather than assuming a layout.
    `DJB_ROOT` overrides, for the third arrangement somebody will have.
    """
    override = os.environ.get("DJB_ROOT")
    if override:
        return Path(override)
    for candidate in (Path(__file__).resolve().parent.parent, Path("/app"), Path.cwd()):
        if (candidate / "manage.py").is_file():
            return candidate
    raise SystemExit(
        "!! grants.sql.py: cannot find the Django tree (no manage.py beside deploy/, "
        "at /app, or in the working directory). Set DJB_ROOT."
    )


# The privileges the application legitimately needs on an ordinary table. Named
# once, here, so the REVOKE below is visibly the complement of something rather
# than a number somebody remembered.
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")

# What an append-only table loses. Not SELECT (history is for reading) and not
# INSERT (a ledger grows). TRUNCATE is not granted in the first place — it is an
# owner privilege — so there is nothing to take away.
APPEND_ONLY_REVOKED = ("UPDATE", "DELETE")


def _quote_identifier(name: str) -> str:
    """A Postgres identifier, safely. Doubling `"` is the whole escape."""
    return '"' + name.replace('"', '""') + '"'


def append_only_tables() -> list[str]:
    """Every table behind a model that declared itself append-only.

    Reads `apps.core.models.append_only_models()` — the registry scan — and not
    a list in this file. Unmanaged models are skipped (there is no table of
    ours to revoke on) and proxies collapse, because two models can name one
    table and two REVOKEs on it would be noise, not belt.
    """
    from apps.core.models import append_only_models

    tables = {
        model._meta.db_table
        for model in append_only_models()
        if model._meta.managed and not model._meta.proxy
    }
    return sorted(tables)


def role_preamble() -> list[str]:
    """Create the application's role if it is not there, WITHOUT naming a value.

    psql meta-commands, and every one of them is doing a job:

    * `\\getenv` reads the role name and its password out of THIS PROCESS'S
      environment. Not out of a `-v` flag, which would put the password in
      `ps` and in a shell history file; not out of this file, which is
      generated, read and committed nowhere but is still a file.
    * `\\gexec` runs the statement the SELECT built, and the SELECT builds
      nothing when the role already exists — which is what makes the release
      step re-runnable.
    * `%I` and `%L` are `format()`'s identifier and literal quoting, done by
      Postgres rather than by string concatenation here.

    The runbook's release step passes both variables through with
    `docker run -e DATABASE_USER -e DATABASE_PASSWORD` — the passthrough form,
    with no `=`, so the values travel in the environment and never in argv.
    """
    return [
        "-- The application's role. Created only if absent; the password comes",
        "-- from the environment and is never in this file or in a command line.",
        "\\getenv djb_role DATABASE_USER",
        "\\getenv djb_password DATABASE_PASSWORD",
        "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'djb_role', :'djb_password')",
        "WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'djb_role')\\gexec",
        "",
    ]


def render(
    *,
    role: str,
    schema: str = "public",
    tables: list[str] | None = None,
    create_role: bool = False,
) -> str:
    """The SQL, as text. Pure: no connection, no clock, no randomness.

    Deliberately deterministic — no generated-at timestamp, no host name. The
    output of two runs against one tree is byte-identical, which is what lets a
    release step diff it, a reviewer read it, and the census test compare it
    against the registry without normalising anything first.
    """
    if tables is None:
        tables = append_only_tables()

    role_sql = _quote_identifier(role)
    schema_sql = _quote_identifier(schema)
    granted = ", ".join(TABLE_PRIVILEGES)
    revoked = ", ".join(APPEND_ONLY_REVOKED)

    lines: list[str] = [
        "-- Generated by deploy/grants.sql.py. Do not edit; re-generate.",
        "--",
        "-- Apply as the schema OWNER (the RDS master), not as the application",
        "-- role: a role cannot revoke a privilege from itself in any way that",
        "-- means anything.",
        "--",
        '--     psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f grants.sql',
        "--",
        "-- Idempotent, and meant to be re-run after every `migrate`.",
        "",
        "BEGIN;",
        "",
        *(role_preamble() if create_role else []),
        "-- What the application may do on an ordinary table of ours.",
        f"GRANT USAGE ON SCHEMA {schema_sql} TO {role_sql};",
        f"GRANT {granted} ON ALL TABLES IN SCHEMA {schema_sql} TO {role_sql};",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema_sql} TO {role_sql};",
        "",
    ]

    if tables:
        lines += [
            f"-- The append-only population ({len(tables)}), read off the model",
            "-- declarations by core.models.append_only_models(). A model that",
            "-- declares `append_only = True` appears here with no edit to this",
            "-- file; deploy/test_grants_census.py fails if one ever does not.",
        ]
        lines += [
            f"REVOKE {revoked} ON {schema_sql}.{_quote_identifier(table)} FROM {role_sql};"
            for table in tables
        ]
    else:
        # Never silently. An empty population means either a product with no
        # ledgers at all or a scan that ran before the app registry was
        # populated, and the two look identical in a file of GRANTs.
        lines += [
            "-- NO APPEND-ONLY MODELS WERE DISCOVERED.",
            "-- That is either a product that declares no ledger, or a registry",
            "-- that was not loaded when this ran. deploy/test_grants_census.py",
            "-- is what tells those apart; it refuses an empty population.",
        ]

    lines += ["", "COMMIT;", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="grants.sql.py",
        description=(
            "Emit the release step's GRANT/REVOKE SQL for the application's "
            "database role, with the append-only population read off the model "
            "declarations."
        ),
    )
    parser.add_argument(
        "--role",
        required=True,
        help=(
            "The application's database role — the one the app connects as, "
            "never the schema owner. Required, because the wrong answer here is "
            "a deployment that revoked nothing and said it had."
        ),
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="Schema holding the product's tables (default: public).",
    )
    parser.add_argument(
        "--create-role",
        action="store_true",
        help=(
            "Also emit the idempotent CREATE ROLE preamble, reading the role and "
            "its password out of DATABASE_USER / DATABASE_PASSWORD in psql's own "
            "environment. The runbook's first release step passes this; every "
            "re-run afterwards does too, and creates nothing."
        ),
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.production"),
        help=(
            "Settings module to load the app registry through. The default is "
            "production because the release step runs inside the deployment; the "
            "flag exists so a laptop can point it at config.settings.local."
        ),
    )
    args = parser.parse_args(argv)

    if not args.role.strip():
        parser.error("--role must name the application's database role")

    sys.path.insert(0, str(django_root()))
    os.environ["DJANGO_SETTINGS_MODULE"] = args.settings

    import django

    django.setup()

    # stdout is the artifact — this is a generator, and its output is piped
    # into psql or written to a file the release step reads. Anything
    # diagnostic goes to stderr so it never lands in the SQL.
    sys.stdout.write(render(role=args.role, schema=args.schema, create_role=args.create_role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
