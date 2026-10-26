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
from apps.accounts import views as accounts_views
from apps.accounts.admin import admin_login, admin_password_change
from apps.core import health, views
from apps.core.api import docs
from config.api import api, api_not_found, api_server_error, surface_view

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
    # ONE line ahead of the admin, and it shadows ONE of its URLs (ADR
    # ident-4). Django's `/admin/login/` is a password form POSTing against
    # `User.password` — the second credential store the ADR closed — so it is
    # taken over here rather than left mounted and hoped about. `admin.site.urls`
    # below still contributes every `admin:` name including `admin:login`, which
    # still reverses to this path; what changed is which callable answers it.
    # A shadow rather than a custom `AdminSite`: a second admin object is one
    # every `ServiceModelAdmin` in the tree would have to be re-registered on.
    path("admin/login/", admin_login, name="admin-login"),
    # The same shadow, one rung later, for the two URLs BEHIND that door that
    # still wrote `User.password`: `AdminSite.password_change` answered
    # 200 with three password fields and a POST changed the hash on the row,
    # and `password_change_done` answered "Password change successful" about a
    # store this deployment does not keep. Both names still reverse — the
    # admin below contributes `admin:password_change` and
    # `admin:password_change_done` exactly as before — and what changed is
    # again only which callable answers. The third password surface,
    # `/admin/accounts/user/<id>/password/`, is `UserAdmin`'s own method and is
    # refused in `apps/accounts/admin.py` where it is defined; it is not
    # mountable here and does not want to be.
    path("admin/password_change/", admin_password_change, name="admin-password-change"),
    path(
        "admin/password_change/done/",
        admin_password_change,
        name="admin-password-change-done",
    ),
    path("admin/", admin.site.urls),
    # ONE line ahead of allauth, and it shadows ONE of its URLs — the same
    # pattern, and the same reasoning, as `/admin/login/` above (design C-13,
    # the lead's decision 16). `SIGN_IN_DOOR` decides which door answers:
    # under `hosted`, the default, this view calls allauth's own `LoginView`
    # and the page is byte-identical to the one this deployment already
    # serves; under `ours` it draws design P-10's frames over the sign-in seam.
    # allauth below still contributes the `account_login` NAME, which still
    # reverses to this path; what changed is which callable answers it. A
    # `LoginView` subclass was rejected for the reason `apps/accounts/views.py`
    # records: a multi-step ceremony is not a form.
    path("accounts/login/", accounts_views.sign_in, name="sign-in"),
    path("accounts/", include("allauth.urls")),
    # The face's boot question — which surface this address is — under the
    # version segment because the face reads it beside the API, and AHEAD of the
    # API's mount and its catch-all so neither shadows it. A plain view, like the
    # RFC 9728 document above, and unauthenticated for the same reason: it is
    # asked before anybody signs in. It says what the address already is (the
    # surface's key, its screens and its tenant rule) and never names a family,
    # a door or another surface; rule 3's plain-view census records it with that
    # reason. Every surface answers it, so no surface's families gate it. Exempt
    # from CSRF at the mount for the catch-all's reason below: it reads and
    # writes nothing, and a wrong method answers the API's JSON 405.
    path(f"{API_PREFIX}surface/", csrf_exempt(surface_view), name="surface"),
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
    # SHADOWED, NOT CONFIGURED. Where a completed sign-in lands
    # (`LOGIN_REDIRECT_URL`, derived in `config/settings/base.py` from
    # `PRODUCT_BASE_URL`). It is mounted here, near the end, for the same reason
    # the index below it is: a product mounting its own `path("welcome/", ...)`
    # ahead of this list wins by ordinary URL resolution and deletes nothing —
    # and a product with a front end never reaches it at all, because
    # `PRODUCT_BASE_URL` then points sign-in somewhere else entirely. Two ways
    # out, neither of them a fork of this file.
    path("welcome/", views.welcome, name="welcome"),
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
