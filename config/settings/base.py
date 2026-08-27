"""Settings shared by every environment.

Every value comes from the environment; `.env.example` is the complete list of
variables this module reads. The environment-specific modules (`local`, `test`,
`production`) import everything from here and override only what differs.
"""

import os
from pathlib import Path
from typing import Any

import django_stubs_ext
import environ
from django.core.exceptions import ImproperlyConfigured

from .discovery import discover_local_apps
from .guards import DEV_DATABASE_PASSWORD

# Makes Django's generic classes subscriptable at runtime, so annotations like
# `admin.ModelAdmin[Widget]` are written the same way in code and in stubs.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    env.read_env(str(_env_file))

# --- Core -------------------------------------------------------------------

SECRET_KEY: str = env.str("SECRET_KEY", default="")
DEBUG: bool = env.bool("DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Where this deployment is reachable from the outside, scheme included and no
# trailing slash. Anything that has to build a link a person will click — an
# invitation email, a webhook callback URL — starts here, because a background
# worker has no request to ask. `django.contrib.sites` is deliberately not that
# source: its default row says `example.com`, and a link to example.com in an
# invitation is a bug nobody notices until a customer reports it.
PUBLIC_BASE_URL: str = env.str("PUBLIC_BASE_URL", default="http://127.0.0.1:8000").rstrip("/")

# What this product is CALLED, and the one place the name is written (owner
# ruling 2026-08-24; ADR platform-1 in docs/product/architecture.md). Every
# surface that shows a name or
# materialises one — the Zitadel project below, the compose first-instance org
# and its service account, the devcontainer's display name — derives from this
# variable, so a product sets its name once in `.env` and renames nothing else.
# The default is the template's own name deliberately: a fresh clone that has
# not chosen a name yet should say it is the template, not borrow a product's.
#
# Not derived from it: `compose.yaml`'s `name: djangobootstrap` (infrastructure
# identity — containers and volumes key on it), the Zitadel admin and dev-user
# logins, and the machine username. Those are account identifiers already
# materialised in a running instance, not display names, and renaming one is a
# migration rather than a setting.
PRODUCT_NAME: str = env.str("PRODUCT_NAME", default="Pilecap")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"
SITE_ID = 1

# BaseModel gives every concrete model an explicit UUID primary key, so
# DEFAULT_AUTO_FIELD is deliberately left unset.

# --- Applications -----------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
]

THIRD_PARTY_APPS = [
    "channels",
    "corsheaders",
    # For its templates and its `export_openapi_schema` command — the routers
    # themselves are discovered by `config/api.py` and need nothing here.
    # `scripts/gen_client.sh` uses the command, which is what lets a client be
    # generated from a checkout with no server running.
    "ninja",
    "allauth",
    "allauth.account",
    # The workforce door (Google Workspace OIDC) and the customer door (one
    # OpenID Connect provider per `accounts.SsoConnection`). Both are *off* in
    # the sense that matters: `SOCIALACCOUNT_PROVIDERS` below leaves Google with
    # no app unless the deployment sets credentials AND names its domains, and
    # `openid_connect` has no apps at all except the ones
    # `accounts.adapter.SocialAccountAdapter.list_apps` builds from the database.
    # An installed app with no credentials is a login page nobody can start.
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.openid_connect",
    "django_linear_migrations",
]

# Discovered, never listed: anything under `apps/` whose `apps.py` declares an
# `AppConfig` is installed. Adding an app is adding a directory — this file is
# not edited, which is what lets one agent per app work in parallel.
#
# The one subtraction a deployment may make: `DJB_DISABLED_APPS`, a comma list
# of app LABELS, empty by default so a development tree is unchanged. It can
# only take away an app whose own `AppConfig` declared `optional = True` (today
# that is `apps/example`, the worked example a product stops shipping once it
# has its own domain app); every other label is refused BY NAME while this file
# is being read, so a deployment built on a hole does not start. Read at import
# — a running process does not re-derive it.
DJB_DISABLED_APPS: list[str] = env.list("DJB_DISABLED_APPS", default=[])
LOCAL_APPS: list[str] = discover_local_apps(BASE_DIR / "apps", DJB_DISABLED_APPS)

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # Outermost: the ambient facts every log line, span and audit row carries.
    "apps.core.middleware.ContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Immediately after SecurityMiddleware, which is where WhiteNoise documents
    # it and where it has to be: above this line the security headers still get
    # applied to a static response, and below it the request would first travel
    # through sessions, auth, tenancy and idempotency to fetch a CSS file. This
    # is why the product needs no separate static file server for the admin and
    # `/api/v1/docs` — the two pages this project actually serves.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Above CommonMiddleware, where django-cors-headers requires it: a preflight
    # OPTIONS has to be answered before anything gets a chance to redirect it.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.TenantMiddleware",
    # After the session and the tenant, so a replayed response is scoped to the
    # same credential and tenant the original request was.
    "apps.core.idempotency.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

TEMPLATES: list[dict[str, Any]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------
# `scripts/db.sh` exports DATABASE_NAME as djb_<branch>_<hash of the checkout's
# absolute path>, and `scripts/setup.sh` writes that same name into .env, so each
# CHECKOUT owns its own database on the one compose Postgres and two checkouts of
# one branch never share one. A name already in the environment wins over the
# derivation. DATABASE_URL, when set, wins over the parts.
#
# There is NO last-resort default. A tree that has run neither resolves an
# empty name and refuses below, out loud, rather than quietly binding whatever
# `djb_main` happens to be on this machine — which on the machine this template
# was built on is the owner's live development database. A default that names a
# real database is not a fallback, it is a wrong answer delivered confidently.
#
# **This changes what an un-setup tree does, and that is the point.** A bare
# `manage.py`, or a bare `uv run pytest` outside `scripts/test.sh`, in a tree
# that has run neither `scripts/setup.sh` nor `source scripts/db.sh`, USED TO
# reach `djb_main` and now stops with the message below. It is a breaking change
# for exactly the workflows that were silently wrong — they were reading and
# writing a database nobody chose for them. The remedy is one command, and the
# message names both of them, because this line cannot tell "never set up" from
# "sourcing forgotten in this shell" and the two are fixed differently.

DATABASE_NAME: str = env.str("DATABASE_NAME", default="")

# The refusal does not sit at this line, and where it moved to is the point:
# DATABASE_NAME is only one of the two ways a name arrives; the name that
# actually governs is whatever the assembled DATABASE_URL resolves to. So the
# refusal — and the one derivation everything downstream reads — sits just below
# the URL assembly, where that resolved name exists. Nothing between here and
# there consumes a name.

DATABASE_USER: str = env.str("DATABASE_USER", default="djb")
# The default is the published compose password and it STAYS one (deleting it
# breaks every laptop for a production problem). It is
# read from `config.settings.guards` rather than typed here so that the value
# `.env.example` ships, the value this line falls back to, and the value
# production refuses are one string with one home — the same arrangement
# SECRET_KEY and the Fernet key already have.
DATABASE_PASSWORD: str = env.str("DATABASE_PASSWORD", default=DEV_DATABASE_PASSWORD)
DATABASE_HOST: str = env.str("DATABASE_HOST", default="127.0.0.1")
DATABASE_PORT: int = env.int("DATABASE_PORT", default=5432)
# --- Connection reuse: the pool, and the budget it fits inside --------------
#
# **THE ESCALATION HAS BEEN TAKEN, AND IT IS NOT PGBOUNCER** (ADR config-1,
# 2026-08-25). What stood here until then described persistent connections —
# `CONN_MAX_AGE=60` — and named PgBouncer as the escalation to reach for when
# the arithmetic ran out. The arithmetic ran out, and the escalation reached
# for was a different one; a comment naming a rejected option as THE option is
# a doc lie once the tree disagrees with it, so this block now says what was
# ruled and why, and PgBouncer keeps its place as the *next* escalation with
# its cost written down.
#
# **What was measured.** Under ASGI every `sync_to_async` thread owns a
# `DatabaseWrapper`, and a `DatabaseWrapper`'s connection is closed only at the
# end of a request *that thread* served. Persistent connections then mean the
# process's server-side connection count is the number of threads that have
# ever served a request, not the number doing work, and nothing reclaims an
# idle thread's slot. LOAD-1b (2026-08-25) read that off `pg_stat_activity` on
# staging: **43 connections held against ≤4 active, flat across the whole
# ladder and unchanged 90 seconds after the load stopped**, on an RDS instance
# whose `max_connections` is 79 and whose neighbours hold about 30 of them.
# Concurrency 1 was already at the wall, and the 83% error rate read as "the
# product cannot take load" when the truth was "the product never got to try".
#
# **What replaced it.** Django 5.2's native psycopg pool: `OPTIONS["pool"]`,
# assembled below, which needs nothing but this settings module and the
# `psycopg[pool]` extra in `pyproject.toml`. Every request-end close becomes a
# *putconn* — the socket goes back to a per-process pool instead of being kept
# by the thread — so:
#
#   * server-side connections are bounded by `max_size` **by construction**,
#     not by a convention a burst can break;
#   * they stay **warm**: no request pays a backend fork plus a TLS handshake,
#     which matters because the resource LOAD-1b convicted is a *burstable*
#     RDS instance's CPU (71.8% at concurrency 16), and connection churn
#     spends exactly that;
#   * an idle connection is dropped after `max_idle`, so the pool shrinks back
#     toward `min_size` between bursts instead of leaving residue.
#
# It also requires `CONN_MAX_AGE=0`, which is why the value below is derived
# rather than read when the pool is on: Django refuses the contradictory pair
# outright (`ImproperlyConfigured: Pooling doesn't support persistent
# connections.`), and an assembly that could produce it would be an assembly
# that fails on somebody's first request. `CONN_HEALTH_CHECKS` still carries:
# the pool is given `ConnectionPool.check_connection`, so a connection the
# server closed in between is discovered by the pool as a reconnect rather than
# by a request as a 500.
#
# **PgBouncer, rejected, and the trigger to look again.** Transaction pooling
# forbids server-side cursors, and `.iterator()` is how this tree streams:
# exports walk chunked JSONL, search rebuilds walk the corpus, the workflow
# sweeps walk tenants. `DISABLE_SERVER_SIDE_CURSORS` would silently turn every
# one of those keyset streams into a full buffer — a platform-layer behaviour
# change bought for nothing. Session state (the per-connection timezone and
# role set in `_configure_connection`) is the same class of landmine. And it is
# a container, an image in the supply chain, TLS on both legs and an auth story
# that fights the per-checkout derived database above — surface a ≤4-active
# demand cannot justify. It earns its keep when `Σ(per-process max_size)`
# across replicas can no longer fit inside the budget below; **that is the
# trigger, and it is a deployment's decision recorded in the product's
# `architecture.md`.** Bare `CONN_MAX_AGE=0` with no pool was rejected too: it
# pays the reconnect tax on the convicted CPU and caps nothing — 32 asgiref
# threads under burst still open 32 slots at once.
#
# **The budget, with the neighbours BOUNDED**
# (`deploy/env.staging.example` carries the same arithmetic beside the values it
# sets, and `deploy/compose.yaml` carries the knobs that make the bounds true):
#
#     max_connections (db.t4g.micro)                          79
#   − Temporal, bounded: 4 roles × 4 + 4 roles × 2         ≤ 24
#   − Zitadel: 5 bounded + 2 its config cannot bound       ≤  7
#   − RDS's own (rdsadmin 2, reserved/unnamed ~5)            ~7
#   − operator headroom (psql, backup, migration — AND the
#     oneoff door's ≤2: the release acts ride this line)      8
#   ─────────────────────────────────────────────────────────────
#   = the application's ceiling                              33
#
#     web 20 + worker 8 = 28 ≤ 33
#
# **What changed, and why the old number could never have held.** The previous
# arithmetic subtracted "Temporal 17+3, Zitadel 3" as a budget CONSTANT. It was
# not a constant; it was an at-rest reading of an unbounded thing. Temporal's
# `auto-setup` image runs frontend + history + matching + worker in ONE process
# and each role builds its own SQL pool from the same configuration, so the
# image's defaults ceilinged at 4×20 + 4×10 = 120 slots against a
# `max_connections` of 79 — and a measurement found 41 held at rest after a
# reboot, a number no single pool of 20 could produce. It confounded a paid
# experiment (size B's knee was slot-gated, not CPU-gated) and it refused a
# release act on a loaded box. The sentence that used to stand here — "Temporal's
# own 17+3 is its configuration to trim on some future Temporal touch" — is gone
# because this **is** that touch: `deploy/compose.yaml` now sets
# `SQL_MAX_CONNS` / `SQL_MAX_IDLE_CONNS` / `SQL_VIS_MAX_CONNS` /
# `SQL_VIS_MAX_IDLE_CONNS` and Zitadel's `MAXOPENCONNS` / `MAXIDLECONNS`, so the
# numbers above are **ceilings the organs enforce on themselves**
# (`SetMaxOpenConns` inside each process), not observations that go stale.
#
# **Zitadel's `+2` is MEASURED AND NAMED, not rounded away.**
# `MAXOPENCONNS` bounds Zitadel's main `Database.postgres` pool; its background
# job queue keeps a **second** pool that no environment variable in v4.17.1
# reaches — `strings` over the v4.17.1 binary returns `MAXOPENCONNS`,
# `MAXIDLECONNS` and the two lifetimes, and no queue knob at all. Driven both
# ways on the laptop deploy stack (`--profile laptop`, recreate between
# runs):
#
#     image defaults 10/5   the `zitadel` database held 12 in the window after a
#                           recreate — exactly what was measured on the box
#     ruled 5/2             7 in the same window; **4 settled**, over four
#                           readings 30s apart
#
# The delta tracks the bound; the residue is the queue's. So the budget line is
# **7 — the observed ceiling, not the settled 4** — and the two unbounded slots
# come out of operator headroom rather than being rounded into invisibility. A
# census reading Zitadel at 7 is AT its bound; above 7 is the stop-and-report.
#
# **The revisit trigger, rewritten against the new bounds.** Not "a number went
# stale": the census recipe reading **any principal above its stated bound**, a
# **new process class** joining the box, or **replicas** — at which point
# `Σ(replicas × processes × max_size)` is what stops fitting, and PgBouncer is
# reconsidered on the terms above.
DATABASE_POOL_APP_CEILING: int = 33

# **A pool is per process, so its size is a property of what the process is.**
# `DJB_SERVICE_NAME` already tells the two apart — `deploy/compose.yaml` sets it
# on each service and `apps/workflows/worker.py` sets it before
# `django.setup()` — so the split rides that one discriminator rather than a
# second copy of it. (`OTEL_SERVICE_NAME` further down reads the same variable;
# it is read twice rather than threaded through, because a settings module that
# defines things in dependency order is easier to read than one that does not.)
#
# 20 and 8 sum to 28, inside the 33 ceiling with room for the operator. The web
# process gets the larger half because it is the one with `ATOMIC_REQUESTS` and
# a thread per in-flight request; the worker's activities are already
# serialised by its own thread pool.
#
# **`oneoff` is the third entry and it is a DOOR, not an organ.** A
# `docker compose run` used to land on the `web` service, inherit
# `DJB_SERVICE_NAME=web`, and derive `max_size=20` — so a one-off `manage.py`
# command reserved a deployment's worth of slots. On a loaded box there were
# none left: the command PoolTimeout'd, and release acts 1, 2, 3 and 5 are the
# same shape, which means a release can be refused by its own box's load.
# `deploy/compose.yaml` grows a dedicated `oneoff` service whose only job is to
# be the name `compose run` lands on, and this entry is the other half: 2, which
# is what a management command actually wants. The pair is one seam rather than
# a `-e` flag on an open set of invocations, and
# `deploy/tests/test_release.sh`'s compose-run census keeps the population
# closed.
#
# `_POOL_MAX_SIZE_OTHERWISE` stays 4 as the STRANGER default — a process that
# named itself something this map has never heard of gets a small pool rather
# than a deployment's worth. It is not the oneoff answer: a default nobody
# declared cannot be the one the release acts depend on.
_POOL_MAX_SIZE_BY_SERVICE: dict[str, int] = {"web": 20, "worker": 8, "oneoff": 2}
_POOL_MAX_SIZE_OTHERWISE = 4

DATABASE_POOL_ENABLED: bool = env.bool("DATABASE_POOL_ENABLED", default=True)
DATABASE_POOL_MIN_SIZE: int = env.int("DATABASE_POOL_MIN_SIZE", default=2)

# **EMPTY MEANS DERIVE, and it is read as a string to make that true.** The
# same escape `DATABASE_NAME`, `TEMPORAL_TASK_QUEUE` and
# `TEMPORAL_MACHINERY_LIFETIME` offer, spelled the same way — but here the
# spelling is load-bearing rather than decorative: `deploy/entrypoint.sh` does
# `set -a; . <env file>`, so a name that appears in an env file at all is
# EXPORTED, empty value included, and `env.int` on an empty string is a
# `ValueError` at import — a container that will not boot, with a stack trace
# about `int()` rather than about connection pools. An empty override therefore
# has to mean "derive", not "crash".
_pool_max_size_override: str = env.str("DATABASE_POOL_MAX_SIZE", default="").strip()
DATABASE_POOL_MAX_SIZE: int = (
    int(_pool_max_size_override)
    if _pool_max_size_override
    else _POOL_MAX_SIZE_BY_SERVICE.get(
        env.str("DJB_SERVICE_NAME", default="web"), _POOL_MAX_SIZE_OTHERWISE
    )
)
# Seconds a request waits for a free connection before the pool refuses. 10 and
# not psycopg's 30, because a saturated pool should answer fast: a request that
# has waited half a minute for a connection has already lost whoever was
# waiting for it, and a refusal a client can retry is worth more than a hang.
DATABASE_POOL_TIMEOUT: float = env.float("DATABASE_POOL_TIMEOUT", default=10.0)
# Seconds an unused connection above `min_size` is kept before the pool drops
# it. This is the knob that makes "the residue goes away" true: 5 minutes is
# long enough that a normal traffic trough does not cost a reconnect storm, and
# short enough that a burst's slots are given back to the neighbours well
# inside the window an operator would notice them missing.
DATABASE_POOL_MAX_IDLE: float = env.float("DATABASE_POOL_MAX_IDLE", default=300.0)

# **Derived, not read, when the pool is on**, and that is the whole of what
# `DATABASE_CONN_MAX_AGE` means now: with a pool, persistent connections are
# not a knob turned down, they are a shape Django refuses. The variable is
# still honoured when `DATABASE_POOL_ENABLED=false` — the escape hatch back to
# the pre-2026-08-25 behaviour, which is *persistent connections*, not bare
# churn, because bare churn is the option that was rejected on its merits.
DATABASE_CONN_MAX_AGE: int = (
    0 if DATABASE_POOL_ENABLED else env.int("DATABASE_CONN_MAX_AGE", default=60)
)

_default_database_url = (
    f"postgres://{DATABASE_USER}:{DATABASE_PASSWORD}"
    f"@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
)
_configured_database_url: str = env.str("DATABASE_URL", default="")
DATABASE_URL: str = _configured_database_url or _default_database_url

# Which password `config.settings.production` refuses over, and whether there is
# one to refuse at all. This line, not `guards`, is what knows the answer:
# a URL wins over the parts one line above, and when it does, the password lives
# inside a string this module is handed whole and never assembled — a different
# population, whose belt is the deployment's own start-up assertion (P4-D1).
# `None` therefore means "the parts were not consulted", never "do not check".
_parts_database_password: str | None = None if _configured_database_url else DATABASE_PASSWORD

# --- One parse, one name -------------------
# `db_url_config` is the parser the connection itself uses, so the name read out
# of it here IS the name the connection will use — by construction, rather than
# by a second derivation that can disagree with it. That is what the both-set
# case needs: DATABASE_URL wins over the parts for the connection, and reading
# the winning name here is what makes the Temporal task queue further down ride
# the same winner instead of the losing DATABASE_NAME.
#
# It also closes a real gap: when only DATABASE_URL was set, DATABASE_NAME
# stayed empty and the task queue derived to the bare `djb-` — which is every OTHER URL-only
# deployment's queue too, so a staging worker could accept a workflow production
# started, silently. That degrade is DELETED rather than announced: there is no
# longer any path that reaches the queue derivation holding an empty name, so
# there is nothing left to warn about.
#
# An empty name is therefore the one thing refused here, and it has two
# entrances. Nothing configured at all: the parts assemble `.../` and resolve to
# nothing — the original scar, unchanged in behaviour. And a DATABASE_URL that
# names no database segment (`postgres://host:5432`, or a bare unix-socket URL):
# it is a URL, but it is not an answer, and guessing one on a deployment's
# behalf is the same mistake already refused above. Both stop here, out loud.
_database_config: dict[str, Any] = env.db_url_config(DATABASE_URL)
_database_name_in_use: str = str(_database_config.get("NAME") or "")

if not _database_name_in_use:
    raise ImproperlyConfigured(
        "DATABASE_NAME is not set and there is no default: this tree would "
        "otherwise connect to a database it never chose. Either remedy fixes "
        "it — run `./scripts/setup.sh`, which writes this checkout's own "
        "database name into .env; or run `source scripts/db.sh`, which exports "
        "the same name into this shell. (`export DATABASE_NAME=<name>` picks a "
        "specific one, and DATABASE_URL, when set, wins over the parts — but a "
        "DATABASE_URL carrying no database segment names nothing either, and is "
        "refused here for the same reason.)"
    )

# OPTIONS from the URL's own query string, if it carried any, plus the pool.
# Merged rather than replaced: a deployment that spells an option into
# DATABASE_URL keeps it, and the pool is added beside it.
_database_options: dict[str, Any] = dict(_database_config.pop("OPTIONS", None) or {})
if DATABASE_POOL_ENABLED:
    # This dict IS `psycopg_pool.ConnectionPool`'s keyword arguments — Django
    # passes it straight through — so the names are psycopg's, not Django's.
    _database_options["pool"] = {
        "min_size": DATABASE_POOL_MIN_SIZE,
        "max_size": DATABASE_POOL_MAX_SIZE,
        "timeout": DATABASE_POOL_TIMEOUT,
        "max_idle": DATABASE_POOL_MAX_IDLE,
    }

DATABASES: dict[str, dict[str, Any]] = {
    "default": {
        **_database_config,
        "CONN_MAX_AGE": DATABASE_CONN_MAX_AGE,
        # Without this, a reused connection that the server closed in between —
        # a failover, an idle timeout, a `pg_terminate_backend` — is discovered
        # by a request, as a 500. With it, it is discovered by Django, as a
        # reconnect. With the pool on it is also what hands the pool
        # `ConnectionPool.check_connection`, so the check happens on the way
        # out of the pool rather than on the way into a view.
        "CONN_HEALTH_CHECKS": True,
        "ATOMIC_REQUESTS": True,
        "OPTIONS": _database_options,
    }
}

# --- Redis, cache and the channel layer -------------------------------------
# One compose Redis serves both; separate databases keep a `cache clear` from
# throwing away every socket group.

REDIS_URL: str = env.str("REDIS_URL", default="redis://127.0.0.1:6379/0")
CACHE_URL: str = env.str("CACHE_URL", default="redis://127.0.0.1:6379/1")

# --- The cache key namespace, per CHECKOUT ----------------------------
#
# `CACHE_URL` above defaults every checkout on this machine to ONE Redis
# database on one server. Without a `KEY_PREFIX` that is one key space shared
# by every worktree: two trees running at once `cache.set("plan", ...)` over
# each other and each reads the other's answer. It is the same class one layer
# up — two clones of `main` sharing `djb_main` — and the symptom is worse, because a
# wrong database announces itself with a missing table while a wrong cache
# entry is a WRONG ROW returned confidently.
#
# It is invisible today only because `config/settings/test.py` swaps in
# `LocMemCache`, so the suite never touches Redis at all. Invisible is not
# absent: the day a product caches a tenant-scoped read under a bare key, the
# defect is live and nothing in the gate is looking at it.
#
# THE PREFIX IS THE DATABASE NAME, and that is the whole derivation. It is not
# a second copy of `scripts/db.sh`'s branch-plus-path-hash arithmetic — it is
# that arithmetic's RESULT, read at the same seam `TEMPORAL_TASK_QUEUE` reads
# below. `db.sh` derives `djb_<branch>_<8 hex of the SHA-256 of the checkout's
# top level>` and exports it; settings parses whatever won (parts or URL) into
# `_database_name_in_use`; both the queue and this prefix ride that one value.
# So the three per-checkout namespaces — database, task queue, cache — cannot
# drift apart, and a key seen in `redis-cli` names the database it belongs to
# verbatim (`djb_main_700aaf41:1:plan`), which the `djb-`-shaped queue name
# deliberately does not.
#
# It reads `_database_name_in_use` and NOT `DATABASE_NAME` for the reason
# stated in full below: `DATABASE_NAME` is only one of the two ways a name
# arrives, and it is empty in exactly the URL-only case. An empty prefix here
# would put every URL-only deployment back in one key space.
#
# NON-EMPTY BY CONSTRUCTION: the refusal above means no import gets past
# `_database_name_in_use` being empty, so there is no path on which this
# derives to `""`.
#
# THE PIN, and its semantics. An explicit `CACHE_KEY_PREFIX`
# in the environment WINS OUTRIGHT and nothing is derived — the same escape
# `DATABASE_NAME` and `TEMPORAL_TASK_QUEUE` offer, spelled the same way, so a
# deployment that wants two processes to share one warm cache says so once. And
# the same hazard comes with it: a pin is a DECLARATION, so a STALE pin is two
# checkouts sharing a key space again, deliberately-looking. `.env.example`
# therefore ships the slot EMPTY, exactly as `TEMPORAL_TASK_QUEUE` and
# `TEMPORAL_MACHINERY_LIFETIME` do — empty means "derive", which is the honest
# answer nearly always, and a fresh clone never has to know what to write.
# (There is no `.env`-versus-derivation announcement here, as `db.sh` makes for
# the database name: `db.sh` can compare because it derives the name itself.
# This value is derived at settings import from the name that already won, so
# a pin and a derivation cannot silently disagree across two doors — there is
# only one door.)
#
# WHAT IT CANNOT SEE, declared: this is per-NAME, not per-SERVER — the same
# blind spot `TEMPORAL_TASK_QUEUE` declares below. Two deployments that give
# their databases the same name on different servers, pointed at one Redis,
# share a key space and no setting here can tell them apart. `CACHE_KEY_PREFIX`
# is the escape for that, and it is why the pin exists.
#
# PRODUCTION takes this derivation unchanged — `config/settings/production.py`
# imports `base` and overrides neither `CACHES` nor this value — and that is
# correct rather than merely inherited: a deployment's database name is stable
# across releases, so the prefix is stable across a deploy and a release does
# not cold-start its own cache; two deployments with different database names
# (staging and production on one Redis, blue and green) are separated without
# anyone configuring anything. A deployment that wants something else sets
# `CACHE_KEY_PREFIX` and it wins, which is the same sentence as the pin above.
CACHE_KEY_PREFIX: str = env.str("CACHE_KEY_PREFIX", default="") or _database_name_in_use

CACHES: dict[str, dict[str, Any]] = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": CACHE_URL,
        # Django composes every key as `<KEY_PREFIX>:<version>:<key>`, so this
        # namespaces the whole cache and not one call site — a product's bare
        # `cache.set("plan", ...)` is inside it without knowing it exists.
        "KEY_PREFIX": CACHE_KEY_PREFIX,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

# How long `channels_redis` blocks on one `BZPOPMIN` before polling again —
# `channels_redis.core.RedisChannelLayer.brpop_timeout`, restated rather than
# imported, because settings load before anything else and must not drag the
# channel layer in with them. `apps/realtime/tests/test_doors_over_the_wire.py`
# asserts the two are still in this relationship, so an upgrade that changes it
# fails the gate rather than the sockets.
CHANNEL_LAYER_BLOCKING_READ_SECONDS = 5.0

# **Longer than the blocking read above, and that is the whole point** (queue
# V2). redis-py 8 defaults `socket_timeout` to five seconds and *raises* when a
# read exceeds it; `channels_redis` issues a five-second blocking read and
# passes no per-read timeout, so the two numbers raced, redis-py won, and every
# idle websocket died at exactly 5.0s with a `TimeoutError` out of
# `channels/utils.py`. A read timeout still exists — a genuinely dead
# connection is still noticed — it is simply no longer shorter than the read it
# is guarding.
CHANNEL_LAYER_SOCKET_TIMEOUT = 4 * CHANNEL_LAYER_BLOCKING_READ_SECONDS

# Connecting is not blocking-read-shaped: a Redis that is not answering the
# handshake should be reported quickly rather than in twenty seconds.
CHANNEL_LAYER_CONNECT_TIMEOUT = 5.0

# Named separately from `CHANNEL_LAYERS` so that a test can override the layer
# back to Redis and get **this** configuration rather than a hand-copied one —
# `config/settings/test.py` replaces `CHANNEL_LAYERS` with the in-memory layer,
# which is what let V2 through green.
REDIS_CHANNEL_LAYER: dict[str, Any] = {
    "BACKEND": "channels_redis.core.RedisChannelLayer",
    "CONFIG": {
        "hosts": [
            {
                "address": REDIS_URL,
                "socket_timeout": CHANNEL_LAYER_SOCKET_TIMEOUT,
                "socket_connect_timeout": CHANNEL_LAYER_CONNECT_TIMEOUT,
            }
        ]
    },
}

CHANNEL_LAYERS: dict[str, dict[str, Any]] = {"default": REDIS_CHANNEL_LAYER}

# --- Does the channel layer need the cache's per-checkout prefix? NO ---------
#
# The same question already asked of `CACHES`, asked here and MEASURED rather than
# assumed, because the setup looks identical: every checkout on this machine
# points at the one `REDIS_URL` above, and `channels_redis` 4.3.0 does take a
# `prefix` in `CONFIG` (`RedisChannelLayer.__init__(..., prefix="asgi")`) which
# this tree does not set — so every checkout's socket traffic really is in one
# `asgi:` namespace on one Redis database.
#
# It is still not the same defect, and the difference is WHO CHOOSES THE NAME.
#
#   The cache's keys are chosen by PRODUCT CODE, and they are bare words:
#   `cache.set("active_plan", ...)` in two checkouts is one key, every time, by
#   construction. Nothing about the key says which tree wrote it.
#
#   The channel layer's names are DERIVED FROM ROWS. `apps/realtime/bridge.py`
#   builds every group it ever joins or sends to out of primary keys —
#   `tenant.<uuid>`, `org.<uuid>.<uuid>`, `user.<uuid>` — and those are UUIDv7s
#   minted by `apps.core.ids.uuid7` into THIS checkout's own database, which
#   is already per-checkout. Two trees therefore never name the same
#   group, prefix or no prefix. Channel names are covered by the library
#   itself: `client_prefix` is a fresh `uuid4().hex` per layer instance
#   (`channels_redis/core.py`), so a specific channel is per-PROCESS, which is
#   narrower than per-checkout.
#
# Adding `"prefix"` here would therefore buy a second namespace under a first
# one that is already unique — and it would cost something real: the prefix is
# baked into every live group key, so changing it is a flag day for any socket
# open across the change. Not worth it for a collision that cannot occur.
#
# WHAT THIS ANSWER DEPENDS ON, so it can be re-opened honestly: it holds only
# while group names are built from row ids. A product that groups by a name a
# HUMAN chose — a slug, a room name, a channel handle — has the cache's problem
# exactly, and the fix is then this `CONFIG["prefix"]`, set from
# `CACHE_KEY_PREFIX` above. `apps/realtime/bridge.py`'s `tenant_group` /
# `org_group` / `user_group` are the three functions that would have to change
# first, and its docstrings already rule out slugs for a different reason
# (a rename would silently stop delivery).
#
# THE ONE RESIDUAL, declared rather than absorbed: `RedisChannelLayer.flush()`
# deletes `<prefix>*` across the whole Redis database, so one un-prefixed
# `flush()` would empty every checkout's socket state at once. Nothing in this
# tree calls it — it is a teardown API, and `config/settings/test.py` swaps in
# `InMemoryChannelLayer`, so the suite never reaches Redis here either. If
# something ever does need to flush, it needs the prefix first.

# --- Temporal ---------------------------------------------------------------
# The task queue is derived from the database name, which `scripts/db.sh`
# derives from the CHECKOUT. One sanitiser, in one place: two checkouts therefore
# get two queues and their workers never steal each other's tasks.
#
# It reads `_database_name_in_use` — the name parsed out of the assembled
# DATABASE_URL above — and NOT `DATABASE_NAME`, which is only one of the two
# ways that name arrives. A URL-only deployment has an empty
# DATABASE_NAME and a perfectly good database name; deriving from the former
# gave every one of them the same queue, `djb-`.
#
# What this still cannot see: the derivation is per-NAME, not per-server. Two
# deployments that deliberately give their databases the same name on different
# servers share a queue, and no setting here can tell them apart. That is a
# naming choice with an escape — set TEMPORAL_TASK_QUEUE and it wins outright.

TEMPORAL_ADDRESS: str = env.str("TEMPORAL_ADDRESS", default="localhost:7233")
TEMPORAL_NAMESPACE: str = env.str("TEMPORAL_NAMESPACE", default="default")
TEMPORAL_TASK_QUEUE: str = (
    env.str("TEMPORAL_TASK_QUEUE", default="")
    or f"djb-{_database_name_in_use.removeprefix('djb_')}"
)

# --- The machinery lifetime class (ADR platform-lifecycle-1) ------------------
# A Temporal Schedule is infinitely durable by construction. The queue above is
# derived from the CHECKOUT and is therefore ephemeral by construction. Durable
# object, mortal identity — and the leak that mismatch mints is not a missing
# reaper, it is a lifetime class nobody declared.
#
# So it is declared. `deployment` means the machinery outlives the process that
# created it: Schedule objects are created on the server and the server starts
# the runs, which is what buys catch-up across a deploy gap and a visible
# missed-run history. `process` means the machinery lives exactly as long as the
# worker that declared it: NO Schedule object is ever created, the worker starts
# the same sweeps itself — once at startup and then on the declared cadence —
# and it deletes any durable schedule an earlier build of this checkout left
# behind.
#
# **The environment is distinguished by declaration and never by name.** There
# is no branch test here, no checkout-name test, no "is this a worktree"
# heuristic: a settings module states its class, the environment variable
# overrides it anywhere, and that is the whole of it. A name-shaped conditional
# would be a guess wearing a policy, and it would be wrong the first time
# somebody ran a real deployment out of a directory called `worktree`.
#
# `base` declares `deployment` — the inherited behaviour, bit-for-bit — so that
# an environment nobody has thought about yet keeps what it had. `local` and
# `test` declare `process`; `production` re-declares `deployment` in its own
# file so that reading that file answers the question.

MACHINERY_DEPLOYMENT = "deployment"
MACHINERY_PROCESS = "process"
MACHINERY_LIFETIMES = (MACHINERY_DEPLOYMENT, MACHINERY_PROCESS)


def machinery_lifetime(default: str) -> str:
    """The declared lifetime class, with the environment able to override it.

    Called by each settings module with its own default, which is what makes
    the default a *declaration* rather than a derivation: the value is either
    written in a settings module or written in the environment, and there is no
    third source it could be inferred from.

    An unrecognised value is refused rather than treated as one of the two.
    Silently falling back to `deployment` would create durable objects in a
    checkout that asked for none — the exact leak this setting exists to close —
    and silently falling back to `process` would stop a production deployment's
    schedules with no line anywhere saying so.

    An **empty** value is not an unrecognised one: `.env.example` ships the slot
    blank on purpose, exactly as `TEMPORAL_TASK_QUEUE` above does, so that a
    fresh clone takes its settings module's declaration rather than having to
    know which word to write.
    """
    value = env.str("TEMPORAL_MACHINERY_LIFETIME", default="") or default
    if value not in MACHINERY_LIFETIMES:
        raise ImproperlyConfigured(
            f"TEMPORAL_MACHINERY_LIFETIME={value!r} is not a lifetime class. It is "
            f"one of {MACHINERY_LIFETIMES}: 'deployment' creates durable Temporal "
            "Schedules that outlive this process, 'process' creates none and runs "
            "the same sweeps from the live worker."
        )
    return value


TEMPORAL_MACHINERY_LIFETIME: str = machinery_lifetime(MACHINERY_DEPLOYMENT)

# --- Encryption -------------------------------------------------------------
# Fernet key for per-tenant connection credentials. `production` refuses to
# start without one; a laptop falls back to the published development value in
# `.env.example`, which is worth nothing and is meant to be.

CONNECTIONS_ENCRYPTION_KEY: str = env.str("CONNECTIONS_ENCRYPTION_KEY", default="")

# --- Authentication ---------------------------------------------------------
# How stale `ApiToken.last_used_at` is allowed to get. Every authenticated
# machine request would otherwise write to the token row, turning a read into a
# read plus a write on the hottest path in the API; 5 minutes is precise enough
# to answer "is this token still in use" and cheap enough to be free.

ACCOUNTS_TOKEN_TOUCH_SECONDS: int = env.int("ACCOUNTS_TOKEN_TOUCH_SECONDS", default=300)

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS: list[dict[str, Any]] = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-allauth: local email accounts only. Headless, MFA and every social
# provider stay off; a product turns on what it needs.
# The signup hook that turns a pending `core.Invitation` into a `Membership`.
# It is an adapter and not a signal on purpose (house rule 4): a `post_save` on
# `User` fires for every user a test or a command ever made, and cannot tell
# that apart from somebody actually signing up.
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
LOGIN_REDIRECT_URL = "/"

# --- The local password door is retired (ADR ident-4) ------------------------
# **Zitadel hosts every interactive authentication, including the passwords of
# local users.** Two credential stores is the shape where "disable this person"
# has to be done twice and is done once; the owner closed that choice.
#
# `SOCIALACCOUNT_ONLY` is allauth's own switch for it, and it is stronger than
# anything an adapter could do, because it removes URLs rather than refusing at
# them: `signup/`, `password/change/`, `password/set/` and the whole password
# reset flow **stop existing** (404), and a POST to `login/` raises
# `PermissionDenied` before a form is ever bound. A GET of `login/` still
# renders, which is what lets the page offer the way in.
#
# `ACCOUNT_LOGIN_METHODS` and `ACCOUNT_SIGNUP_FIELDS` above are kept rather than
# deleted: they describe the local form's shape, allauth still validates them
# against each other in its own system checks, and a product that reopens local
# accounts changes one setting here instead of reconstructing two.
SOCIALACCOUNT_ONLY = True
# Required by the switch, and checked by allauth at startup: with no local
# accounts there is no local address to send a confirmation to. The IdP asserted
# it, and `accounts.adapter` refuses any assertion that does not say verified.
ACCOUNT_EMAIL_VERIFICATION = "none"

# --- Zitadel: the identity platform this deployment runs on ------------------
# Zitadel is **deployment infrastructure**, not a tenant's integration: there is
# one instance per deployment, it is configured by environment, and it is
# therefore not a `connections.Connection` row. That is the stated distinction
# (ADR ident-2) — a `Connection` belongs to a tenant and carries a tenant's
# credential; this belongs to the installation.
#
# `ZITADEL_ISSUER` is what the discovery document reports as `issuer` and what
# every redirect, audience and management URL is built from. `ZITADEL_PAT` is
# the platform machine user's personal access token, minted once by Zitadel's
# first-instance bootstrap into a docker volume and copied into `.env` by
# `./scripts/setup.sh` — it is never in this repository, and `.env.example`
# ships it deliberately empty.
#
# **`ZITADEL_PAT` is named here and in `apps/accounts/zitadel.py`, and nowhere
# else.** House rule 27 is what keeps that true: this module is where the
# environment is read, that module is where the credential is used, and a third
# reader would be a second place the secret could leak from.
ZITADEL_ISSUER: str = env.str("ZITADEL_ISSUER", default="")
ZITADEL_PAT: str = env.str("ZITADEL_PAT", default="")
# How long one management call may take. See `accounts.zitadel.DEFAULT_TIMEOUT`
# for why there is a number here at all.
ZITADEL_MANAGEMENT_TIMEOUT: float = env.float("ZITADEL_MANAGEMENT_TIMEOUT", default=10.0)
# What `zitadel_seed` names the objects it makes. They are settings rather than
# command constants because a second deployment against the same instance — a
# staging tree beside a development one — needs to be able to not collide.
#
# The project defaults to PRODUCT_NAME, so naming the product names its project
# too. **Changing it after a seed does not rename anything.** `zitadel_seed`
# finds-or-creates by name (`accounts.zitadel.ensure_project`), so a new value
# against an already-seeded instance makes a SECOND project with fresh
# applications and fresh client ids — and the `ZITADEL_CLIENT_ID` in `.env`
# would still point at the old one. Renaming a live deployment's project is a
# deliberate act against the management API, not a settings edit; until then,
# pin the old name in that deployment's `.env`.
# Empty is treated as unset, so this line and compose's `${ZITADEL_ORG_NAME:-…}`
# mean the same thing: `.env.example` ships the key blank, and a blank key
# falls through to PRODUCT_NAME rather than naming a project "".
ZITADEL_PROJECT_NAME: str = env.str("ZITADEL_PROJECT_NAME", default="") or PRODUCT_NAME
ZITADEL_BROWSER_APP_NAME: str = env.str("ZITADEL_BROWSER_APP_NAME", default="Web")
ZITADEL_MCP_RESOURCE_NAME: str = env.str("ZITADEL_MCP_RESOURCE_NAME", default="MCP")
ZITADEL_MCP_CLIENT_NAME: str = env.str("ZITADEL_MCP_CLIENT_NAME", default="MCP Client")
# The person `zitadel_seed` leaves a laptop able to sign in as. Published
# development values, worth nothing, and `zitadel_seed` refuses to create the
# user at all unless DEBUG is on — the same guard `seed` already carries.
ZITADEL_DEV_USER_EMAIL: str = env.str(
    "ZITADEL_DEV_USER_EMAIL", default="dev@djangobootstrap.localhost"
)
ZITADEL_DEV_USER_PASSWORD: str = env.str("ZITADEL_DEV_USER_PASSWORD", default="Password1!")

# --- Zitadel as the browser relying party (ADR ident-4, P0 W2-R3) ------------
# The OIDC client `zitadel_seed` made, as an application signs in with it. The
# id and the secret are printed **once**, by that command, at creation — Zitadel
# never shows a client secret twice — so they are copied into `.env` by a human
# and are empty here, exactly as `ZITADEL_PAT` is.
#
# **Empty disables the provider entirely**, the same way `GOOGLE_WORKSPACE_DOMAINS`
# does above and for the same reason: a deployment that half-configured a login
# door should have no door, not a door that fails at the far end of a redirect.
ZITADEL_CLIENT_ID: str = env.str("ZITADEL_CLIENT_ID", default="")
ZITADEL_CLIENT_SECRET: str = env.str("ZITADEL_CLIENT_SECRET", default="")
# The provider id in the callback URL — `/accounts/oidc/<id>/login/callback/`.
# It is a constant rather than a literal because **three things have to agree on
# it**: this settings block, the redirect URI `zitadel_seed` registers with
# Zitadel (`BROWSER_CALLBACK_PATH`), and the login page's link. A disagreement
# is a redirect_uri mismatch at the far end of somebody else's login screen,
# which is the least debuggable failure in this whole chain.
ZITADEL_PROVIDER_ID = "zitadel"

# --- The MCP door as an OAuth 2.1 resource server (ADR ident-3, P0 W2-R4) ----
# A third-party client (an assistant, a DCR client) reaches `/mcp` with an
# access token Zitadel issued. `apps/accounts/oauth.py` validates it here, as a
# **resource server**: signature against the published JWKS, issuer, expiry, and
# — the half people forget — **audience**.
#
# Audience is what stops a token minted for some other API in this instance from
# working here. Zitadel puts the project id and the API applications' client ids
# in `aud`; either identifies this resource, so both are accepted and a
# deployment records whichever its tokens actually carry. Empty means the
# resource server is **off**: no audience to check against is not "accept
# anything", it is "there is no OAuth door", and `oauth.py` refuses accordingly.
ZITADEL_MCP_AUDIENCE: list[str] = [
    value.strip() for value in env.list("ZITADEL_MCP_AUDIENCE", default=[]) if value.strip()
]

# How long a fetched JWKS is reused before it is fetched again.
#
# **This is the token-revocation latency, and it is a named guess** — the rung's
# recorded blind spot. A JWT is self-contained, so a token revoked at Zitadel
# stays cryptographically valid here until it expires; rotating the *signing
# key* is the only revocation this cache delays, and it delays it by at most
# this many seconds. Five minutes is pyjwt's own default and short enough that a
# key rotation converges within a deploy window. Introspection would make
# revocation immediate at the cost of a network round trip on every call; that
# trade is not made here, and this line is where it would be.
ZITADEL_JWKS_CACHE_SECONDS: int = env.int("ZITADEL_JWKS_CACHE_SECONDS", default=300)

# --- Identity providers ------------------------------------------------------
# Two doors, and they answer different questions (`architecture.md`, "Auth &
# identity"):
#
# * **Workforce** — the people who build and run this product sign in with
#   Google Workspace, restricted to the organisation's own domains. Google
#   authenticates; it grants nothing. A fresh workforce login lands with no
#   membership and, tenancy failing closed, sees nothing at all until somebody
#   invites them.
# * **Customers** — each tenant may bring its own IdP as an
#   `accounts.SsoConnection`. Since W2-R5 the row is materialised as an external
#   provider *inside Zitadel* (`accounts.services.sync_identity_config`) rather
#   than resolved into an allauth app of ours, and `accounts.SsoDomain` routes
#   an address to it. Nothing about a customer's IdP is in this file, and that
#   is still the point: adding one is a row, not a deploy.
#
# **`GOOGLE_WORKSPACE_DOMAINS` empty disables the Google provider entirely.** Not
# "allows every domain" — the opposite. A deployment that set credentials and
# forgot the domain list would otherwise let anybody with a Google account
# create a user here, and the failure would look exactly like success.

GOOGLE_OAUTH_CLIENT_ID: str = env.str("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET: str = env.str("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_WORKSPACE_DOMAINS: list[str] = [
    domain.strip().lower().lstrip("@")
    for domain in env.list("GOOGLE_WORKSPACE_DOMAINS", default=[])
    if domain.strip()
]

SOCIALACCOUNT_ADAPTER = "apps.accounts.adapter.SocialAccountAdapter"

# An account arriving through an IdP does not get an email-confirmation round
# trip: the IdP already asserted the address, and the adapter refuses any
# assertion where it did not (`accounts.adapter`, "verified-email trust").
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_EMAIL_REQUIRED = True
# No interstitial signup form. The whole promise of SSO is that signing in is
# one click; a form asking for the address the IdP just asserted is not that.
SOCIALACCOUNT_AUTO_SIGNUP = True
# **Off, and this is the security-relevant one.** With it on, allauth would
# attach an incoming social account to any local user with the same address —
# which turns "can receive mail at this address, or can make an IdP claim it"
# into "can take over that account". The linking this product does do is in
# `accounts.adapter`, gated on the provider actually asserting `email_verified`.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False

SOCIALACCOUNT_PROVIDERS: dict[str, Any] = {
    "google": {
        "APPS": (
            [
                {
                    "client_id": GOOGLE_OAUTH_CLIENT_ID,
                    "secret": GOOGLE_OAUTH_CLIENT_SECRET,
                    "key": "",
                }
            ]
            if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_WORKSPACE_DOMAINS
            else []
        ),
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {
            # Google's own account-chooser hint. It is a convenience for the
            # person signing in and **not** a control: the adapter re-checks the
            # asserted address against `GOOGLE_WORKSPACE_DOMAINS` regardless,
            # because a parameter in a URL is a suggestion to the IdP, not a
            # promise to us.
            "hd": GOOGLE_WORKSPACE_DOMAINS[0] if GOOGLE_WORKSPACE_DOMAINS else "",
        },
    },
    # No `APPS` key at all: every OpenID Connect app is a `SsoConnection` row,
    # built at request time by the adapter.
    "openid_connect": {
        # **One static app: Zitadel, the deployment's own identity platform.**
        # It is here rather than in a row because it is not any tenant's
        # configuration — it is the installation's (ADR ident-2, the same
        # distinction that makes `ZITADEL_PAT` a setting and a `Connection` a
        # row).
        #
        # **And it is the only one.** A customer's own IdP is still a
        # `SsoConnection` row, but W2-R5 re-pointed it: the row is materialised
        # as an external provider inside Zitadel, so there is nothing here to
        # enumerate and no per-connection allauth app to build. A login page
        # listing every tenant's connection would have been a customer list
        # rendered as buttons; now there is one button, and home-realm discovery
        # decides which provider it hints at.
        "APPS": (
            [
                {
                    "provider_id": ZITADEL_PROVIDER_ID,
                    "name": "Zitadel",
                    "client_id": ZITADEL_CLIENT_ID,
                    "secret": ZITADEL_CLIENT_SECRET,
                    # allauth appends `/.well-known/openid-configuration`
                    # itself; the issuer is what that document reports as
                    # `issuer`, and what every audience is checked against.
                    "settings": {"server_url": ZITADEL_ISSUER},
                }
            ]
            if ZITADEL_CLIENT_ID and ZITADEL_ISSUER
            else []
        ),
        # **PKCE on, explicitly.** allauth's OAuth2 default is off, and a
        # confidential web client is the case where people argue it is
        # optional — it is not: an authorization code intercepted between the
        # IdP's redirect and this callback is useless without the verifier, and
        # the cost is one hash. Asserted over the wire in `test_rp_login.py`.
        "OAUTH_PKCE_ENABLED": True,
    },
}

# --- SAML --------------------------------------------------------------------
# **Not built, and named rather than left to be discovered.** `SsoConnection`
# carries `protocol="saml"` in its vocabulary and `services.create_sso_connection`
# refuses it. The reason is a dependency, not a design: allauth's SAML support
# needs `python3-saml`, which needs `xmlsec`, which needs libxml2 and libxmlsec1
# headers present at *build* time on every machine that installs this template —
# a laptop, a CI runner, and the production image. Trading a green install on
# three platforms for a protocol no customer has asked for yet is a bad trade.
#
# **The trigger** is the first customer whose IdP does not speak OIDC. Turning it
# on is: add `django-allauth[saml]` to `pyproject.toml`, add
# `allauth.socialaccount.providers.saml` to `THIRD_PARTY_APPS`, add the system
# packages to `Dockerfile` and the CI job, extend `list_apps` in
# `accounts.adapter` with the SAML shape (allauth's own per-organisation
# pattern: one app per `organization_slug`), and drop the refusal in
# `create_sso_connection`. The model, the domains, the identities, the JIT
# provisioning and the home-realm discovery are all protocol-agnostic already.
SSO_SAML_ENABLED = False


# --- API --------------------------------------------------------------------
# django-ninja, mounted at `/api/v1/`: the version is in the path from day one,
# so a breaking change is a `v2` router beside `v1` rather than a negotiation
# nobody wrote down. Lists are CURSOR-paged (ADR core-18): the seam is
# `apps.core.api.pagination`, the wire controls are `?cursor=` and `?limit=`,
# and these two are the default and the ceiling a route that says nothing falls
# back to. The names keep `PAGE_SIZE` because that is what they mean to an
# operator — how many items come back at a time — and renaming an environment
# variable would break every deployment for a word.

API_PAGE_SIZE: int = env.int("API_PAGE_SIZE", default=50)
API_MAX_PAGE_SIZE: int = env.int("API_MAX_PAGE_SIZE", default=200)

NINJA_PAGINATION_PER_PAGE = API_PAGE_SIZE
NINJA_PAGINATION_MAX_PER_PAGE_SIZE = API_MAX_PAGE_SIZE

# --- Rate limiting ----------------------------------------------------------
# Two limits, two questions (`apps/core/throttling.py`): `auth` is "is this one
# client looping", `tenant` is "is this one customer taking more than their
# share". Counted in the shared Redis cache, so the limit belongs to the
# deployment and not to each process — four processes with a local counter is a
# limit four times higher than the one you wrote down.

NINJA_DEFAULT_THROTTLE_RATES: dict[str, str | None] = {
    "auth": env.str("THROTTLE_AUTH_RATE", default="600/min"),
    "tenant": env.str("THROTTLE_TENANT_RATE", default="1200/min"),
    "anon": env.str("THROTTLE_ANON_RATE", default="60/min"),
    "user": env.str("THROTTLE_USER_RATE", default="600/min"),
}

# How long a stored `Idempotency-Key` response stays replayable.
IDEMPOTENCY_TTL_HOURS: int = env.int("IDEMPOTENCY_TTL_HOURS", default=24)

# How long a *dispatched* outbox row is kept before the daily housekeeping
# workflow removes it (`apps.events.activities.purge_expired_records`). Long
# enough to answer "did that event go out last month", short enough that the
# outbox does not become a second copy of the event log — the `Event` rows
# themselves are never purged by this.
EVENTS_OUTBOX_RETENTION_DAYS: int = env.int("EVENTS_OUTBOX_RETENTION_DAYS", default=30)

# How long the two kinds of presigned URL `apps/files` mints stay valid, in
# seconds (ADR files-2 § "Presigned URLs"). These are the only knobs that reach
# those signatures: `AWS_QUERYSTRING_EXPIRE` below configures `STORAGES` and
# nothing in `apps/files/storage.py` reads it, which is the confusion this
# pair closes.
#
# FIVE MINUTES for a download, because a presigned URL is a stateless signature
# and there is no such thing as revoking one — a longer life turns every issuance
# into a durable bearer credential. A UI that needs the bytes again re-issues, and
# re-issuance re-audits, so the audit trail approximates *use* at this resolution.
# Raising it trades that resolution away.
FILES_DOWNLOAD_URL_TTL: int = env.int("FILES_DOWNLOAD_URL_TTL", default=300)

# FIFTEEN MINUTES for an upload, because a large file on a slow link has to get
# started. It can afford to be longer than the download because whatever lands in
# that pending key is streamed and digested by `FinalizeUpload` before any row
# calls it stored, and the signature carries `If-None-Match: *`, so a replayed
# upload URL cannot overwrite what has already been finalized.
FILES_UPLOAD_URL_TTL: int = env.int("FILES_UPLOAD_URL_TTL", default=900)

# --- CORS and CSRF ----------------------------------------------------------
# The machine door needs neither: a bearer token is not a cookie, so there is
# nothing for another origin to ride on. The human door needs both — a browser
# sends the session cookie whoever asked it to, which is exactly what CSRF is
# about, so a session-authenticated write must carry `X-CSRFToken` from the
# `csrftoken` cookie (`ensure_csrf_cookie` on whatever page the front end
# bootstraps from, then the header on every unsafe request).
#
# `CORS_ALLOWED_ORIGINS` is an explicit list and there is deliberately no
# allow-all switch: with credentials, allowing every origin is the same as
# having no origin policy at all.

CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS: bool = env.bool("CORS_ALLOW_CREDENTIALS", default=True)
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    # The two scoping headers, lowercased. They are the values of
    # `apps.core.middleware.TENANT_HEADER` and `ORG_HEADER` and are typed here
    # rather than imported because settings is read before the app registry is
    # ready and that module imports models — so the constant cannot travel this
    # way, and the census that keeps the two spellings in step is a check, not
    # an import (rule 40). `x-org` was missing until this pair was added:
    # without it a cross-origin browser client cannot send `X-Org` at all, so every one of
    # its requests silently lands on the default hat rather than the one the
    # user chose — no error anywhere, which is why no door test saw it.
    "x-tenant",
    "x-org",
    "x-request-id",
    "x-correlation-id",
    "idempotency-key",
    # The webhook receiver's two, found by the census when it first ran.
    # They were missing for the same reason `x-org` was: the list was typed from
    # the headers somebody remembered, and `apps/connections/api.py` reads
    # `SIGNATURE_HEADER` and `EVENT_TYPE_HEADER` under `/api/`. A signed
    # delivery normally arrives server-to-server, where CORS is not consulted at
    # all — but the list is a CENSUS of what the HTTP doors read, and the moment
    # it becomes a list of what somebody thought a browser would need, it starts
    # drifting again. If a header genuinely must not be browser-sendable, that
    # is a decision to write down in rule 40's scope, not a line to leave out.
    "x-signature",
    "x-event-type",
)
# What a cross-origin browser client may READ off a response. It is a census of
# what this deployment actually stamps, lowercased — the population
# `apps.core.api.docs.declared_response_headers()` walks — and
# `apps/core/tests/test_response_headers.py` holds the two in step, because a
# header the server stamps and CORS does not expose is the server telling the
# truth to nobody: no error, no log line, and the value simply absent in the
# browser (the same shape, one direction over).
CORS_EXPOSE_HEADERS = (
    "x-request-id",
    "x-correlation-id",
    "idempotent-replayed",
    "retry-after",
    # ADR core-19: the throttle's numbers, so a browser client can back off
    # before it is refused rather than after.
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)

# --- Email ------------------------------------------------------------------

EMAIL_BACKEND: str = env.str(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST: str = env.str("EMAIL_HOST", default="localhost")
EMAIL_PORT: int = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER: str = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD: str = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS: bool = env.bool("EMAIL_USE_TLS", default=False)
# A mail host that accepts the connection and then never answers must not hold
# an activity open until whatever the socket's own timeout happens to be.
EMAIL_TIMEOUT: int = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL: str = env.str("DEFAULT_FROM_EMAIL", default="no-reply@localhost")
SERVER_EMAIL: str = env.str("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# **The ESP's own settings, discovered rather than enumerated (ADR comms-12).**
#
# `EMAIL_BACKEND` names the provider and nothing else does — `smtp` on a laptop
# pointing at Mailpit, `locmem` under pytest, `anymail.backends.<esp>.EmailBackend`
# for any of the fifteen ESPs Anymail supports. Each of those backends reads its
# credential out of `settings.ANYMAIL` under its own key (`RESEND_API_KEY`,
# `MAILGUN_API_KEY`, `POSTMARK_SERVER_TOKEN`, …), so the alternative to this loop
# is a line in this file per ESP per credential — fifteen providers' worth of
# settings a template carries so that one product can use one of them.
#
# So the rule is the prefix: **an environment variable named `ANYMAIL_<KEY>` with
# a value becomes `ANYMAIL["<KEY>"]`, and no ESP is named in this file at all.**
# Switching provider stays what `architecture.md` promised it would be — a
# setting and a credential — and adding one is adding an environment variable to
# a deployment's manifest, never an edit here.
#
# This is the one place this module reads the environment by pattern rather than
# by name, which is why it is spelled out: the module docstring's "`.env.example`
# is the complete list" holds for every *named* variable, and `.env.example`
# carries the one slot this template's own deployments use
# (`ANYMAIL_RESEND_API_KEY`) so the pattern has a worked example to copy.
#
# **Webhook signature secrets are deliberately NOT here.** Anymail would read one
# from this dict, but this product's inbound signatures are checked per tenant
# against `Connection.webhook_secret` — encrypted, on the row, one per
# integration (`apps/comms/providers.verify_status_webhook`). A deployment-wide
# signing secret in settings would be every tenant's provider sharing one.
ANYMAIL: dict[str, str] = {
    name.removeprefix("ANYMAIL_"): value
    for name, value in sorted(os.environ.items())
    if name.startswith("ANYMAIL_") and value
}

# --- Feature flags ----------------------------------------------------------
# The deployment-wide default for each flag; a tenant overrides it in its own
# `Tenant.settings` (`apps/core/flags.py`). Off is the default and there is no
# allow-all: a flag that defaults on does nothing until somebody remembers to
# turn it off, which is the opposite of what it is for.

FEATURE_FLAGS: dict[str, bool] = {}

# --- Internationalisation ---------------------------------------------------

# English only, and **`USE_I18N` is off by default** (`architecture.md`). Not
# because translation is unimportant, but because leaving it on costs a locale
# lookup and a translation-catalogue consultation on every string, in every
# request, to produce English — and because a product that turns it on later
# does so as a recorded decision with somebody actually translating something.
# A product that needs it sets `USE_I18N=1` and says so in its own
# `architecture.md`.
#
# **`TIME_ZONE` and `USE_TZ` are a different question and are unaffected.**
# Everything is stored in UTC (`apps/core/time.py`); what a human is *shown* is
# decided per tenant by `Tenant.timezone` and `Tenant.locale`, which already
# exist on the model and are validated against the real zone database by
# `core.services.update_tenant_settings`. Display is a tenant's setting; the
# deployment's `TIME_ZONE` is only the fallback.
LANGUAGE_CODE: str = env.str("LANGUAGE_CODE", default="en-us")
TIME_ZONE: str = env.str("TIME_ZONE", default="UTC")
USE_I18N: bool = env.bool("USE_I18N", default=False)
USE_TZ = True

# --- Static and media -------------------------------------------------------

STATIC_URL: str = env.str("STATIC_URL", default="/static/")
STATIC_ROOT: Path = BASE_DIR / env.str("STATIC_ROOT", default="staticfiles")
MEDIA_URL: str = env.str("MEDIA_URL", default="/media/")
MEDIA_ROOT: Path = BASE_DIR / env.str("MEDIA_ROOT", default="media")

# THIRD-PARTY BROWSER BYTES LIVE OUTSIDE `apps/`, under `/static/vendor/`.
#
# Everything else in this project is found by discovery — an app's `static/`
# directory is picked up by `AppDirectoriesFinder` and nothing has to be
# registered. A vendored browser bundle is the one thing that cannot live
# there, and the reason is a house rule doing its job: rule 23's secret scan
# reads every file under `apps/`, `config/` and `scripts/` for four
# high-signal patterns, and a minified third-party bundle contains those
# strings as placeholders and example values — Scalar's mTLS input field
# carries a PEM private-key header as its placeholder text, which is one of
# the four patterns exactly. Vendoring under `apps/core/static/` turned rule
# 23 red on bytes nobody in this repository wrote. The rule is right about its
# own subject — the code we write — so the fix is to put the code we did NOT
# write somewhere else, rather than to widen the rule's blind spot.
#
# `vendor/` is that somewhere: one directory, third-party artifacts only, each
# pinned by version and checksum in `vendor/<name>/MANIFEST.toml`, which is
# the stated supply-chain posture for assets no Python audit can see. The
# prefixed form keeps the namespace in the URL, so `/static/vendor/...` says
# what it is to anyone reading a page source or a proxy log.
STATICFILES_DIRS: list[tuple[str, Path]] = [("vendor", BASE_DIR / "vendor")]

# --- Object storage ----------------------------------------------------------
# `django-storages` with S3, switched on by the presence of a bucket name and by
# nothing else. There is no `USE_S3` flag, because a deployment that sets a
# bucket and forgets the flag writes its uploads onto a container filesystem
# that disappears at the next deploy — silently, and only discovered when
# somebody asks for a file back.
#
# Credentials are deliberately absent from this file's defaults: an instance
# role or a workload identity is how a deployment should be authenticating, and
# boto3 finds those on its own. `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
# are read only because a laptop pointing at MinIO has nothing else.
#
# Keys are built by `apps.files.storage.version_key` — `t/<tenant pk>/f/<file
# pk>/v/<n>` — and by nothing else, which house rule 48 enforces: one door to the
# object store, and it is `apps/files/storage.py`. (This comment named
# `apps.core.storage.tenant_prefixed_key` until an earlier rung; that module
# was deleted once its last caller went away, and a key carrying a renamable
# slug and a user-supplied filename is exactly what ADR files-2 rules against.)
#
# `STORAGES` below is the FIFTH DOOR rule 48 fences: it points `default_storage`
# at this same bucket the moment a bucket is named, so `default_storage.open()`
# reads an object and `.url()` signs one with no boto3 import anywhere. That is
# why no module under `apps/` may import `django.core.files.storage`.

AWS_STORAGE_BUCKET_NAME: str = env.str("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME: str = env.str("AWS_S3_REGION_NAME", default="")
# `None` rather than `""` when unset: boto3 reads "no endpoint override" from
# None and would take an empty string literally.
AWS_S3_ENDPOINT_URL: str | None = env.str("AWS_S3_ENDPOINT_URL", default="") or None
AWS_S3_CUSTOM_DOMAIN: str | None = env.str("AWS_S3_CUSTOM_DOMAIN", default="") or None
AWS_ACCESS_KEY_ID: str = env.str("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY: str = env.str("AWS_SECRET_ACCESS_KEY", default="")

# Private by default and signed on read: an uploaded file belongs to one tenant,
# and a public-read bucket makes every key a URL anyone who guesses it can
# fetch. A product that genuinely wants public assets says so in its own
# settings, with the reason.
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH: bool = env.bool("AWS_QUERYSTRING_AUTH", default=True)
AWS_QUERYSTRING_EXPIRE: int = env.int("AWS_QUERYSTRING_EXPIRE", default=3600)
# Never silently overwrite: two tenants' files with the same name must not
# become one file, and a retried upload must not clobber the original.
AWS_S3_FILE_OVERWRITE = False

_DEFAULT_FILE_STORAGE: dict[str, Any] = (
    {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME or None,
            "endpoint_url": AWS_S3_ENDPOINT_URL,
            "custom_domain": AWS_S3_CUSTOM_DOMAIN,
            "default_acl": AWS_DEFAULT_ACL,
            "querystring_auth": AWS_QUERYSTRING_AUTH,
            "querystring_expire": AWS_QUERYSTRING_EXPIRE,
            "file_overwrite": AWS_S3_FILE_OVERWRITE,
        },
    }
    if AWS_STORAGE_BUCKET_NAME
    else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
)

STORAGES: dict[str, dict[str, Any]] = {
    "default": _DEFAULT_FILE_STORAGE,
    # Plain in every environment but production, which swaps in WhiteNoise's
    # compressed manifest storage. A manifest on a laptop means every template
    # change needs a `collectstatic` before the page renders again, and a
    # missing-file error where a developer expected a page.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- Security ---------------------------------------------------------------
# Secure by default; `local` and `test` relax only what a laptop cannot satisfy.

SECURE_SSL_REDIRECT: bool = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS: int = env.int("SECURE_HSTS_SECONDS", default=31_536_000)
SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD: bool = env.bool("SECURE_HSTS_PRELOAD", default=True)
SESSION_COOKIE_SECURE: bool = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE: bool = env.bool("CSRF_COOKIE_SECURE", default=True)
# The two probe endpoints answer over plain HTTP instead of being redirected.
# A liveness probe does not follow a 301: kubelet, an ALB target group and a
# compose healthcheck all read the status code they were handed, so with
# SECURE_SSL_REDIRECT on and no exemption every replica in a fleet reports
# unhealthy and gets restarted forever. Safe because these two are the only
# paths in the tree that carry no credential and return no data — see
# `apps/core/health.py`. Everything else still redirects.
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
# `X-Forwarded-Proto` is only trustworthy when something in front of this
# process sets it and strips a client-supplied one. Trusting it unconditionally
# lets any client claim its plain-HTTP request arrived over TLS, which turns
# SECURE_SSL_REDIRECT and the secure-cookie flags into decoration. So it is off
# unless the deployment says it is behind such a proxy.
BEHIND_PROXY: bool = env.bool("BEHIND_PROXY", default=False)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Search -----------------------------------------------------------------
# The Meilisearch address and master key, **read here and used in
# `apps/search/engine.py`, and nowhere else** — which is house rule 33's shape,
# not an exception to it: the rule's own scope entry for this tree says so in as
# many words ("Where the environment is read into settings. Naming a variable in
# order to read it out of the environment is not the leak this guards"), and its
# violation message names the pair of files.
#
# **They were `os.environ` reads in `engine.py` until SRCH-FIX (2026-08-25)**,
# which was the one external service in this product escaping
# `config/settings/test.py`'s pin — so the suite dialled whatever the
# developer's `.env` said, and a checkout pointed at a black-holed Meilisearch
# ran a different suite from CI's. It cost a bisect: the reconcile machine
# retried without bound against an address nobody else had, and
# `test_the_sweeps_still_run_from_a_live_worker` died 22s later saying only
# "No completion event found". `guards.py` had predicted this move and named
# the rung that should have made it; this is that move, one rung late.
#
# Settings rather than the environment is also what lets a test that WANTS the
# real engine arm it for itself (`apps/search/tests/conftest.py::live_meili`),
# which is the same shape `apps/files/tests/conftest.py::bucket` uses for MinIO.
MEILI_URL: str = env.str("MEILI_URL", default="http://127.0.0.1:7700")
MEILI_MASTER_KEY: str = env.str("MEILI_MASTER_KEY", default="")

# --- Observability ----------------------------------------------------------
# One sink: OpenTelemetry over OTLP to ClickStack. `apps/core/observability.py`
# is the only module that configures any of this, and it is called once from
# `CoreConfig.ready`.
#
# With no endpoint set — a laptop, the test suite — tracing still runs (so
# `trace_id` is on every log line where you are actually reading it) but nothing
# is exported and no library is patched. `docker compose --profile observability
# up` starts the collector and ClickStack; point this at the collector.

OTEL_EXPORTER_OTLP_ENDPOINT: str = env.str("OTEL_EXPORTER_OTLP_ENDPOINT", default="")
OTEL_SERVICE_NAME: str = env.str("DJB_SERVICE_NAME", default="web")
DJB_ENVIRONMENT: str = env.str("DJB_ENVIRONMENT", default="local")

# --- Logging ----------------------------------------------------------------
# structlog renders the line; stdlib logging carries it. The formatter is
# therefore the message and nothing else — a JSON document with a level and a
# timestamp printed in front of it is not a JSON document.

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {"format": "{message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "structured"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
