"""Local development settings — the default for `manage.py`.

Plain HTTP on a laptop and a throwaway SECRET_KEY when none is set. The API is
drivable with a bearer token: mint one with `issue_token` and send
`Authorization: Bearer <token>`.
"""

from .base import *  # noqa: F403
from .base import (
    MACHINERY_PROCESS,
    SECRET_KEY,
    SURFACE_HOSTS,
    admitted_hosts,
    env,
    machinery_lifetime,
)
from .guards import DEV_SECRET_KEY

DEBUG = env.bool("DEBUG", default=True)

# The published development value, from the one module that names it — so
# `production` can refuse this exact string rather than merely an empty one.
if not SECRET_KEY:
    SECRET_KEY = DEV_SECRET_KEY

# Re-read with a laptop default, so the surface map is folded in again here —
# otherwise a bound `customer.localhost` answers 400 on the one stack
# (`scripts/serve.sh`) a laptop and a verifier box actually run.
ALLOWED_HOSTS = admitted_hosts(
    env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"]), SURFACE_HOSTS
)

# THE ONE PROXY IN FRONT OF A LAPTOP'S OR A BOX'S DJANGO IS THE FACE. The
# face's `next.config.ts` rewrite forwards `/api/v1/*` to Django with
# `Host: 127.0.0.1:8000` and the address the browser used in
# `X-Forwarded-Host` — a rewrite cannot keep `Host`. The surface is read from
# the host, so without this every address answered through the face would be
# `127.0.0.1` and no surface. That rewrite is the only reason this is on, and
# it is on HERE only: `base` and `production` leave it off, because in a
# deployment Caddy's `reverse_proxy web:8000` keeps the client's own `Host`
# (`deploy/Caddyfile`) and a header nobody we run set must never choose the
# audience. `request.get_host()` honours it on the HTTP door by Django's own
# law; the socket and MCP doors read it through `core.surfaces.request_host`.
USE_X_FORWARDED_HOST = True

# A laptop serves plain HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
# A laptop's webhook subscribers are on localhost (SF-WEBHOOK-1 reads it; N2238).
WEBHOOK_PRIVATE_TARGETS_ALLOWED = True

EMAIL_BACKEND = env.str("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# WhiteNoise serves static straight from the finders on a laptop, so the admin
# and `/api/v1/docs` have their CSS without anyone having run `collectstatic`.
# `serve.sh` runs uvicorn rather than `runserver`, so Django's own development
# static handler is not in the picture — without these two, the admin renders
# unstyled and the first reaction is to suspect the admin.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

# --- Machinery lifetime (ADR platform-lifecycle-1) ---------------------------
# A laptop's task queue is derived from the checkout, so a laptop's identities
# are ephemeral by construction: a durable Temporal Schedule created against one
# outlives the worktree that made it, keeps firing at a queue nobody polls, and
# is only ever found by a census. `process` is the honest class for it — no
# Schedule object is created, the live worker starts the same sweeps at startup
# and on their declared cadence, and it deletes the durable ones an earlier
# build left behind.
#
# Declared, not derived. `TEMPORAL_MACHINERY_LIFETIME=deployment` in the
# environment overrides this for a laptop that genuinely wants the durable
# behaviour — for reproducing a production question, say — and nothing here
# looks at the branch or the directory to decide.
TEMPORAL_MACHINERY_LIFETIME = machinery_lifetime(MACHINERY_PROCESS)
