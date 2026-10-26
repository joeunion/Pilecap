from typing import TYPE_CHECKING, ClassVar

from django.apps import AppConfig

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.core.models import Tenant


def tenant_for_bearer_credential(request: "HttpRequest") -> "Tenant | None":
    """Which tenant a bearer token lands in — answered before the view runs.

    Registered into `core.idempotency` by `AccountsConfig.ready()` below.
    `IdempotencyMiddleware` has to build a request's scope before anything has
    authenticated it, and for a machine request that means before `ApiTokenAuth`
    has read the token at all. This is that answer, given early.

    **It is the same answer, not a second one.** `authenticate_token` is the one
    function both HTTP doors and the MCP mount already resolve a token with, and
    it is called here exactly as `ApiTokenAuth` calls it — the same plaintext,
    the same `X-Tenant` through the same declared constant. A resolver that
    reimplemented the pin rule, or the revocation check, or the default-
    membership fallback would be a second copy of a single truth, which is the
    drift this cycle is about; there is none here.

    **It authorizes nothing and grants nothing.** Nothing downstream trusts it:
    the route still authenticates, and what this returns only ever decides which
    *scope* an idempotency record is filed under. A wrong answer would move a
    request into a scope of its own — never into somebody else's — which is why
    it may fail closed by simply returning `None`.

    `None` means "not mine to answer": no `Authorization` header, a scheme that
    is not Bearer, an empty token, or a credential `authenticate_token` refuses
    — a revoked token, an inactive user. All of them are requests that resolve
    no tenant in the view either, and a record written by one carries a NULL
    tenant that `_may_replay` hands to nobody. The first two cost nothing at
    all: they decline on the header, before any query, which is what keeps the
    session path free of the seam's expense.

    **A pin the header contradicts is no longer one of them** (ADR core-21).
    `authenticate_token` answers WHO and returns the pin; the request is
    then refused at the door for WHERE it asked to act, with 403. So this
    answers the pinned tenant, the claim is filed under it, and the 403 that
    follows is above `REPLAYABLE_BELOW` — so `_remember` drops the claim and a
    corrected retry under the same key proceeds as the fresh request it is.

    Imported inside the body because this module is read by
    `config.settings.discovery` to derive `INSTALLED_APPS`, before Django is
    ready — the constraint `AccountsConfig.ready()` is written around too.
    """
    from apps.accounts.auth import AUTHORIZATION_HEADER, resolve_bearer

    scheme, _, plaintext = request.headers.get(AUTHORIZATION_HEADER, "").partition(" ")
    if scheme.lower() != "bearer" or not plaintext.strip():
        return None
    resolved = resolve_bearer(request, plaintext)
    return resolved.tenant if resolved is not None else None


class AccountsConfig(AppConfig):
    """The user, and the token a machine acts as one with."""

    name = "apps.accounts"
    verbose_name = "Accounts"
    # Runs start through `core.bridge` and the seams live in `core`, so `workflows` is no import.
    depends_on: tuple[str, ...] = ("core",)
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 3817,
        "91.docstring-tail": 8330,
        "91.module-tail": 2253,
        "91.narrative": 96,
    }

    def ready(self) -> None:
        """Fill the two seams `core` declares for this app: bearer tenancy, and a tenant's realm.

        The one thing `core` cannot answer for itself. `IdempotencyMiddleware`
        builds a request's scope before the view runs, and for a bearer token
        the tenant is not known until `ApiTokenAuth` resolves it inside the view
        — off an `ApiToken` row that lives here, in an app `core` may not import
        (house rule 7, the fixed layer direction). Unresolved, that credential
        was scoped on itself alone, so one person's two hats shared a scope and
        a replay crossed between them (ADR core-16, which declared
        the hole; this line closes it).

        So the call inverts: `core` declares the seam, this app registers into
        it, and no import runs upward. The same shape `core.bridge` uses for
        every other call that has to go against the layer direction — and the
        dependency it needs is already declared, in `depends_on` above.
        """
        from apps.accounts.services import _ask_for_identity_home
        from apps.core import bridge
        from apps.core.idempotency import register_tenant_resolver

        register_tenant_resolver(tenant_for_bearer_credential)
        # And the one thing `core.create_tenant` cannot do for itself: give the
        # new tenant a realm of its own. `core` may not name this app, so it
        # asks through the bridge and this app answers — the
        # `START_WORKFLOW_ON_COMMIT` shape, the other way round.
        bridge.register(bridge.ENSURE_IDENTITY_HOME, _ask_for_identity_home)
