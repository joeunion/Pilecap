"""Local development settings — the default for `manage.py`.

Plain HTTP on a laptop and a throwaway SECRET_KEY when none is set. The API is
drivable with a bearer token: mint one with `issue_token` and send
`Authorization: Bearer <token>`.
"""

from .base import *  # noqa: F403
from .base import MACHINERY_PROCESS, SECRET_KEY, env, machinery_lifetime
from .guards import DEV_SECRET_KEY

DEBUG = env.bool("DEBUG", default=True)

# The published development value, from the one module that names it — so
# `production` can refuse this exact string rather than merely an empty one.
if not SECRET_KEY:
    SECRET_KEY = DEV_SECRET_KEY

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

# A laptop serves plain HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

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
