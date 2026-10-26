"""The staff door onto users and the tokens they hold.

`UserAdmin` inherits **both** `core.admin.ServiceModelAdmin` (house rule 21) and
Django's own `UserAdmin`, in that order. The first gives it the house behaviour
— writes through a service where there is one, scoped reads, `door="admin"` in
the audit row — and the second gives it password hashing, the change-password
view and the permission widgets, which are the entire reason Django ships a
`UserAdmin` at all.

`service_for` returns `None` here, deliberately and with the reason stated on
it: `create_user` cannot take over from the add form without also taking over
password validation and the "set a usable password?" flow, and a worse copy of
those is not an improvement. `User` is not tenant-scoped, so the scoping half of
the rule has nothing to narrow either.

**On whether this door should exist at all**, recorded so the
next reader does not re-open it: the add-person page is fixed here and no
position is taken on its future. A separate ruling may decide that
creating a person belongs to `invite_member` and that this door should narrow
or close. Either answer is fine and both are reachable from here — what is not
fine is a staff member clicking Add and getting a traceback.
The test module `tests/test_admin_user_door.py` is written to that shape: a
working door passes, a deliberate refusal naming `invite_member` passes, a 500
fails.
"""

import posixpath
from typing import Any, ClassVar
from urllib.parse import unquote

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    AdminUserCreationForm,
    UserChangeForm,
)
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

from apps.accounts.models import ApiToken, SsoConnection, SsoDomain, SsoIdentity, User
from apps.core.admin import Action, ReadOnlyModelAdmin, ServiceModelAdmin


class UserCreateForm(AdminUserCreationForm[User]):
    """The add form, on the base Django's own `UserAdmin` uses.

    **`AdminUserCreationForm`, not `UserCreationForm`** — and the difference is
    the whole point. Django 5.1 split the two: `UserCreationForm` is the
    *self-service* sign-up form and requires a password, while
    `AdminUserCreationForm` is the *staff* one and declares the extra
    `usable_password` radio that lets a staff member create a person with no
    password at all (they will arrive through the identity platform instead).
    `add_fieldsets` below names `usable_password`, because that is the field
    Django's own add-form template renders — so on the self-service base the
    admin's `get_form` found a fieldset naming a field the form did not have and
    raised `FieldError: Unknown field(s) (usable_password)`, which the admin
    turns into a 500 on every GET of `/admin/accounts/user/add/`.

    The two halves have to agree, and this is the half that was wrong: the
    fieldset describes the staff flow, so the form must be the staff form.
    Naming the base explicitly here (rather than inheriting `DjangoUserAdmin`'s
    `add_form` by omission) is deliberate — the `Meta.fields` list below is the
    reason this form exists at all, and it is the same reason `UserEditForm`
    exists.
    """

    class Meta(AdminUserCreationForm.Meta):
        model = User
        # The *model* fields the form may write. `usable_password`, `password1`
        # and `password2` are declared form fields, not columns, and are not
        # listed here for the same reason they are not in `UserEditForm`.
        fields = ("email",)


class UserEditForm(UserChangeForm[User]):
    """The editable fields, listed.

    `"__all__"` is what puts the next column somebody adds onto a staff form
    nobody reviewed — including one a product means to keep out of the admin.
    The list below is the same set the `fieldsets` render, said once more where
    the form itself decides what may be written.
    """

    class Meta(UserChangeForm.Meta):
        model = User
        # django-stubs types the base's `fields` as `str`, because Django ships
        # it as `"__all__"`. A list is what Django itself documents here.
        fields: ClassVar[Any] = (
            "email",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )


@admin.register(User)
class UserAdmin(ServiceModelAdmin[User], DjangoUserAdmin[User]):
    """The minimum that makes a UUID, email-identified user editable."""

    def service_for(self, action: Action) -> Any | None:
        # See the module docstring: taking the add form over would mean taking
        # password validation over too, and doing it worse.
        return None

    def user_change_password(
        self, request: HttpRequest, id: str, form_url: str = ""
    ) -> HttpResponse:
        """`/admin/accounts/user/<id>/password/` — the third password door, shut.

        `DjangoUserAdmin` mounts this inside `get_urls()`, so it is not a URL
        `config/urls.py` can shadow the way it shadows `AdminSite`'s two: it is
        refused where it is defined. Measured before that override, a SUPERUSER
        GET of it answered 200 with two `type="password"` inputs and a POST
        wrote another person's `User.password` — the same second credential
        store ADR ident-4 closed, one level down from the page the field test
        named, and
        reachable for exactly the population `createsuperuser` creates.

        The link on the change page (`UserChangeForm`'s `password` help text,
        `../password/`) is deliberately left pointing here: it now leads to a
        page that says why, which is better than a 404 that says nothing. The
        method signature is Django's, `id` shadowing the builtin included —
        this is an override, and an override that renamed the argument would
        stop being one.
        """
        return _password_page_refusal(request)

    add_form = UserCreateForm
    form = UserEditForm
    change_password_form = AdminPasswordChangeForm
    model = User

    list_display = ("email", "is_active", "is_staff", "is_superuser", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email",)
    ordering = ("email",)
    readonly_fields = ("id", "created_at", "updated_at", "last_login", "date_joined")

    fieldsets: ClassVar[Any] = (
        (None, {"fields": ("id", "email", "password")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets: Any = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "usable_password", "password1", "password2"),
            },
        ),
    )


@admin.register(ApiToken)
class ApiTokenAdmin(ReadOnlyModelAdmin[ApiToken]):
    """Visible, revocable nowhere but through the service.

    Read-only because there is nothing here a form should do: a token is minted
    by `issue_token` (which returns the plaintext once) and stopped by
    `revoke_token`, and the only column a form could offer to edit is the hash —
    which would silently invalidate the token without recording that anybody did
    it.
    """

    list_display = ("name", "user", "tenant", "last_used_at", "revoked_at", "created_at")
    list_filter = ("revoked_at",)
    list_select_related = ("user", "tenant")
    search_fields = ("name", "user__email", "tenant__slug")
    ordering = ("-created_at",)


# --- Customer SSO -------------------------------------------------------------
# All three are read-only, and the reason is the same for all three: **there is
# no form here that would be an improvement on the service.**
#
# For `SsoConnection` specifically it is worth spelling out, because it looks
# like an obvious candidate for `ServiceModelAdmin`'s write path. The services
# take `issuer`, `client_id`, `client_secret` and `email_domains`; the table has
# `metadata` (one encrypted blob) and a related `SsoDomain` set. `call_service`
# maps changed *form fields* to service keywords, and those two shapes do not
# line up — so wiring it would mean either a custom form that reconstructs the
# service's arguments (a second, less-tested copy of the API's job) or an admin
# textarea containing a client secret in plain text on a staff member's screen.
#
# Configuration goes through `/api/v1/auth/sso-connections/`, which is
# authorized, audited and has the schema. The admin is where somebody *looks* at
# what a customer has configured while they are on the phone to them, and for
# that, read-only is the whole requirement.


@admin.register(SsoConnection)
class SsoConnectionAdmin(ReadOnlyModelAdmin[SsoConnection]):
    """A tenant's identity provider, visible and unchangeable from here.

    `client_secret` is deliberately absent from every list and detail view.
    `has_client_secret` answers the only question a human asks of it ("is this
    one set up?"), which is the same line `Connection.has_credentials` draws.
    """

    list_display = (
        "name",
        "tenant",
        "protocol",
        "status",
        "enforced",
        "default_role",
        "created_at",
    )
    list_filter = ("protocol", "status", "enforced")
    list_select_related = ("tenant",)
    search_fields = ("name", "tenant__slug", "domains__domain")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "tenant",
        "name",
        "protocol",
        "status",
        "enforced",
        "default_role",
        "issuer",
        "client_id",
        "has_client_secret",
        "claimed_domains",
        "created_at",
        "updated_at",
        "disabled_at",
    )
    fields = readonly_fields

    @admin.display(description="Claimed email domains")
    def claimed_domains(self, obj: SsoConnection) -> str:
        return ", ".join(obj.email_domains) or "—"

    @admin.display(description="Client secret stored", boolean=True)
    def has_client_secret(self, obj: SsoConnection) -> bool:
        return obj.has_client_secret

    @admin.display(description="Issuer")
    def issuer(self, obj: SsoConnection) -> str:
        return obj.issuer

    @admin.display(description="Client ID")
    def client_id(self, obj: SsoConnection) -> str:
        return obj.client_id


@admin.register(SsoDomain)
class SsoDomainAdmin(ReadOnlyModelAdmin[SsoDomain]):
    """Which domain routes to which connection.

    Read-only for a sharper reason than the others: `domain` is unique across
    every tenant, so an admin who could edit one could move a customer's whole
    login to another tenant's identity provider with a text field and no audit
    row. `services.update_sso_connection` is the only way, and it says so.
    """

    list_display = ("domain", "connection", "tenant", "created_at")
    list_select_related = ("connection", "tenant")
    search_fields = ("domain", "connection__name", "tenant__slug")
    ordering = ("domain",)


@admin.register(SsoIdentity)
class SsoIdentityAdmin(ReadOnlyModelAdmin[SsoIdentity]):
    """Who arrived through which connection, and when they were last seen.

    The support view for "why can this person not sign in": either there is a
    row here, or their identity provider has never successfully asserted them.
    """

    list_display = ("subject", "email", "user", "connection", "tenant", "last_seen_at")
    list_select_related = ("user", "connection", "tenant")
    search_fields = ("subject", "email", "user__email", "connection__name")
    ordering = ("-created_at",)


# --- The admin's front door, which is the product's front door ----------------
#
# ADR ident-4. `/admin/login/` used to answer 200 with Django's own "Log in
# | Django site admin" page — an Email and a Password field POSTing back to
# itself, authenticating against `User.password`. That is the second credential
# store the ADR closed, reachable, unbranded, and pointed at by the setup
# epilogue. This view is mounted ONE line ahead of `admin.site.urls` in
# `config/urls.py` (the recorded decision) and shadows that URL and only that
# URL: every other `admin:` name reverses where it always did, and no `AdminSite`
# is subclassed, forked or re-registered.
#
# WHY IT LIVES IN `admin.py` AND NOT IN A `views.py`. `apps/accounts/views.py` is
# `djb.E011` on sight today — `views` is not in `CANONICAL_MODULES`
# (`apps/core/checks.py`) and not in rule 11's `extra_modules` for this app — and
# both files that would have to change belong to other territory. The
# tree's own precedent for a view outside a `views.py` is
# `oauth.protected_resource_metadata_view`, mounted the same way from the module
# whose subject it is: a view belongs with the thing it is a door onto, and the
# thing this is a door onto is the admin.
#
# WHY IT ISSUES A CSRF COOKIE. The page it replaces did, because it rendered a
# form with `{% csrf_token %}` in it, and four modules across this tree take
# their server-issued token from a GET of exactly this URL
# (`CSRF_SOURCE_URL` in `apps/accounts/tests/test_auth_over_the_wire.py`,
# `test_mcp_oauth.py`, `apps/core/tests/test_idempotency_over_the_wire.py`,
# `apps/example/tests/test_doors_over_the_wire.py`). A CSRF token is not a
# credential — it authenticates nobody and is useless without the session it is
# bound to — so keeping the cookie costs nothing and keeps four modules that are
# about something else entirely from having to move.

#: The one sentence a signed-in person who cannot use the admin reads. One
#: constant because the template renders it and the wire test asserts it, and a
#: wall that says two different things is two walls.
ADMIN_REFUSED_SENTENCE = "This account cannot use the admin."

#: The one sentence anybody who reaches the admin's password page reads. The
#: sibling of the constant above, and separate from it because it says a
#: different true thing: the account is fine, the *page* is gone.
#:
#: The pragma is `detect-secrets`' Secret Keyword heuristic reading the word
#: before the `=`: any name containing "password" assigned a string literal is
#: a candidate, and this one is an English sentence rendered on a public
#: refusal page. There is no credential in this module to leak.
PASSWORD_CHANGE_REFUSED_SENTENCE = "Passwords are not changed here."  # noqa: S105 — the refusal sentence the admin shows, not a credential  # pragma: allowlist secret


def _shadowed_admin_paths() -> tuple[str, ...]:
    """The admin URLs this module answers instead of Django, resolved live.

    Read off `reverse()` at call time rather than written down: this module is
    imported while the app registry is still loading, so a module-level
    `reverse()` here is an import cycle, and a hand-typed `"/admin/login/"`
    would be a second spelling of a path `config/urls.py` already owns.

    A prefix match, not equality — `/admin/password_change/done/` hangs under
    the second of these and is the same non-destination for the same reason.
    """
    return (reverse("admin:login"), reverse("admin:password_change"))


def _admin_destination(request: HttpRequest) -> str:
    """Where inside the admin this request was heading, defaulting to its index.

    `?next=` is honoured only when it stays *inside* the admin and is local to
    this host: this view is the admin's door and has no business forwarding a
    browser anywhere else, which makes the ordinary open-redirect question moot
    rather than merely answered.

    **The door is not a destination.** `/admin/login/` is itself under
    `admin:index`, so the first form of this function honoured
    `?next=/admin/login/` and sent a staff session straight back to the view
    that produced it — a redirect to itself, forever, for the one `?next=` a
    browser lands on most easily (a bookmark of the old password page, or a
    second bounce through `admin.site.admin_view`). Every URL this module
    shadows is excluded for the same reason: none of them is a page anybody was
    ever heading *to*, so "where were you going" has one honest answer here, and
    it is the index.

    **A prefix test is a test on the SPELLING, so the spelling is settled
    first.** `/admin/../accounts/profile/` starts with `/admin/`, satisfies
    `url_has_allowed_host_and_scheme` (it is relative and names no host) and
    resolves in the browser to `/accounts/profile/` — outside the admin,
    through the one check that exists to keep a destination inside it. The
    percent-encoded spelling is the same string ONE decode later: Django
    decodes the query value into `request.GET`, so `%2E%2E` arrives here as
    `..`. A *doubly* encoded `%252E%252E` arrives as the literal text `%2E%2E`,
    which `normpath` leaves alone and a browser then collapses itself when it
    follows the `Location` — measured, and the reason the decision unquotes one
    more time before it normalises. Unquoting for the decision can only make
    this function refuse MORE, never less, which is the direction a door may
    err in.

    `posixpath.normpath` collapses `.`, `..` and doubled separators, and the
    DECISION is made on the collapsed form while the value RETURNED is the one
    that was asked for — normalising the answer too would quietly rewrite
    `/admin/accounts/user/` to a path with no trailing slash and buy a second
    redirect for every legitimate destination.
    """
    root = reverse("admin:index")
    asked = request.GET.get(REDIRECT_FIELD_NAME, "")
    # The path this actually reaches, which is the only thing worth testing.
    # `normpath` leaves a leading `//` alone (POSIX says it may mean something),
    # which is right here: a protocol-relative URL must still fail the prefix
    # test below, and it does.
    settled = posixpath.normpath(unquote(asked)) if asked else ""
    if not settled.startswith(root):
        # Outside the admin entirely: another app's path, an absolute URL, a
        # protocol-relative `//host/…`, a traversal back out. One answer for all.
        return root
    # Compared against the collapsed spelling, so the trailing slash comes off
    # the shadowed paths too — and the match is on a SEGMENT boundary, not a
    # bare prefix, so `/admin/logins/` is somebody else's 404 and not ours to
    # swallow. Catching the slashless `/admin/login` here rather than letting
    # `APPEND_SLASH` bounce it through the door a second time is the same
    # question answered one hop earlier.
    for shadowed in _shadowed_admin_paths():
        stem = shadowed.rstrip("/")
        if settled == stem or settled.startswith(f"{stem}/"):
            return root
    if not url_has_allowed_host_and_scheme(
        url=asked, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return root
    return asked


@ensure_csrf_cookie
@require_safe
def admin_login(request: HttpRequest) -> HttpResponse:
    """`GET /admin/login/` — three answers, and none of them is a password field.

    * **Anonymous** → 302 to the one sign-in door, carrying where they were
      going. There is exactly one place to authenticate in this deployment and
      the admin now points at it instead of offering an alternative.
    * **Signed in and staff** → 302 into the admin. The door is already open;
      Django's own view answered this case the same way and it keeps doing so.
    * **Signed in and not staff** → 403, rendered in the entrance shell, saying
      so. This is the case the defect was really about: the old page bounced a
      signed-in owner into a form they could never complete, with nothing on it
      to explain why, so "my password is wrong" was the only reading left.

    A POST is 405 (`require_safe`) and never reaches an authentication backend —
    the stronger half of the criterion, and the reason this is a new view rather
    than a new template on Django's: a template swap leaves `AdminSite.login`
    reading `User.password` on POST, one form field away from being a door again.
    """
    user = request.user
    destination = _admin_destination(request)
    if not user.is_authenticated:
        # Django's own helper, not a hand-built URL: it resolves `LOGIN_URL`
        # (a path or a route name) and writes `?next=` with `/` left unescaped,
        # which is the Location every other redirect-to-login in the stack
        # produces. A second spelling here would differ in the escaping alone.
        return redirect_to_login(destination)
    if user.is_staff:
        return HttpResponseRedirect(destination)
    return render(
        request,
        "accounts/admin_refused.html",
        {
            "sentence": ADMIN_REFUSED_SENTENCE,
            "email": getattr(user, "email", ""),
            "landing": settings.LOGIN_REDIRECT_URL,
        },
        status=403,
    )


# --- The admin's password pages, which are no longer pages --------------------
#
# ADR ident-4, second half. Closing `/admin/login/` left the two
# surfaces BEHIND it that still wrote `User.password`, both measured on the
# tree before this change, over the wire:
#
#   GET  /admin/password_change/                   -> 200, three type="password"
#                                                     inputs, "Password change |
#                                                     Django site admin"
#   POST /admin/password_change/                   -> 302 .../done/ and the hash
#                                                     on the row CHANGED
#   GET  /admin/password_change/done/              -> 200 "Password change
#                                                     successful" — a sentence
#                                                     about a store this
#                                                     deployment does not keep
#   GET  /admin/accounts/user/<id>/password/       -> 200, two type="password"
#                                                     inputs (superuser; a plain
#                                                     staff member is already
#                                                     403 for want of the
#                                                     permission)
#
# The first three are `AdminSite`'s and are shadowed in `config/urls.py` the
# way I8 shadowed the login page — two `path()` lines ahead of
# `admin.site.urls`, no `AdminSite` subclassed and every `admin:` name still
# reversing where it always did (`admin:password_change`,
# `admin:password_change_done`). The fourth is `UserAdmin`'s own method and is
# refused where it is defined, below, which needs no mount at all.
#
# WHY THE `done` PAGE IS SHADOWED TOO, when nothing can reach it any more: a
# page saying "Password change successful" in a deployment with one credential
# store somewhere else is the same defect as the form — a true-looking sentence
# about the wrong system — and it is reachable by typing the URL that was in
# somebody's history. One more line costs nothing and says the true thing.
#
# WHAT IS DELIBERATELY LEFT: `/admin/accounts/user/add/` still offers
# `usable_password` and a password pair, because CREATING a person with a
# password is a different act from changing one, it is the recorded decision in
# this module's own docstring, and the field test did not name it. It is a
# declared frontier in the report that landed this change.


def _password_page_refusal(request: HttpRequest) -> HttpResponse:
    """The one answer every admin password surface gives, rendered once.

    403 in the entrance shell with no `<form>`, no field and no retry — I8's
    shape, for the same reason: a wall somebody can do nothing about from the
    browser they are holding says so, and offers nothing to try.
    """
    return render(
        request,
        "accounts/admin_password_refused.html",
        {
            "sentence": PASSWORD_CHANGE_REFUSED_SENTENCE,
            "sign_in": settings.LOGIN_URL,
            "landing": settings.LOGIN_REDIRECT_URL,
        },
        status=403,
    )


@require_safe
def admin_password_change(request: HttpRequest) -> HttpResponse:
    """`GET /admin/password_change/` (and its `done/`) — never a password field.

    * **Anonymous** → 302 to the one sign-in door, heading for the admin index.
      There is nowhere else to authenticate and this page is not a destination.
    * **Any session, staff or not** → 403 in the entrance shell. Staff is not
      the distinction here the way it is at the login door: the page is gone
      for everybody, because the credential it wrote is not ours to write.

    A POST is 405 (`require_safe`) and reaches no form at all — the same
    stronger half I8's view has, and the reason this is a shadowing view rather
    than a template override: `AdminSite.password_change` would still call
    `PasswordChangeForm.save()` on POST behind any template we gave it.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(reverse("admin:index"))
    return _password_page_refusal(request)
