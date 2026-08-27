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

from typing import Any, ClassVar

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    AdminUserCreationForm,
    UserChangeForm,
)

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
