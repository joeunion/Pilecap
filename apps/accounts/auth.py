"""Bearer-token authentication, shared by every machine-facing door.

The REST API mounts this beside session authentication, and the MCP mount uses
the same `authenticate_token` service. One token, one user, one tenant, both
doors — a door that authenticated differently would be a door that could see
something the other cannot.

Which of the two authenticated a given request is recorded on the request, and
`authenticated_by_token()` is how a route asks. Exactly one route needs to
know: minting a token is a thing a person does while signed in, never a thing a
token does for itself, because a token that can mint tokens cannot be revoked.

**That one route now says so at the door rather than in its body.** The
token ceiling is checked between authentication and the view, so a route body
was too late to answer first: a narrow token was told it needed `tokens:write`
and sent to the one operation no token can ever call. `MINT_AUTH` — this
module's one narrowing of `API_AUTH` — puts `SessionOnly` where `ApiTokenAuth`
sits, so the honest refusal is the first one. `authenticated_by_token()` stays
in the route as the belt: it is unreachable while `MINT_AUTH` is that route's
`auth=`, and it is what keeps the rule true if anybody ever widens it back.

**Order matters, and it is a correctness property rather than a preference.**
ninja tries the authenticators in the order `API_AUTH` lists them and stops at
the first that returns something — but `ninja.security.APIKeyCookie._get_key`
does not *decline* when its CSRF check fails, it **raises** `HttpError(403)`,
and `Operation._run_authentication` turns any exception into that response.
Session authentication placed first therefore answered every bearer `POST` with
403 "CSRF check Failed" before the token authenticator was reached at all (queue
V1). Two things keep that shut, and both are needed:

1. `ApiTokenAuth` is **first**, so a request carrying a token never reaches the
   cookie authenticator;
2. `SessionCookieAuth` **declines** a request that carries an `Authorization`
   header instead of CSRF-checking it, so a bad or expired token gets the 401 it
   deserves rather than a 403 about a cookie it never sent — and that 401 now
   says *which* 401 it is (`BEARER_NOT_VALID`), because a caller holding a
   withdrawn token was being told nobody could be identified;
3. `SessionCookieAuth` **declines a request with no session cookie at all**, for
   the same reason said about a different caller: an anonymous `POST` carrying
   no credential of any kind was answered "CSRF check Failed" (403), which
   tells a client to go and find a CSRF token when what it actually needs is to
   authenticate. There is nothing to CSRF-protect when there is no session to
   ride on. It is now the 401 it always was.

Nothing about CSRF is loosened for the browser: a session-authenticated write
without `X-CSRFToken` is still refused, which is the whole point of the check
and is asserted over the wire in
`apps/example/tests/test_doors_over_the_wire.py` and, for all four cases at
once, in `apps/accounts/tests/test_auth_over_the_wire.py`.

**And both of this door's refusals now travel in the product's one envelope.**
The two things this module can say no with — "we could not tell
who you are" and "you are signed in and this write did not prove where it came
from" — used to leave as ninja's own bare `{"detail": ...}` with no `code`,
which made them the only two refusals in the product a client could not branch
on. They are registered refusals now (`unauthenticated`, `page_token_missing`,
declared below beside the door that makes them) and reach the wire through
`core.exceptions.wire_refusal` like every other one. The status codes are still
`config/api.py`'s and only `config/api.py`'s — house rule 14 is untouched.
"""

from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from apps.accounts.models import User
from apps.accounts.services import authenticate_token
from apps.core import context
from apps.core.actor import TOKEN_ATTR, TOKEN_AUTH_ATTR
from apps.core.exceptions import DomainError, Forbidden, Remedy, register_refusal
from apps.core.middleware import (
    AUTHORIZATION_HEADER,
    ORG_HEADER,
    TENANT_HEADER,
    resolve_org,
)
from apps.core.requests import TenantRequest

__all__ = [
    "API_AUTH",
    "AUTHORIZATION_HEADER",
    "BEARER_NOT_VALID",
    "CSRF_TOKEN_HEADER",
    "MINT_AUTH",
    "TOKEN_ATTR",
    "TOKEN_AUTH_ATTR",
    "ApiTokenAuth",
    "PageTokenMissing",
    "SessionCookieAuth",
    "SessionOnly",
    "SessionRequired",
    "Unauthenticated",
    "authenticated_by_token",
]

#: The header a browser proves a write came from our own pages with. Declared
#: here rather than spelled inside the sentence that names it, for rule 40's
#: reason: a refusal that points at a header is only useful if it points at the
#: header the server actually reads, and one spelling is how that stays true.
CSRF_TOKEN_HEADER = "X-CSRFToken"

# The header a machine identifies itself with is declared ONCE, in
# `core.middleware`, and imported downward — `accounts` sits on `core`. It was
# declared here as well until N100c, and a second spelling of a header is the
# fail-open rule 40 exists to catch: the read finds nothing and the request is
# answered as though the caller had presented nothing. Re-exported above,
# because this is the module the door reads it in.


# --- The two refusals the authentication door itself makes --------------------
#
# Both used to reach a client as one of ninja's own bare bodies —
# `{"detail": "Unauthorized"}` and `{"detail": "CSRF check Failed"}` — with **no
# `code`**, which this closes. Every other refusal in the
# product carries a stable token a client branches on and a structured list of
# what to do next; these two, the first two refusals most callers ever meet, did
# not. A client that has to branch on the *wording* of "Unauthorized" is a
# client that breaks when somebody improves the wording.
#
# They are declared HERE and not in `core.exceptions` for the reason the whole
# grammar is declared beside its raise site: this module is where the door
# decides that nobody is signed in, and the fact and the remedies are about this
# door. `config/api.py` adds nothing but the number.


register_refusal(
    code="unauthenticated",
    boundary="door",
    remedy=(
        "No credential resolved. Either none was sent, or the bearer token was wrong, "
        "expired or revoked — `authenticate_token` returns None for all of those on "
        "purpose, so the door cannot leak which. Check the token is live in the admin "
        "or through `manage.py`, and check the session cookie is being sent at all "
        "before assuming the token is the problem."
    ),
    fact=(
        "We could not tell who is making this request. Either nothing was sent to "
        "identify you, or what was sent is no longer good — an expired or withdrawn "
        "token and no token at all are answered the same way on purpose, because a "
        "refusal that told them apart would confirm which tokens exist. Nothing was "
        "read and nothing was written."
    ),
    remedies=(
        Remedy("Sign in, and let the browser send the session it gives you", "self:session"),
        Remedy(
            "Or send a token you hold as `Authorization: Bearer <token>`",
            f"header:{AUTHORIZATION_HEADER}",
        ),
        Remedy("Mint a fresh token — the operation is under API tokens", "docs:openapi"),
    ),
    # 401, declared here rather than appended to a table under `config/` (ADR
    # core-23). `config/api.py` used to restate this and `page_token_missing`'s
    # 403 by hand for a reason that has gone: its table was built by a dict
    # comprehension over CLASSES, so two classes sharing 403 kept whichever came
    # last. A table keyed on the CODE, derived from the declarations, cannot
    # lose one to the other.
    status=401,
)


class Unauthenticated(DomainError):
    """Nobody was identified — nothing was sent, or what was sent is no good.

    Deliberately one answer for both. A refusal that distinguished "you sent
    nothing" from "your token was withdrawn" would tell an unauthenticated
    caller which strings are real tokens, which is the fact the hashing exists
    to hide.

    **One code, two sentences, and the `detail` is the half that varies.** The
    `default_detail` below is the answer to a caller who identified themselves
    with *nothing*; `BEARER_NOT_VALID` is the answer to a caller who presented a
    bearer token that resolved to nobody. Both are this code and this fact —
    see `BEARER_NOT_VALID` for why saying which one happened leaks nothing.
    """

    code = "unauthenticated"
    default_detail = (
        "We could not tell who is making this request. Sign in, or send a token you "
        "hold as `Authorization: Bearer <token>`."
    )


#: What a caller who PRESENTED a bearer that resolved to nobody is told —
#: declared once and said by **both** doors that read the header: this module
#: for REST, `config/mcp.py` for `/mcp`, which imports it rather than spelling
#: it a second time.
#:
#: The two doors used to disagree, and REST was the one that was wrong: it
#: answered the registry's general sentence — "we could not tell who is making
#: this request" — over a credential whose owner the door had just looked up and
#: refused. That fact is true of a request that sent nothing and false of a
#: withdrawn token, and a refusal whose fact is false is what the grammar
#: exists against.
#:
#: **It tells the holder nothing they do not already have.** They sent the
#: string, so they have it; and revoked, expired, never-issued and
#: belonging-to-a-deactivated-person are all still answered identically —
#: `authenticate_token` returns `None` for every one of them — which is the fact
#: the hashing protects. What changes is only whether the door admits that
#: something was presented at all.
#:
#: A second refusal CODE was deliberately not minted for it: `unauthenticated`
#: is what this is, one code carries one fact, and the `detail` is the half a
#: raise site is allowed to make specific.
BEARER_NOT_VALID = "That bearer token is not valid."


register_refusal(
    code="page_token_missing",
    boundary="door",
    remedy=(
        f"A signed-in browser write reached the door without {CSRF_TOKEN_HEADER}. The "
        "check is Django's own and nothing here loosens it: read the `csrftoken` cookie "
        "the server set and send it back in that header. A machine caller should not be "
        "on this path at all — it should send a bearer token, which is not a cookie and "
        "so has no cross-site request to forge."
    ),
    fact=(
        "You are signed in, and this write did not carry the short-lived token that "
        "proves it came from one of our own pages. Browsers attach a signed-in session "
        "to any page that asks, so a write has to prove where it came from as well as "
        "who it is from. Nothing was written."
    ),
    remedies=(
        Remedy(
            "Send the value of the `csrftoken` cookie back in this header",
            f"header:{CSRF_TOKEN_HEADER}",
        ),
        Remedy(
            "Or make this call with a token instead of a browser session",
            f"header:{AUTHORIZATION_HEADER}",
        ),
    ),
    # 403 and NOT `Forbidden`'s — the tie-break `config/api.py`'s
    # `REFUSAL_FOR_STATUS` still records from the other direction: a bare
    # `HttpError(403, …)` in a route means `forbidden`, never this. Declaring the
    # number here is what makes the two independent of which class a dict
    # comprehension happened to visit last.
    status=403,
)


class PageTokenMissing(DomainError):
    """A signed-in browser write with no proof of where it came from.

    Named for what is *missing* rather than for the framework check that noticed
    it, because the name reaches a reader through `introspect` and through the
    OpenAPI document, and "the CSRF middleware said no" is a sentence about our
    plumbing rather than about the caller's request.
    """

    code = "page_token_missing"
    default_detail = (
        "This write did not carry the token that proves it came from one of our own "
        f"pages. Send the `csrftoken` cookie's value in the `{CSRF_TOKEN_HEADER}` header, "
        "or make the call with a bearer token instead of a browser session."
    )


# --- The operation a bearer token may not reach, refused as such --------------
#
# WHY IT IS AN AUTHENTICATOR AND NOT A LINE IN THE VIEW. The mint has always
# refused a bearer token — but it refused it in the route body, and the route
# body is the last thing that runs. The token ceiling (ADR ident-7) is checked
# between authentication and the view, so a NARROW token never got that far: it
# was answered `insufficient_scope`, told it needed `tokens:write`, and sent to
# mint a token carrying it — which is the very operation that then refuses every
# token whatever it carries. Two refusals, each true, pointing at each other
# (FT-1′ F2/F3). An agent runtime holding one narrow token has no wire path to a
# wider one BY DESIGN, and the chain never said so.
#
# So the answer moves to where it can be given first. Authentication runs inside
# ninja's `_run_checks`, and the ceiling check wraps `_run_checks` — so an
# authenticator that refuses is the one seam in this app that answers before the
# ceiling is consulted. `Operation._run_authentication` hands any exception to
# `api.on_exception`, which is how `PageTokenMissing` already travels, so the
# refusal arrives in the product's one envelope with a code and remedies.
#
# It contributes no OpenAPI security scheme on purpose: it is not a way in, it
# is a door that is shut, and a published `bearer` scheme on a session-only
# operation would be the document promising what the door refuses.


register_refusal(
    code="session_required",
    boundary="door",
    remedy=(
        "The credential was fine and this operation is not one a bearer token may make "
        "at all — no scope reaches it, so widening the token is not the fix and offering "
        "it as one sends the caller round a loop. Drive this from a signed-in session "
        "(`manage.py issue_token` is the shell's equivalent door). If a machine genuinely "
        "needs to do this unattended, that is a product decision about delegation, not a "
        "scope to add."
    ),
    fact=(
        "This operation is only done by a person signed in with a browser session. A "
        "bearer token cannot make it, whatever scopes the token carries — so there is no "
        "wider token to go and mint. Nothing was read and nothing was written."
    ),
    remedies=(
        Remedy(
            "Sign in, and make this call from the session the browser then holds",
            "self:session",
        ),
        Remedy(
            "Read what this refusal means, and what else this API can refuse with",
            "introspect:refusals",
        ),
    ),
    # 403, its base class's. This is the code whose missing `CODE_STATUS` line
    # was the live defect rule 47 was born against: registered, refusable,
    # declared by the mint route — and dropped from that route's own
    # `x-refusal-codes` because `config/api.py` had not heard of it. It is
    # published by this line now, in the file that raises it.
    status=403,
)
# The SECOND way out — somebody with a shell on this deployment mints it for
# you — is deliberately not a remedy here, and the reason is rule 40's: a
# destination is a `<kind>:<name>` token a renderer classifies by kind, the
# enumerated kinds are `docs`, `field`, `header`, `introspect`, `route` and
# `self`, and none of them names a management command. Inventing `shell:` is
# an edit to the `Remedy` docstring in `apps/core/exceptions.py` — the file
# that owns the vocabulary — and it belongs to whoever owns that file. The
# path is said in prose on the route that refuses, where it is
# read by the person who can act on it, and in the internal `remedy` above.


class SessionRequired(Forbidden):
    """A bearer token at an operation only a signed-in person may make.

    A `Forbidden`, so the one mapper answers it `403` by walking the class tree
    and no status table is edited — the same construction `InsufficientScope`
    uses, and for the same reason.

    Named for what is *required* rather than for what was presented, for
    `PageTokenMissing`'s reason: the name reaches a caller through the OpenAPI
    document and through `introspect`, and the useful half is what to do next.

    Deliberately NOT a narrowing of `insufficient_scope`. That code means "a
    wider token would have worked", and a client — or an agent — is entitled to
    act on it by asking for a wider token. Here no token works, and saying so in
    the code rather than only in the prose is what stops the loop.
    """

    code = "session_required"
    default_detail = (
        "This operation is only done by a person signed in with a browser session; a "
        "bearer token cannot make it."
    )


class SessionOnly:
    """An authenticator that refuses a bearer token, and declines everything else.

    Placed FIRST in a route's `auth=` list, ahead of `SessionCookieAuth`: it
    answers the caller who brought a token and steps out of the way of the one
    who brought a cookie. It authenticates nobody — returning `None` is
    declining, and ninja goes on to the next authenticator, so the session path
    is untouched and a caller with no credential at all still reaches the 401 at
    the end of the list.

    It reads the `Authorization` header rather than asking whether a token
    *resolved*, and the two differ for a caller whose token is expired or
    revoked. That caller gets this refusal too, which is the right answer: they
    are at a door no token opens, and telling them their token is stale would
    send them to renew it and come straight back. The same test is what
    `SessionCookieAuth` declines on, so the two halves of the pair agree about
    which caller is at which door.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __call__(self, request: HttpRequest) -> Any | None:
        if request.headers.get(AUTHORIZATION_HEADER):
            raise SessionRequired(self.reason)
        return None


class ApiTokenAuth(HttpBearer):
    """`Authorization: Bearer <token>`.

    `TenantMiddleware` has already run and, for a token request, saw an
    anonymous user — so the tenant **and the acting hat** are resolved here,
    from the token and the same `X-Org` header, and put on the request where
    every route reads them. The hat goes through `core.middleware.resolve_org`,
    the one function both HTTP doors and the MCP mount call, so a token gets
    exactly the rows a session for the same person and the same header would.

    **A presented bearer that resolves to nobody is REFUSED here, not
    declined**, and the difference is the sentence the caller reads — see the
    raise below.
    """

    openapi_name = "ApiToken"

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        resolved = authenticate_token(
            plaintext=token,
            requested_slug=request.headers.get(TENANT_HEADER),
        )
        if resolved is None:
            # RAISED RATHER THAN DECLINED, and nothing about the status changes:
            # this was a 401 before and is a 401 now. What changes is the
            # `detail`. Declining left ninja to reach the end of `API_AUTH` and
            # raise its own `AuthenticationError`, which `config/api.py`
            # translates with the registry's `default_detail` — the sentence for
            # a caller who sent NOTHING — over a credential this door had just
            # looked up and refused. The machine door has always said the true
            # one, and `/mcp` and this door are two doors onto one refusal.
            #
            # Nothing behind this authenticator can answer for this caller
            # anyway: `SessionCookieAuth` declines every request carrying
            # `Authorization` (above), so a decline here only ever reached the
            # end of the list. And `HttpBearer.__call__` has already established
            # that a bearer was presented — a missing header, or a scheme that
            # is not Bearer, never reaches this method at all, which is what
            # keeps the sentence honest about what happened.
            #
            # It travels the path `PageTokenMissing` already travels:
            # `Operation._run_authentication` hands an authenticator's exception
            # to `api.on_exception`, so the refusal arrives in the product's one
            # envelope with its code and its remedies (`config/api.py`).
            raise Unauthenticated(BEARER_NOT_VALID)
        user, tenant, token_row = resolved
        request.user = user
        cast(TenantRequest, request).tenant = tenant
        org = resolve_org(
            user=user,
            tenant=tenant,
            requested_slug=request.headers.get(ORG_HEADER),
        )
        cast(TenantRequest, request).org = org
        setattr(request, TOKEN_AUTH_ATTR, True)
        # The token row itself, for the audit trail: "which integration" is a
        # different question from "which user", and only this answers it.
        setattr(request, TOKEN_ATTR, token_row)
        # `TenantMiddleware` ran before this and saw an anonymous user, so the
        # context it bound says nobody. Correct it here — this is the machine
        # door, and `actor_kind="agent"` is what an audit row needs to be true.
        context.bind(
            tenant_id=str(tenant.pk) if tenant is not None else None,
            org_id=str(org.pk) if org is not None else None,
            user_id=str(user.pk),
            actor_kind="agent",
        )
        return user


class SessionCookieAuth(SessionAuth):
    """`SessionAuth`, with two declines added: it answers for the browser only.

    ninja's `SessionAuth` is an `APIKeyCookie`, and an `APIKeyCookie` runs the
    CSRF check *inside* `_get_key` and **raises** `HttpError(403)` when it
    fails. An authenticator that raises does not fall through to the next one —
    it becomes the response. So a request with an `Authorization` header and no
    cookie was answered "CSRF check Failed", which is both wrong and unhelpful:
    there was no cookie to forge a request with.

    Declining here is not a hole. A caller that sends `Authorization` has said
    which door it is at; if the token is bad, `ApiTokenAuth` has already
    returned `None` and ninja answers 401. What this cannot do is let a browser
    skip CSRF: a browser sends its session cookie automatically and does *not*
    send `Authorization`, so a cross-site form post has no way to reach this
    branch — the attacker would have to set a header, which is the thing CORS
    already stops them doing.

    **The second decline is the same argument about the caller with nothing at
    all.** A `POST` with no `Authorization`, no session cookie and no CSRF token
    is an unauthenticated request, and it was being answered 403 "CSRF check
    Failed" — a status that says *"we know who you are and you still may not"*
    and prose that sends the client hunting for a token it has no session to
    attach one to. `APIKeyCookie._get_key` reaches the CSRF check before it ever
    looks for the cookie, so the emptiest possible request got the most specific
    possible refusal. Declining when `SESSION_COOKIE_NAME` is absent lets ninja
    reach the end of `API_AUTH` and answer **401**, which is what "authenticate
    first" is spelled.

    Nothing is loosened, and the reason is one line: CSRF exists to stop a
    *credential the browser attaches by itself* being used by somebody else's
    page. No cookie means no credential, means nothing for a forged request to
    ride on. The request that does carry a session cookie takes exactly the path
    it always took, CSRF check and all.
    """

    def __call__(self, request: HttpRequest) -> Any | None:
        if request.headers.get(AUTHORIZATION_HEADER):
            return None
        if settings.SESSION_COOKIE_NAME not in request.COOKIES:
            return None
        try:
            return super().__call__(request)
        except HttpError as raised:
            # THE THIRD CORRECTION, AND IT IS ABOUT THE BODY RATHER THAN THE
            # STATUS. The refusal above stays a refusal — nothing is
            # loosened, the check is Django's own and it still runs — but
            # `APIKeyCookie._get_key` announces it by raising
            # `HttpError(403, "CSRF check Failed")`, and ninja turns that into
            # `{"detail": "CSRF check Failed"}`: no `code` to branch on, no
            # remedy, and a sentence about our middleware rather than about the
            # caller's request. Re-raising the domain refusal here is what puts
            # it back inside the one envelope every other refusal travels in.
            #
            # Narrow on purpose: only a 403 out of this call is the CSRF check,
            # because the cookie authenticator has no other way to refuse — it
            # DECLINES (returns None) for everything else. Anything else is
            # somebody's genuine `HttpError` and is left to travel as itself.
            if raised.status_code != 403:
                raise
            raise PageTokenMissing() from raised


def authenticated_by_token(request: HttpRequest) -> bool:
    """True when this request got in with a bearer token rather than a session."""
    return bool(getattr(request, TOKEN_AUTH_ATTR, False))


# The API default and what every router restates. Bearer token for the machine
# door, session cookie for the human door; both end at a user and a tenant.
#
# **The token first** — see the module docstring: the cookie authenticator
# raises on a failed CSRF check rather than declining, so anything ahead of it
# that a machine can satisfy has to come first or the machine door is 403.
API_AUTH = [ApiTokenAuth(), SessionCookieAuth()]

#: The narrowing the mint door takes, and the only one in the product.
#: A route may narrow its `auth=` and never drop it (house rule 3), and this is
#: the narrowing: the token half of `API_AUTH` is replaced by the door that
#: refuses a token in the product's own words instead of the one that lets it in.
#:
#: The sentence lives here rather than in `api.py` because this module is where
#: the rule is already explained — a token that could mint tokens would survive
#: being revoked, because its offspring would keep working — and a refusal is
#: only as good as the reason travelling with it.
MINT_AUTH = [
    SessionOnly(
        "A token cannot mint another token; sign in to do that. A token that could "
        "mint would survive being revoked, because its offspring would keep working — "
        "so no scope reaches this and there is no wider token to go and get."
    ),
    SessionCookieAuth(),
]
