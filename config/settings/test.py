"""Settings for pytest.

Fast password hashing and no HTTPS. The test database is Django's default
`test_` + DATABASE_NAME, so each worktree tests against its own database.
"""

import os

from .base import *  # noqa: F403
from .base import (
    DATABASES,
    MACHINERY_PROCESS,
    SOCIALACCOUNT_PROVIDERS,
    STORAGES,
    machinery_lifetime,
)
from .guards import DEV_CONNECTIONS_ENCRYPTION_KEY, TEST_SECRET_KEY

DEBUG = False
SECRET_KEY = TEST_SECRET_KEY
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# No persistent connections under pytest, AND NO POOL. `base` pools by default
# (ADR config-1) and, before that, reused connections for 60 seconds; both are
# right for a deployment and wrong here, for one reason: the workflow tests run
# activities on worker threads, each thread holds a connection open past the end
# of the test, and the run ends with Django unable to drop its own test database
# ("is being accessed by other users"). A left-behind `test_<db>` is the next
# run's confusing failure. A pool makes that worse rather than better — its own
# maintenance threads hold `min_size` connections open with no test to attribute
# them to.
#
# So the ambient suite runs unpooled and non-persistent, and **that is a
# deliberate absence, not an oversight to tidy up later**: nothing about pooling
# is under test in the ambient world. What IS under test arms the pool for
# ITSELF — `apps/core/tests/test_connection_pool.py` imports the deployment's
# own settings module under a patched environment, points the assembled
# `DATABASES["default"]` at this worker's test database, and drives real threads
# through it. Same shape as `apps/files/tests/conftest.py::bucket` and
# `apps/search/tests/conftest.py::live_meili`: the test that wants the real
# thing says so, and the floor stays the world every other test can rely on.
#
# --- THE TEST DATABASE CLONES A TEMPLATE WHEN THERE IS ONE ------------
#
# Under `-n auto` every xdist worker creates and MIGRATES its own
# `test_<DATABASE_NAME>_gwN`. Measured: ten `--durations` setup entries
# of ~4.5-6s, one per worker, ~60 CPU-seconds a pass and paid twice by the full
# gate, all of it before a single assertion. `TEST["TEMPLATE"]` makes Django
# issue `CREATE DATABASE … WITH TEMPLATE …` instead, so each worker copies files
# rather than replaying the migration chain. An earlier rung published the
# template; this is the line that spends it, and it is the line
# `apps/conftest.py` specified and a verification pass found was never written.
#
# THE NAME COMES FROM THE ENVIRONMENT AND IS NEVER DERIVED HERE.
# `scripts/test.sh` asks db.sh for `db_template_name` and exports
# `DJB_TEST_DB_TEMPLATE` **only when that template really exists on the server**.
# Two reasons it is that way round and not this one:
#
#   * Django REFUSES to create a test database when `TEST["TEMPLATE"]` names a
#     database that is not there — so on a fresh clone, or after the migration
#     state moves, an unconditional line here would break the suite outright
#     rather than merely fail to speed it up. Absent variable, absent key,
#     ordinary creation.
#   * Settings must not open a connection at import to find out. Every
#     `manage.py`, every management command and `check --deploy` would pay it.
#     The shell already holds the socket; this module only reads its answer.
#
# So a bare `uv run pytest` (no `scripts/test.sh`) simply migrates, exactly as it
# did before this line existed. Both directions are driven in
# `scripts/tests/test_db_template.sh`.
_TEST_DB_TEMPLATE = os.environ.get("DJB_TEST_DB_TEMPLATE", "").strip()

DATABASES = {
    "default": {
        **DATABASES["default"],
        "CONN_MAX_AGE": 0,
        # `pool` is dropped by name rather than by replacing OPTIONS wholesale,
        # so an option a checkout spelled into DATABASE_URL still reaches the
        # suite. An empty-or-absent OPTIONS is fine here: `base` always writes
        # the key.
        "OPTIONS": {
            key: value
            for key, value in DATABASES["default"].get("OPTIONS", {}).items()
            if key != "pool"
        },
    }
}
if _TEST_DB_TEMPLATE:
    DATABASES["default"]["TEST"] = {
        **DATABASES["default"].get("TEST", {}),
        "TEMPLATE": _TEST_DB_TEMPLATE,
    }

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# NO OBJECT STORAGE IN THE AMBIENT TEST WORLD, whatever this laptop's `.env`
# says. `base` reads AWS_STORAGE_BUCKET_NAME from the environment and naming a
# bucket is the whole switch to S3 — so without this pin a developer who has
# configured one (which `scripts/setup.sh` now does for every checkout)
# runs a DIFFERENT suite from CI's: `apps/exports` writes its archives to MinIO,
# `default_storage.url()` starts signing, `/readyz` grows a `storage` member,
# and the ten tests that name the no-bucket world fail. The same reasoning as
# TEMPORAL_ADDRESS and ZITADEL_ISSUER below: the suite measures one world, and
# it is not the one whoever ran it happens to have.
#
# A test that wants object storage names a bucket itself, through the `settings`
# fixture — `apps/files/tests/conftest.py::bucket` does exactly that, against
# the real compose MinIO.
AWS_STORAGE_BUCKET_NAME = ""
STORAGES = {**STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}

# Nothing has run `collectstatic` in a test tree, and WhiteNoise warns once per
# request about the directory that is therefore missing. Serving from the
# finders is both quieter and more honest: a test that asks for a static file
# gets the one in the source tree.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

# A throwaway key, so nothing under test has to invent one. Named in `guards`,
# which is also what refuses it in production.
CONNECTIONS_ENCRYPTION_KEY = DEV_CONNECTIONS_ENCRYPTION_KEY

# --- Temporal: nothing under pytest may reach a server ----------------------
# A test that starts a real run on the shared development server leaves an
# execution nobody will ever finish, and a worker somewhere retrying an activity
# against a database row that only existed inside a rolled-back test. The
# cycle-0 verifier measured 20 leaked per gate run and 275 stuck RUNNING (queue
# V3), and the contract has always said tests never point at the dev server
# (`build-contract.md`).
#
# Two layers, because a rule that is only a convention is not a rule:
#
# 1. this address. Port 1 is the TCP port-reservation port; nothing may listen
#    on it, and the connection is refused immediately rather than hanging on a
#    SYN timeout the way an unroutable address would;
# 2. `apps/conftest.py`'s autouse `_no_dialling_temporal` fixture, which
#    replaces the client factory with one that raises and names the way out.
#
# The tests that genuinely need a server start their own — the time-skipping
# `WorkflowEnvironment` — and point the factory at it.
TEMPORAL_ADDRESS = "127.0.0.1:1"

# And its own queue name, so that even a leak that got past both layers could
# not be picked up by the worktree's running worker.
TEMPORAL_TASK_QUEUE = "djb-tests-must-not-dial"

# --- Zitadel: nothing under pytest may reach an instance --------------------
# The same posture as Temporal above, for the same reason (ADR ident-5): the
# suite, `--loop` and CI never dial Zitadel. A gate run that configured a shared
# identity instance would leak state into the thing every other worktree logs in
# through — V3's class, reborn one layer up.
#
# Two layers again. This address is the first: port 1 is the TCP
# port-reservation port, so a connection is refused immediately rather than
# hanging on a SYN timeout. The second is structural and stronger — the
# management client is reached only from `apps/accounts/activities.py` and the
# two `zitadel_*` management commands (house rule 27), and no test drives
# either against a live instance.
#
# The PAT is blanked as the third: `accounts.zitadel` raises
# `ZitadelNotConfigured` **before** it opens a socket when either half is
# missing, so a test that somehow reached the client gets an exception naming
# this block instead of a ten-second timeout.
ZITADEL_ISSUER = "http://127.0.0.1:1"
ZITADEL_PAT = ""

# --- Meilisearch: the ambient test world has no search index ----------------
# The third instance of the posture above, and the one that was MISSING until
# a later fix. `apps/search/engine.py` read `MEILI_URL` and
# `MEILI_MASTER_KEY` straight out of `os.environ`, which made it the one
# external service in this product that the pin could not reach: the suite
# dialled whatever the developer's `.env` said. A checkout whose `.env` pointed
# at an unreachable address — a stopped container, a VPN, a stale host — ran a
# DIFFERENT suite from CI's, and it did not fail honestly: the search app's
# reconcile machine retried against the black hole without bound and
# `apps/workflows/tests/test_machinery_lifetime.py::
# test_the_sweeps_still_run_from_a_live_worker` died 22 seconds later saying
# "No completion event found". Deterministic, and attributable to nothing.
#
# Port 1 for the same reason Temporal and Zitadel use it: it is the TCP
# port-reservation port, nothing may listen on it, and a connection is REFUSED
# immediately rather than hanging on a SYN timeout the way an unroutable address
# does. A refusal is what the search circuit is built to survive (R-d: Meili
# unreachable is a degraded state answered from Postgres, never an outage), so
# the ambient suite exercises the degraded path rather than a timeout.
#
# A test that wants the real engine arms it for ITSELF, through the `settings`
# fixture — `apps/search/tests/conftest.py::live_meili` does exactly that,
# against the real compose Meilisearch, and it is the same shape
# `apps/files/tests/conftest.py::bucket` uses for MinIO.
MEILI_URL = "http://127.0.0.1:1"
MEILI_MASTER_KEY = ""  # pragma: allowlist secret

# --- Zitadel and Google: the login doors are OFF under pytest ---------------
# The block above closes the *management* door, and closes it against dialling.
# This one closes the other three — the browser relying party, the MCP resource
# server, and the workforce provider beside them — against a different failure:
# not "a test must not dial" but **a test must not read the machine it runs on**.
#
# Every value here is an `env.str(...)`/`env.list(...)` in `base.py` with an
# empty default, so until this block a developer whose `.env` armed a door armed
# it for the suite too, and a handful of assertions passed or failed depending
# on whose laptop ran them. An earlier pass found four of those and pinned each one inside
# itself; this is the same fix made once, in the floor, where the fifth test
# cannot forget it.
#
# The floor is **off**: no client id, no secret, no audience, no workforce
# domain — which every one of those settings reads as "there is no door" rather
# than "the door is open" (`base.py` says so at each of them, and
# `test_identity_doors.py` pins it). A test whose *subject* is an armed door
# arms it for itself through the `settings` fixture, which is the right place
# for it: the test then states which deployment state it is asserting about
# instead of inheriting one.
ZITADEL_CLIENT_ID = ""
ZITADEL_CLIENT_SECRET = ""  # pragma: allowlist secret
ZITADEL_MCP_AUDIENCE = []
GOOGLE_OAUTH_CLIENT_ID = ""
GOOGLE_OAUTH_CLIENT_SECRET = ""  # pragma: allowlist secret
GOOGLE_WORKSPACE_DOMAINS = []

# And the structure `base.py` *derived* from them, which is the half that makes
# the pin real rather than decorative: `SOCIALACCOUNT_PROVIDERS` is built once,
# at import, out of the values above as the environment had them — so blanking
# the scalars afterwards would leave allauth still holding the app it registered
# from the ambient `.env`, and `list_apps` would still enumerate it.
#
# Rebuilt from base's own dict rather than retyped, so a provider added there
# arrives here switched off instead of silently inherited armed. `APPS` empty is
# allauth's "not configured", and `hd` is blanked with it because base builds
# that hint from `GOOGLE_WORKSPACE_DOMAINS` and it would otherwise carry one
# machine's domain into everybody's suite.
SOCIALACCOUNT_PROVIDERS = {
    name: {
        **provider,
        "APPS": [],
        **(
            {"AUTH_PARAMS": {**provider["AUTH_PARAMS"], "hd": ""}}
            if "AUTH_PARAMS" in provider
            else {}
        ),
    }
    for name, provider in SOCIALACCOUNT_PROVIDERS.items()
}

# Tests must not need Redis running to import settings; the channel layer and
# the cache are in memory unless a test asks otherwise.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Silence the console handler so test output stays readable.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}

# --- Machinery lifetime (ADR platform-lifecycle-1) ---------------------------
# The third layer of the same posture the two blocks above take about dialling:
# a suite that created a durable Temporal Schedule would leave an object on a
# shared dev server pointed at `djb-tests-must-not-dial`, outliving the run that
# made it and every checkout that made it. `process` creates none, ever, which
# is what the harness tests assert about this settings module rather than about
# a mock.
TEMPORAL_MACHINERY_LIFETIME = machinery_lifetime(MACHINERY_PROCESS)
