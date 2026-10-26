"""Production settings.

`python manage.py check --deploy --settings=config.settings.production` must be
clean — zero warnings — with `.env.example` values plus a real SECRET_KEY,
DEBUG=0 and a real ALLOWED_HOSTS. Everything security-related is inherited from
`base`, which is secure by default; this module only refuses to start on the
things that must not be defaults in production.

The refusals are by value, not only by absence: `.env.example` ships working
secrets, and the whole point of that file is that people copy it. See
`config.settings.guards`.
"""

from typing import Any
from urllib.parse import urlsplit

from .base import *  # noqa: F403
from .base import (
    ALLOWED_HOSTS,
    CONNECTIONS_ENCRYPTION_KEY,
    DEBUG,
    MACHINERY_DEPLOYMENT,
    MIDDLEWARE,
    PUBLIC_BASE_URL,
    SECRET_KEY,
    SIGN_IN_DOOR,
    SOCIALACCOUNT_PROVIDERS,
    STORAGES,
    SURFACE_HOSTS,
    _parts_database_password,
    _surface_names,
    _surface_origins,
    env,
    machinery_lifetime,
)
from .guards import refuse_development_defaults

if DEBUG:
    raise RuntimeError("DEBUG must be off in production; set DEBUG=0.")

if not ALLOWED_HOSTS:
    raise RuntimeError("ALLOWED_HOSTS must be set in production.")

refuse_development_defaults(
    secret_key=SECRET_KEY,
    connections_encryption_key=CONNECTIONS_ENCRYPTION_KEY,
    # Private on purpose: this is not a setting, it is base's answer to "did the
    # DATABASE_* parts configure this connection, and with what password" — the
    # population of the check, decided where the winner is decided. A URL-
    # configured deployment passes `None` and is refused by the deployment's own
    # start-up assertion instead.
    database_password=_parts_database_password,
)

EMAIL_BACKEND = env.str("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")

# Static files: WhiteNoise's compressed manifest storage, so the web container
# serves the admin and `/api/v1/docs` itself — hashed filenames with a far-future
# cache header, gzip and brotli pre-compressed at build time, and no separate
# static server, CDN origin or nginx sidecar for two pages. `collectstatic` runs
# in the image build (`Dockerfile`), which is what makes the manifest present
# before the first request rather than generated during it.
#
# `default` is inherited from `base`: FileSystemStorage, or S3 the moment
# AWS_STORAGE_BUCKET_NAME is set. A production deployment with uploads sets the
# bucket; a production deployment without uploads does not need one.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- Content Security Policy -------------------------------------------------
# Production only, and deliberately so: `django-csp` on a laptop mostly breaks
# the debug toolbar and the OpenAPI docs page, and a policy people turn off to
# get work done is a policy that is off in production too.
#
# The pages this project serves are the admin and `/api/v1/docs`; a product with a
# front end widens this in its own settings, and records why. `'unsafe-inline'`
# is on styles because Django's admin ships inline `style=` attributes and
# removing them is Django's job, not a deployment's; scripts have no such
# exemption, which is the half that matters.

MIDDLEWARE = [*MIDDLEWARE, "csp.middleware.CSPMiddleware"]

# `form-action` is the one directive a sign-in door collides with, and the
# collision is not the one the name suggests. **Browsers apply `form-action` to
# the whole redirect chain a form submission travels, not just to the URL the
# form names.** The provider-login form POSTs to our own host — same origin,
# allowed — and our server answers `302` to the identity provider's authorize
# endpoint. With `form-action 'self'` the browser refuses *that hop*:
#
#   Refused to send form data to '…/o/oauth2/v2/auth?…' because it violates the
#   following Content Security Policy directive: "form-action 'self'".
#
# Measured in the owner's browser console on staging (four occurrences, both
# doors) and only there: the server log shows the `302` leaving and cannot see
# the browser decline to follow it, which is why this read as an identity
# misconfiguration for a while.
#
# So the authorize origins join the directive — **derived, never a
# per-environment literal**, and never wider than the doors this deployment
# actually opened. `_authorize_origins` reads the provider blocks `base`
# already built: an `APPS` list is empty exactly when the provider is
# unconfigured (no client id, no issuer), which is also exactly when no button
# offers that door. A deployment that moves its identity host moves
# `ZITADEL_ISSUER` and this moves with it.
#
# **Google is not in it.** The workforce's Google is an identity provider inside
# Zitadel, so our form's redirect chain ends at Zitadel; the hop onwards to
# Google starts on Zitadel's own page, under Zitadel's policy, not ours.


def _origin(url: str) -> str:
    """Scheme and host of `url`, or "" if it is not an absolute URL.

    A `form-action` source expression matches on scheme, host and port; a path
    in the value would be noise at best. So the origin is what goes in, and a
    configured value that is not an absolute URL contributes nothing rather
    than contributing something malformed.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _authorize_origins(providers: dict[str, Any]) -> list[str]:
    """Where a sign-in that starts on this host is allowed to end up.

    Order-preserving and de-duplicated, so the rendered header is stable
    between restarts and a reader can diff two deployments' policies.
    """
    origins: list[str] = []

    # Zitadel, and any other statically configured OpenID Connect app: the
    # origin of the `server_url` allauth builds every endpoint from — the same
    # `ZITADEL_ISSUER` the discovery document, the audiences and the callback
    # are all checked against (`config.settings.base`).
    oidc: dict[str, Any] = providers.get("openid_connect", {})
    for app in oidc.get("APPS", []):
        origin = _origin(str(app.get("settings", {}).get("server_url", "")))
        if origin:
            origins.append(origin)

    return list(dict.fromkeys(origins))


def _declared_redirect_origins() -> list[str]:
    """Where a sign-in that COMPLETES on our own page is allowed to end up.

    **The other half of the same defect, and it only exists under `ours`**
    (design C-10's CSP half; the consumer's LOGIN-CSP-1). `_authorize_origins`
    above admits the hop OUT — our page 302s the browser to the identity
    platform's authorize endpoint. This admits the hop BACK: with the login
    page on our host, the person's password POSTs here, our server finalizes
    the OIDC auth request, and the answer is a 302 towards the client's
    registered redirect URI. That redirect is part of the same submission's
    chain, so `form-action` governs it — and the failure is invisible from
    this side: the server log shows the 302 leaving and every headless drive
    passes, while the browser silently declines to follow it.

    **Empty under `hosted`, and that is the derivation, not caution.** Under
    the hosted door no form of ours is ever submitted into that chain — the
    password is typed on the identity platform's own page — so the origins are
    not needed, and a directive listing them anyway would be wider than the
    doors this deployment opened. That is the same rule the authorize origins
    above are derived by.

    **The URIs are the SEED's, imported rather than restated.** They are what
    `zitadel_seed` registers with Zitadel; a copy here would be a hand list
    that agrees with the registration on the day it is written and silently
    stops agreeing the first time either moves — and the symptom would be a
    browser refusing a redirect nobody can see refused. The module is
    importable from a settings module because it touches no model and no app
    registry: it reads `django.conf.settings` lazily and calls Zitadel only
    from inside `handle`. `config/urls.py` and `config/api.py` already import
    from `apps.`; this is that direction, one file earlier.
    """
    if SIGN_IN_DOOR != "ours":
        return []

    # Imported here rather than at module scope so the arrow is visible at the
    # one place that needs it, and so nothing else in this file can start
    # depending on a command module.
    from apps.accounts.management.commands import zitadel_seed

    base = str(PUBLIC_BASE_URL or "")
    declared = [
        f"{base}{zitadel_seed.BROWSER_CALLBACK_PATH}",
        f"{base}{zitadel_seed.BROWSER_LOGOUT_PATH}",
        *zitadel_seed.MCP_CALLBACK_URIS,
    ]
    # And every surface's origin: the seed registers a browser callback on each
    # surface's host (`core.surfaces.surface_base_urls`), so a sign-in completed
    # on the customer host comes back to the customer host, and a `form-action`
    # that knew only `PUBLIC_BASE_URL` refused that hop. Settings may not import
    # `apps`, so the origins are this module's own derivation of the same map —
    # `base.py`'s `_surface_origins`, the settings-side twin of `absolute_url`.
    surfaces = _surface_origins(_surface_names(SURFACE_HOSTS), base)
    return list(
        dict.fromkeys([*(origin for origin in map(_origin, declared) if origin), *surfaces])
    )


CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'none'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "form-action": [
            "'self'",
            *_authorize_origins(SOCIALACCOUNT_PROVIDERS),
            *_declared_redirect_origins(),
        ],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
    }
}

# --- Machinery lifetime (ADR platform-lifecycle-1) ---------------------------
# `deployment`, restated here rather than inherited, because this is the file
# somebody reads to find out what production does. It is also the behaviour this
# template has always had: durable Temporal Schedules, created at worker
# startup, outliving the process — which is what buys catch-up across a deploy
# gap and a missed run that is a fact rather than a silence.
#
# It is the right class **because a deployment's task queue is a stable
# identity**, not because it is production. The day a deployment gives each
# instance its own queue — a per-pod suffix, a blue/green pair — its identities
# become ephemeral and this line is the one to revisit; that is the trigger
# recorded with the ADR, and it is a question about identities rather than about
# environments.
TEMPORAL_MACHINERY_LIFETIME = machinery_lifetime(MACHINERY_DEPLOYMENT)
