"""Root URL configuration.

`/api/v1/` is the product's HTTP contract, `/admin/` is the staff door, and
`/accounts/` is django-allauth's local email account flow. The machine door
(`/mcp`) and the socket door are mounted in `config/asgi.py`, not here: neither
is URL-routed by Django.

`/healthz` and `/readyz` are mounted at the **root**, deliberately outside
`/api/v1/`. They are not part of the product's contract — they are what an
orchestrator asks before it sends anyone else's traffic here — and being off the
API means they inherit none of its machinery: no `auth=`, no throttle, and no
`Idempotency-Key` handling (that middleware only inspects writes under `/api/`).
Both are unauthenticated on purpose; `apps/core/health.py` records why, and what
each one is allowed to say.

**The version is in the path from day one.** Not because a `v2` is planned, but
because retrofitting one is the expensive move: every client hard-codes `/api/`
in the meantime, and the day a breaking change is needed the only options are
to break them or to negotiate versions in a header nobody logs. `v1` costs five
characters now. A breaking change is a `v2` router mounted beside this one, with
`v1` still answering, until the clients have moved.
"""

from functools import partial

from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from django.views.decorators.csrf import csrf_exempt

from apps.accounts import oauth
from apps.core import health, views
from apps.core.api import docs
from config.api import api, api_not_found, api_server_error

API_PREFIX = "api/v1/"

urlpatterns: list[URLPattern | URLResolver] = [
    # No trailing slash: every probe that will ever call these — kubelet, an ALB
    # target group, a compose healthcheck — is configured with a literal path
    # and does not follow redirects.
    path("healthz", health.healthz, name="healthz"),
    path("readyz", health.readyz, name="readyz"),
    # RFC 9728, at the root because a well-known URI is fixed by its RFC. This
    # is the first thing a third-party MCP client fetches: a 401 from `/mcp`
    # points at it, and it names the authorization server to go and get a token
    # from (ADR ident-3). Unauthenticated, necessarily — a client discovering
    # this deployment has no credential yet.
    path(
        ".well-known/oauth-protected-resource",
        oauth.protected_resource_metadata_view,
        name="oauth-protected-resource",
    ),
    # At the ROOT, and by that name, because that is the whole convention: an
    # agent that has been given a base URL looks for `/llms.txt` and nothing
    # else. It is the same contract as `/api/v1/docs` and `openapi.json` in the
    # rendering the third kind of reader can afford — flat text, no JavaScript
    # to run, no `$ref` graph to resolve — and it is DERIVED on request from
    # the live document (`apps/core/api/docs.py`), never a file in the tree,
    # so it cannot drift from the routes. The API arrives bound rather than
    # imported: an app never imports `config`, and `config/api.py` already
    # imports that module, so `partial` is what keeps the arrow pointing one
    # way. Ninja mounts its own document view exactly like this.
    path("llms.txt", partial(docs.llms_txt, api=api), name="llms-txt"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path(API_PREFIX, api.urls),
    # Reached only when the resolver has already failed INSIDE the API
    # above, so it can shadow no route: a path under the version segment that
    # nothing claims is answered in the API's own vocabulary — `{detail, code}`
    # as JSON — instead of falling through to Django's HTML 404 page. A JSON
    # client's first typo should not come back as markup with no `code` in it.
    # The body is composed by `config/api.py`, where every other refusal's is.
    #
    # The only `csrf_exempt` in this tree: this view answers 404 to
    # everything and reads, writes and authenticates nothing, so there is no
    # state a forged cross-site request could reach through it — while without
    # the exemption `CsrfViewMiddleware` answers a cookieless POST first, with
    # Django's HTML CSRF page, and the JSON contract above is a fiction for
    # exactly the callers it was written for. Applied at the mount, not on the
    # function, because `config/api.py` owns the refusal and this file owns
    # where it hangs. The API ahead of it needs no such line: ninja marks its
    # own view exempt and `SessionAuth` does the human door's CSRF check in
    # full — which is why the exemption here loosens nothing for a real route.
    path(f"{API_PREFIX}<path:unmatched>", csrf_exempt(api_not_found), name="api-not-found"),
    # LAST, and at the root. The door index (`apps/core/views.py`): what a
    # person, an operator or a third party gets when they open the deployment
    # with no path, instead of Django's bare "Not Found". It is mounted after
    # everything else so that a product overriding it — its own landing page at
    # `""` in its own urlpatterns, ahead of this list — wins by ordinary URL
    # resolution and does not have to delete anything.
    path("", views.index, name="index"),
]

# Django reads `handler500` off the ROOT urlconf, which is what makes
# this a config-level catch that needs no `MIDDLEWARE` entry — and it is reached
# for a fault anywhere in the request: `BaseHandler.load_middleware` wraps every
# middleware in `convert_exception_to_response`, so the session read that
# `TenantMiddleware` triggers — the first statement of every authenticated
# browser request — arrives here, and that is not somewhere an
# `@api.exception_handler` will ever run.
# The function is `config/api.py`'s, mounted here, for exactly the reason
# `api_not_found` is: that module owns the status and the refusal, this file
# owns where it hangs. Everything it will not claim goes to Django's own
# `server_error` unchanged — a 500 is still a 500.
handler500 = api_server_error
