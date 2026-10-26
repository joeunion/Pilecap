#!/usr/bin/env bash
# THE BELT AT THE DEPLOYMENT — the assignment `config/settings/guards.py` wrote
# down and could not discharge (ADR deploy-3d).
#
#   deploy/assert_not_published.sh                 # over this process's environment
#   deploy/assert_not_published.sh deploy/.env     # over an env file, before anything starts
#
# Exit: 0 clean and SILENT · 1 a published value is in play, named · 2 the check
# itself could not run. 2 outranks a pass, exactly as the gate's does: a belt
# that cannot read what it is meant to refuse has not cleared anything.
#
# WHY THIS EXISTS HERE AND NOT IN PYTHON. guards.py refuses a published
# SECRET_KEY and a published Fernet key because a settings import is a moment it
# owns. It declared, in its own words, that four more published credentials
# reach `compose.yaml` and never reach a settings import at all —
#
#     ZITADEL_MASTERKEY · ZITADEL_DATABASE_PASSWORD
#     POSTGRES_PASSWORD · ZITADEL_ADMIN_PASSWORD
#
# — "a gate standing in an open field" if added there, and assigned the belt to
# "the first production deploy", which is this. Here the values ARE in hand:
# they are in the file compose substitutes from, and in the environment the
# entrypoint materialized. So this is where they get checked.
#
# TWO SOURCES OF TRUTH, AND NEITHER IS COPIED. The published values guards
# already knows are read OUT OF guards, live, so a value added there is refused
# here in the same commit with no edit to this file. The four it structurally
# cannot see are declared below, once, because nothing else in the tree knows
# them either.
#
# WHAT THIS DOES NOT DO. It refuses PUBLISHED values — the ones in this
# repository, worth nothing because anybody can read them. It has no opinion
# about a weak value somebody chose: "hunter2" is not published and passes here.
# Entropy is `provision.sh`'s job, upstream, where the values are generated and
# no human types one.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Where the Django tree is, so `config.settings.guards` is importable. In the
# container that is /app; from a checkout it is the repository root, one level
# up from deploy/. Overridable for neither reason but the third one somebody
# will have.
DJB_ROOT="${DJB_ROOT:-$([ -f /app/manage.py ] && echo /app || dirname "$HERE")}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_BIN=python
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN=python3
    else
        echo "!! assert_not_published: no python on PATH — cannot read the published values guards declares" >&2
        exit 2
    fi
fi

# The whole check is Python because the comparison is over secret material:
# shell quoting, word splitting and a `$` in a masterkey are three ways to
# compare the wrong thing, and a belt that silently compares the wrong thing is
# worse than no belt. The shell script is the deployment-facing name (an
# entrypoint wants a shell script) and this is its one job.
#
# NOTHING HERE PRINTS A VALUE. A refusal names the VARIABLE and says how long
# what it holds was. A belt that echoed the secret to prove it was wrong would
# put it in every log the deployment ships.
exec "$PYTHON_BIN" - "$DJB_ROOT" "$HERE" "$@" <<'PYTHON'
from __future__ import annotations

import sys
from pathlib import Path

BROKEN = 2
REFUSED = 1

root = Path(sys.argv[1])
sources = sys.argv[3:]

# The env file's one reader — the subset `docker compose --env-file` and
# `set -a` agree on — is deploy/envfile.py, beside this script (in the
# container, /deploy). Stdlib only, so the belt still runs before anything is
# installed; a reader it cannot load is a belt that cannot read, exit 2.
sys.path.insert(0, sys.argv[2])
try:
    from envfile import read_env_file
except Exception as error:  # pragma: no cover - the broken-enforcement path
    print(
        f"!! assert_not_published: cannot import envfile from {sys.argv[2]} "
        f"({type(error).__name__}: {error}). The env file cannot be read.",
        file=sys.stderr,
    )
    raise SystemExit(BROKEN)

# --- half one: what guards already knows, read live -------------------------
sys.path.insert(0, str(root))
try:
    from config.settings import guards
except Exception as error:  # pragma: no cover - the broken-enforcement path
    print(
        f"!! assert_not_published: cannot import config.settings.guards from {root} "
        f"({type(error).__name__}: {error}).\n"
        "   The published values this belt refuses live there. Not clearing "
        "anything is not the same as clearing it.",
        file=sys.stderr,
    )
    raise SystemExit(BROKEN)

# Every `PUBLISHED_*` frozenset guards declares, discovered rather than listed —
# the same discipline `core.models.append_only_models` uses on the registry. A
# set added to guards (S1 adds PUBLISHED_DATABASE_PASSWORDS) joins this belt
# with no edit here.
GUARD_SETS = {
    name: frozenset(str(v) for v in value)
    for name, value in vars(guards).items()
    if name.startswith("PUBLISHED_") and isinstance(value, (frozenset, set, tuple, list))
}

# --- half two: the four guards structurally cannot see -----------------------
# Declared here, once, with the reason recorded in guards.py's own boundary
# paragraph. Each is refused by NAME AND VALUE rather than by value alone,
# because `djb` and `zitadel` are also legitimate usernames elsewhere in the
# same file and a value-only sweep would refuse a correct deployment.
#
# The FALLBACK column is what keeps this belt honest across the S1 seam: a
# variable whose guards set has not landed yet is still refused, from the value
# named here, and the report says which source did the refusing.
COMPOSE_ONLY = {
    "ZITADEL_MASTERKEY": "djb-local-development-masterkey!",  # pragma: allowlist secret
    "ZITADEL_DATABASE_PASSWORD": "zitadel",  # pragma: allowlist secret
    "POSTGRES_PASSWORD": "djb",  # pragma: allowlist secret
    "ZITADEL_ADMIN_PASSWORD": "Password1!",  # pragma: allowlist secret
}

# Every variable this belt has an opinion about, and where the opinion comes
# from. A guards set named here that guards does not declare falls back to the
# literal beside it — never to silence.
WATCHED: list[tuple[str, str | None, str | None]] = [
    # (variable, guards set name, fallback published value)
    ("SECRET_KEY", "PUBLISHED_SECRET_KEYS", None),
    ("CONNECTIONS_ENCRYPTION_KEY", "PUBLISHED_ENCRYPTION_KEYS", None),
    # S1 adds PUBLISHED_DATABASE_PASSWORDS to guards. Until it lands, the
    # fallback refuses the same value, and the source line says so out loud.
    ("DATABASE_PASSWORD", "PUBLISHED_DATABASE_PASSWORDS", "djb"),  # pragma: allowlist secret
    ("ZITADEL_MASTERKEY", None, COMPOSE_ONLY["ZITADEL_MASTERKEY"]),
    ("ZITADEL_DATABASE_PASSWORD", None, COMPOSE_ONLY["ZITADEL_DATABASE_PASSWORD"]),
    ("POSTGRES_PASSWORD", None, COMPOSE_ONLY["POSTGRES_PASSWORD"]),
    ("ZITADEL_ADMIN_PASSWORD", None, COMPOSE_ONLY["ZITADEL_ADMIN_PASSWORD"]),
    # Read by settings, fenced upstream by `zitadel_seed`'s DEBUG refusal
    # (guards.py says so). Refused here anyway: upstream fences are for the
    # paths that go through them, and this one costs a dictionary entry.
    ("ZITADEL_DEV_USER_PASSWORD", None, "Password1!"),  # pragma: allowlist secret
]


if sources:
    environment: dict[str, str] = {}
    where = ", ".join(sources)
    for source in sources:
        path = Path(source)
        if not path.is_file():
            print(f"!! assert_not_published: no such env file: {source}", file=sys.stderr)
            raise SystemExit(BROKEN)
        environment.update(read_env_file(path))
else:
    import os

    environment = dict(os.environ)
    where = "this process's environment"

findings: list[str] = []
checked = 0

for variable, guard_set, fallback in WATCHED:
    published: frozenset[str]
    source: str
    if guard_set is not None and guard_set in GUARD_SETS:
        published = GUARD_SETS[guard_set]
        source = f"config.settings.guards.{guard_set}"
    elif fallback is not None:
        published = frozenset({fallback})
        source = (
            f"deploy/assert_not_published.sh (guards declares no {guard_set})"
            if guard_set is not None
            else "deploy/assert_not_published.sh"
        )
    else:
        print(
            f"!! assert_not_published: {variable} is watched through "
            f"config.settings.guards.{guard_set}, which guards does not declare, "
            "and there is no fallback. This belt cannot say whether the value is "
            "published.",
            file=sys.stderr,
        )
        raise SystemExit(BROKEN)

    checked += 1
    value = environment.get(variable)
    if value is None or value == "":
        continue
    if value in published:
        findings.append(
            f"   {variable}: the value published in this repository "
            f"({len(value)} characters). Refused by {source}."
        )

if not checked:
    print(
        "!! assert_not_published: nothing was checked — the watch list is empty. "
        "A belt with no buckle is not a belt.",
        file=sys.stderr,
    )
    raise SystemExit(BROKEN)

if findings:
    print(
        f"!! REFUSED: {len(findings)} published credential(s) in {where}.\n"
        + "\n".join(findings)
        + "\n\n   These values are in a public git repository and are therefore worth\n"
        "   nothing. Generate real ones — `deploy/provision.sh env-file` does it\n"
        "   for a laptop and `deploy/provision.sh secrets-put` for an environment;\n"
        "   no human types one (the secrets doctrine).",
        file=sys.stderr,
    )
    raise SystemExit(REFUSED)

# Silent on success. This runs in front of every container start, and a line
# per boot saying "still fine" is a line people stop reading.
raise SystemExit(0)
PYTHON
