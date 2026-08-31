"""What production refuses to start with.

`.env.example` ships working secrets so a laptop runs on `cp .env.example .env`.
That is a convenience with an obvious failure mode: the same file is the first
thing anyone copies onto a server, and an empty-string check does not catch it —
the value is not empty, it is *published*. A key that is in a public git
repository is not a key.

So the refusals are by value as well as by absence. The published values live
here, once, and `.env.example`, `config.settings.local` and `config.settings.
base` all take their development defaults from this module: there is no way to
change one and leave the other, and the tests that prove it read `.env.example`
from disk.

`base` taking its default from here is what makes the DATABASE_PASSWORD refusal
cover the deployment it is about. The variable *forgotten* and the
variable *set to the published value* are then the same string, refused by the
same comparison, rather than two checks that can drift apart.
"""

from __future__ import annotations

# --- What this module does NOT refuse (the declared boundary) ----
#
# `does_not_cover`, applied to a guard rather than to a house rule, and for the
# same reason: a fence whose edge lives only in the reviewer's head gets
# re-derived by the next reviewer — or, worse, assumed to run somewhere it
# never could. Three refusals are below. `.env.example`
# publishes several more credentials, each named below, and not one of them is
# refused here.
#
# COMPOSE-ONLY, NO CHOKEPOINT EXISTS. A refusal has to run somewhere, and the
# only somewhere this module owns is a settings import: `config.settings.
# production` calls `refuse_development_defaults()` while it is being read, and
# the process does not start if it raises. These never reach that moment —
# `compose.yaml` hands them straight to the `postgres`, `zitadel`, `minio` and
# `meilisearch` containers, and no settings module reads any of them (the deploy
# layer puts the belt on them, where the values are in hand — see
# WHERE THE REAL FENCE BELONGS, below, which is now a dispatched job rather
# than a promise):
#
#     ZITADEL_MASTERKEY          djb-local-development-masterkey!
#     ZITADEL_DATABASE_PASSWORD  zitadel
#     POSTGRES_PASSWORD          djb   (also Zitadel's Postgres ADMIN password)
#     ZITADEL_ADMIN_PASSWORD     Password1!
#     MINIO_ROOT_PASSWORD        minioadmin
#
# There is nothing here to compare them against. A check added to this file
# would guard values the Django process never sees — a gate standing in an open
# field, reading as coverage while covering nothing, which is worse than the
# absence it would hide.
#
# **MEILI_MASTER_KEY has left that list**, which is the move this block
# predicted. It was expected one rung and actually happened the next, one rung
# late and for a reason worth recording: the chokepoint was built but had
# `engine.py` read `os.environ` directly, so the value stayed one the Django
# process never saw — the
# prediction below was written as though the move had been made. It is a
# `config.settings.base` setting now (`MEILI_URL` beside it), which is what put
# it inside `config/settings/test.py`'s pin and inside the entry below.
#
# READ BY SETTINGS, STILL NOT REFUSED — the honest half of the boundary, since
# for these a chokepoint does exist:
#
#   * `ZITADEL_DEV_USER_PASSWORD` (`Password1!`, `config.settings.base`). Its
#     one consumer, `manage.py zitadel_seed`, refuses to create the dev user at
#     all unless DEBUG is on. That fence sits upstream of the value and is the
#     stronger of the two: it holds for a *changed* published password, which
#     an equality check here would wave straight through. A second, weaker
#     fence behind a stronger one buys a line of coverage and one more thing to
#     keep in step.
#
#   * `AWS_SECRET_ACCESS_KEY` (`minioadmin`, `config.settings.base`).
#     `.env.example` points the app-side S3 credentials at the
#     compose MinIO so that naming a bucket is the only step left on a laptop.
#     ABSENCE CANNOT BE REFUSED HERE, and that is the whole difficulty: an
#     empty value is the *correct* production posture — an instance role or a
#     workload identity, which boto3 finds by itself — so the DATABASE_PASSWORD
#     shape (absent and published refused by one comparison) does not transfer.
#     What could be refused is the published *value*, and the reason it is not
#     refused here is scope, not judgement: the declared boundary above owns
#     it, not a new refusal. **Recorded as the named candidate** — a
#     `check_object_storage_secret` that refuses `minioadmin` while allowing
#     empty, wired into `refuse_development_defaults` — for whichever future
#     work owns the storage seam, which is also where a production deployment
#     first has a bucket to point it at. Until then, the honest statement is
#     that a deployment which copied `.env.example` wholesale and named a real
#     S3 bucket would fail loudly at the first call with a bad credential
#     rather than quietly succeed — the failure mode is noise, not silence.
#
#     **THE CALL WAS TAKEN AND THE ANSWER IS YES — and it is not landed,
#     because of territory rather than judgement, which is the same reasoning
#     above and is worth being precise about.**
#
#     The verdict, on this module's OWN test: a refusal has to run somewhere,
#     and for this one a somewhere exists. `AWS_SECRET_ACCESS_KEY` is read by
#     `config.settings.base` and now has a real consumer — `apps/files/storage.py`
#     builds the boto3 client with it — so it sits on the chokepoint side of
#     this boundary and not with the compose-only values above.
#
#     What the refusal buys, stated honestly and no larger: it moves a loud
#     failure EARLIER. A deployment holding `minioadmin` against real S3 is
#     rejected at the first call whether or not this check exists; what changes
#     is that "the first call" stops being somebody's first upload, months
#     later, and becomes the process refusing to start. That is exactly the
#     value `check_database_password`'s empty branch carries, and it is the
#     whole of the case — this is not a breach being closed. (The one shape
#     where the published value would actually WORK is a production MinIO run
#     with its own default root credentials, and no check in this process can
#     see that.)
#
#     Empty stays legal, and that asymmetry with DATABASE_PASSWORD is the
#     design: an absent credential is the CORRECT production posture, because
#     boto3 then finds the instance role or the workload identity by itself.
#     So the check refuses one exact published string and nothing else, and
#     says so.
#
#     WHY IT IS NOT IN THIS FILE ALREADY. `refuse_development_defaults` is
#     handed its values by `config.settings.production`, and a
#     `check_object_storage_secret` that no caller passes a value to is a gate
#     standing in an open field — the exact thing the top of this comment
#     refuses, and it would read as coverage while covering nothing. Landing it
#     is therefore TWO files, and F1's territory is one:
#
#         config/settings/guards.py   `check_object_storage_secret`, plus
#                                     `object_storage_secret: str | None = None`
#                                     on `refuse_development_defaults`
#         config/settings/production.py
#                                     `AWS_SECRET_ACCESS_KEY` added to the
#                                     explicit `from .base import (...)` list,
#                                     and passed on the existing call
#
#     Flagged with that shape, and re-holdered. The day
#     both lines land together, this paragraph becomes a third entry under READ
#     BY SETTINGS AND NOW REFUSED.
#
#   * `MEILI_MASTER_KEY` (`djb-local-development-meili-master-key`,
#     `config.settings.base`). It arrived on this side of
#     the boundary the day `apps/search/engine.py` stopped reading `os.environ`,
#     which is the move the paragraph at the top of this file predicted.
#
#     NOT REFUSED, and the shape is `AWS_SECRET_ACCESS_KEY`'s rather than
#     `DATABASE_PASSWORD`'s: **empty is legal and is not the safe posture — it
#     is a 401.** The compose container runs with a key, so a caller that sends
#     none is refused `invalid_api_key`, and a deployment that lost the variable
#     does not get an unauthenticated engine, it gets no engine. That is why
#     absence needs no refusal here: the product already treats it as an outage
#     it survives (the search circuit degrades to Postgres and announces it;
#     the reconcile completes with a finding and the next tick retries). The
#     published VALUE could be refused the way `AWS_SECRET_ACCESS_KEY`'s
#     candidate above would be, and is not, for the same reason: that refusal
#     is two files and out of scope for a settings-only pass. Recorded here
#     rather than left to be noticed.
#
# READ BY SETTINGS AND NOW REFUSED. `DATABASE_PASSWORD` (`djb`,
# `config.settings.base`) used to stand in the paragraph above as the honest
# admission that the boundary's largest neighbour was unfenced. The fence now
# exists: `check_database_password` below, called from
# `refuse_development_defaults`, and the population is exactly the deployment
# the hole was about — one that configures the DATABASE_* **parts**. Both
# entrances close together, because they are one entrance: the base default IS
# the published value, so *forgetting* the variable and *setting* it to `djb`
# arrive at the same string and are refused by the same comparison.
#
# What it deliberately does not cover: a deployment that sets `DATABASE_URL`,
# where the parts are never consulted and the password lives inside a URL this
# module is not handed. `config.settings.base` decides that population — it
# passes `None` for the password when a URL won — rather than this module
# guessing at it, and the belt for a published value inside a URL is the
# deployment's own start-up assertion, where the whole URL is in hand.
#
# WHERE THE REAL FENCE BELONGS: deployment posture, not Python. `compose.yaml`
# is the development stack, and a production Zitadel is not started by it. The
# masterkey and the three passwords are secret material a deployment generates
# and injects, so the check that they are not the published defaults belongs
# where that injection is defined — the deployment manifest, its secret store,
# or a start-up assertion in the deployment itself. That is the only place with
# the values in hand.
#
# TRIGGER: the first production deploy — where a code-level
# promise is honest until there is a deployment to put the belt on, and the
# belt is written then rather than guessed now. Until that day the four
# compose-only values stay published and unrefused. That is the true state of
# this tree, recorded here so nobody has to re-derive it.

# The development values published in `.env.example`. Worth exactly nothing, and
# meant to be — but only if production says so out loud.
DEV_SECRET_KEY = (
    "insecure-local-development-key-change-me-000000000000000000"  # pragma: allowlist secret
)
DEV_CONNECTIONS_ENCRYPTION_KEY = (
    "X8S2D9HPCtxlLLMHRNYByWXXQf2JRMmaH16DIxD7vdo="  # pragma: allowlist secret
)

# The compose Postgres' password, published in `.env.example` and in
# `compose.yaml`, and `config.settings.base`'s default for DATABASE_PASSWORD —
# which is the point: the default STAYS (deleting it breaks every laptop for a
# production problem), and production refuses it instead.
DEV_DATABASE_PASSWORD = "djb"  # pragma: allowlist secret

# The one `config.settings.test` uses, so a test tree cannot be deployed either.
TEST_SECRET_KEY = (
    "insecure-test-key-000000000000000000000000000000000000000000"  # pragma: allowlist secret
)

GENERATE_SECRET_KEY = 'python -c "import secrets; print(secrets.token_hex(32))"'
GENERATE_FERNET_KEY = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)
GENERATE_DATABASE_PASSWORD = 'python -c "import secrets; print(secrets.token_urlsafe(32))"'

PUBLISHED_SECRET_KEYS = frozenset({DEV_SECRET_KEY, TEST_SECRET_KEY})
PUBLISHED_ENCRYPTION_KEYS = frozenset({DEV_CONNECTIONS_ENCRYPTION_KEY})
PUBLISHED_DATABASE_PASSWORDS = frozenset({DEV_DATABASE_PASSWORD})


def check_secret_key(value: str) -> None:
    """Refuse an absent SECRET_KEY, and refuse a published one just as hard."""
    if not value:
        raise RuntimeError(
            f"SECRET_KEY must be set in production. Generate one: {GENERATE_SECRET_KEY}"
        )
    if value in PUBLISHED_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY is the development value published in .env.example, so it is "
            f"public and worth nothing. Generate one: {GENERATE_SECRET_KEY}"
        )


def check_connections_encryption_key(value: str) -> None:
    """Same rule for the Fernet key that protects every tenant's credentials."""
    if not value:
        raise RuntimeError(
            "CONNECTIONS_ENCRYPTION_KEY must be set in production. "
            f"Generate one: {GENERATE_FERNET_KEY}"
        )
    if value in PUBLISHED_ENCRYPTION_KEYS:
        raise RuntimeError(
            "CONNECTIONS_ENCRYPTION_KEY is the development value published in "
            ".env.example. Every tenant credential it encrypts would be readable by "
            f"anyone with the repository. Generate one: {GENERATE_FERNET_KEY}"
        )


def check_database_password(value: str) -> None:
    """Refuse the published compose password, and refuse an empty one.

    Only ever called for a **parts-configured** deployment — see
    `refuse_development_defaults` for who decides that. The absent case and the
    published case are the same string here, deliberately: `config.settings.
    base` defaults this variable to `DEV_DATABASE_PASSWORD`, so a deployment
    that sets DATABASE_HOST, DATABASE_USER and DATABASE_NAME and forgets this
    one is holding `"djb"` exactly as if it had typed it. An empty value is the
    third spelling of the same mistake and is refused on its own terms, because
    a blank password is not a password either.
    """
    if not value:
        raise RuntimeError(
            "DATABASE_PASSWORD must be set in production when the DATABASE_* parts "
            "configure the connection (set DATABASE_URL instead if the password "
            f"belongs inside a URL). Generate one: {GENERATE_DATABASE_PASSWORD}"
        )
    if value in PUBLISHED_DATABASE_PASSWORDS:
        raise RuntimeError(
            "DATABASE_PASSWORD is the development value published in .env.example "
            "and compose.yaml, so it is public. A deployment that configures the "
            "DATABASE_* parts and leaves this one unset gets it by default, which "
            "is the whole reason this is refused rather than warned about. "
            f"Generate one: {GENERATE_DATABASE_PASSWORD}"
        )


def refuse_development_defaults(
    *,
    secret_key: str,
    connections_encryption_key: str,
    database_password: str | None = None,
) -> None:
    """Every check, in the order production runs them.

    `database_password` is `None` when the caller is **not in that check's
    population** — a deployment configured by `DATABASE_URL`, where the parts
    were never consulted and there is no parts password to refuse. That is a
    statement about the deployment, not a way to skip the check: the one caller
    that matters, `config.settings.production`, passes what
    `config.settings.base` resolved, and base passes `None` only when a URL
    actually won. The default exists so that a caller checking a *key pair*
    does not have to invent a database password to do it.
    """
    check_secret_key(secret_key)
    check_connections_encryption_key(connections_encryption_key)
    if database_password is not None:
        check_database_password(database_password)
