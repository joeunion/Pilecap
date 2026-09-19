"""There is one credential store, and it is not this one (ADR ident-4).

Zitadel hosts every interactive authentication, including the passwords
of local users, and the owner closed the A-vs-B: two credential stores is the
shape where "disable this person" has to be done twice and is done once.

What that means concretely is asserted here rather than described: the login
POST is refused, and the URLs that could set or reset a password **do not
exist**. The second half is the stronger one. A URL that exists and refuses is
one `if` away from being a door again; a URL that does not resolve cannot be
reopened by accident, and `reverse()` raising is what a future change trips over.

`test_auth_over_the_wire.py` carries the other half of this criterion — the four
V1 CSRF probes — and is deliberately **not touched** by this change. Its subject is
`API_AUTH` and the session cookie, both of which this change leaves alone; that
it still passes unmodified is the regression net, and editing it to make it pass
would have cut the net.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import NoReverseMatch, resolve, reverse

from apps.accounts.admin import admin_login, admin_password_change
from apps.accounts.models import SsoConnection
from apps.accounts.services import create_user
from apps.accounts.tests.stub_issuer import StubIssuer

# The custom property our entrance shell declares — imported from the module
# that owns the census rather than spelled a second time here, so a rename of
# the token moves both at once. Since I1b that module READS the marker off
# `IDENTITY_SHAPE["entrance_marker"]` rather than pinning it, so the seam is a
# function and these two cases follow it: a product that draws its own entrance
# asks the same question of its own shell.
from apps.accounts.tests.test_entrance_chain import token_marker
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

# The login URL survives, GET-only: the page is how somebody reaches the IdP.
LOGIN_URL = "/accounts/login/"

# Every URL that could take, set or reset a local password. Each one used to
# resolve; none of them may now.
RETIRED_URL_NAMES = [
    "account_signup",
    "account_change_password",
    "account_set_password",
    "account_reset_password",
]


def test_posting_a_correct_password_is_refused_and_creates_no_session(api: Client) -> None:
    """The account is real and the password is right. That is the point.

    Answering "that password was correct" for an account whose authentication
    has moved elsewhere is most of what moving it was for.
    """
    person = create_user(email="staff@example.com", password="a-long-enough-password")

    response = api.post(
        LOGIN_URL,
        {"login": person.email, "password": "a-long-enough-password"},  # pragma: allowlist secret
    )

    assert response.status_code == 403
    assert "_auth_user_id" not in api.session


def test_the_login_page_still_answers_a_get(api: Client) -> None:
    """GET survives on purpose: it is the page that offers the way in.

    Retiring the form is not retiring the page. Somebody arriving at
    `/accounts/login/` has to find a door, and a 404 there would be a product
    with no visible entrance.
    """
    assert api.get(LOGIN_URL).status_code == 200


@pytest.mark.parametrize("url_name", RETIRED_URL_NAMES)
def test_the_password_urls_do_not_exist(url_name: str) -> None:
    """Not "refuse" — *gone*. `SOCIALACCOUNT_ONLY` takes them out of the urlconf."""
    with pytest.raises(NoReverseMatch):
        reverse(url_name)


def test_the_login_page_offers_the_identity_provider(api: Client, stub_issuer: StubIssuer) -> None:
    """A page with no form and no button is a dead end.

    Asserted through the rendered page rather than through settings, because
    what a person can click is the property — and this is what fails the day the
    provider registration silently stops resolving.
    """
    page = api.get(LOGIN_URL).content.decode()

    assert "/accounts/oidc/zitadel/login/" in page


def test_the_page_does_not_enumerate_customer_connections(
    api: Client,
    stub_issuer: StubIssuer,
    sso_connection: SsoConnection,
    tenant: Tenant,
) -> None:
    """A login page listing every tenant's IdP is a customer list as buttons.

    `SocialAccountAdapter.list_apps` contributes nothing while allauth is
    enumerating, and this is the assertion that keeps it that way now that there
    is a static provider beside the per-connection ones.
    """
    page = api.get(LOGIN_URL).content.decode()

    assert sso_connection.name not in page
    assert sso_connection.provider_id not in page
    assert tenant.name not in page


# --- the admin's own door (ADR ident-4) ---------------------------------------
#
# The population above is allauth's. `/admin/` is the OTHER door onto the same
# `User.password` column, and it was never in it: `GET /admin/login/` used to
# answer 200 with "Log in | Django site admin" and an
# Email + Password form, so the credential store the ADR closed had a second,
# unbranded front door that a POST would have authenticated against. These
# cases are that door, over the wire, in the three states a browser can be in.

ADMIN_LOGIN_URL = "/admin/login/"
ADMIN_URL = "/admin/"

#: The two URLs behind that door that wrote `User.password` until it was shut.
ADMIN_PASSWORD_CHANGE_URL = "/admin/password_change/"
ADMIN_PASSWORD_CHANGE_DONE_URL = "/admin/password_change/done/"

#: The sentence a signed-in person who is not staff reads instead of a form.
ADMIN_REFUSAL = "This account cannot use the admin."

#: The sentence ANY session reads at the admin's password pages. Spelled here
#: rather than imported for the same reason `ADMIN_REFUSAL` is: a test that
#: imports the constant it asserts on cannot see the constant change. The
#: pragma is the Secret Keyword heuristic on the name, not on the value: the
#: value is the sentence the refusal page renders.
PASSWORD_CHANGE_REFUSAL = "Passwords are not changed here."  # pragma: allowlist secret

PASSWORD = "a-long-enough-password"  # pragma: allowlist secret

#: What a password-change form would be asked to write. Different from
#: `PASSWORD` on purpose: "the hash did not change" is only an assertion if the
#: change being attempted is a real one.
NEW_PASSWORD = "an-entirely-different-password"  # pragma: allowlist secret


def test_the_admin_login_mount_is_ours_and_the_admin_names_are_untouched() -> None:
    """One line ahead of `admin.site.urls`, and nothing else moved.

    The shadow shape: `/admin/login/` resolves to our callable, and every other
    `admin:` name still reverses to where it always did — so the admin is not
    forked, subclassed or re-registered, it just no longer owns one URL.
    """
    assert resolve(ADMIN_LOGIN_URL).func is admin_login
    assert reverse("admin:index") == ADMIN_URL
    assert reverse("admin:login") == ADMIN_LOGIN_URL


def test_the_admin_login_redirects_to_the_one_door(api: Client) -> None:
    """Anonymous: there is one place to sign in, and the admin points at it."""
    response = api.get(ADMIN_LOGIN_URL)

    assert response.status_code == 302
    assert response["Location"] == f"{LOGIN_URL}?next={ADMIN_URL}"


def test_a_staff_session_reaches_the_admin(api: Client) -> None:
    """Signed in and staff: the door is already open, so it opens."""
    person = create_user(email="staff-door@example.com", password=PASSWORD, is_staff=True)
    api.force_login(person)

    response = api.get(ADMIN_LOGIN_URL)

    assert response.status_code == 302
    assert response["Location"] == ADMIN_URL


def test_a_non_staff_session_reads_a_refusal_not_a_form(api: Client) -> None:
    """Signed in and not staff: the bounce that used to be a form nobody could use.

    The defect this closes is not that the page was ugly. It is that a signed-in
    owner following `/admin/` landed on a password prompt for a credential store
    this deployment does not keep, with nothing on the page saying so — so the
    only readings available were "my password is wrong" and "this product is
    broken", and both are false.
    """
    person = create_user(email="ordinary@example.com", password=PASSWORD)
    api.force_login(person)

    response = api.get(ADMIN_LOGIN_URL)
    body = response.content.decode()

    assert response.status_code == 403
    assert ADMIN_REFUSAL in body
    assert token_marker() in body
    assert 'type="password"' not in body


def test_posting_a_password_to_the_admin_authenticates_nobody(api: Client) -> None:
    """The POST half, and the one that matters: a correct password, refused.

    The sibling of `test_posting_a_correct_password_is_refused_and_creates_no_session`
    at the other door. The account is real, the password is right, and no
    session is created — because nothing here reads `User.password` at all.
    """
    person = create_user(email="poster@example.com", password=PASSWORD)

    response = api.post(
        ADMIN_LOGIN_URL,
        {"username": person.email, "password": PASSWORD},  # pragma: allowlist secret
    )

    assert response.status_code in (403, 405)
    assert "_auth_user_id" not in api.session


def test_admin_index_still_answers_a_staff_session(api: Client) -> None:
    """The negative: shadowing the login page changed nothing else about the admin."""
    person = create_user(email="staff-index@example.com", password=PASSWORD, is_staff=True)
    api.force_login(person)

    assert api.get(ADMIN_URL).status_code == 200


# --- where the admin login door was heading ------------------------------------
#
# `?next=` on the door above. The open-redirect half was right from the start —
# `https://evil.example/`, `//evil.example/` and `/accounts/profile/` all fell
# back to `/admin/` before this change — and the half that was wrong was
# the one nobody writes a test for: `/admin/login/` is itself under
# `admin:index`, so `?next=/admin/login/` was honoured and a staff session was
# redirected to the page it had just been served. Measured on the baseline:
#
#     GET /admin/login/?next=/admin/login/ -> 302 Location: /admin/login/
#
# One case per shape, and the shapes are the population: the door itself, a
# real page inside the admin, an absolute URL, a protocol-relative one, and a
# local path outside the admin.

#: A real page inside the admin — the one `?next=` that must still be honoured,
#: because a redirect that always lands on the index is not a fixed redirect,
#: it is a deleted feature.
ADMIN_NESTED_URL = "/admin/accounts/user/"


@pytest.mark.parametrize(
    ("asked", "why"),
    [
        (ADMIN_LOGIN_URL, "the door itself — the self-redirect the field test found"),
        (ADMIN_PASSWORD_CHANGE_URL, "the other page this module shadows"),
        ("https://evil.example/", "an absolute URL on somebody else's host"),
        ("//evil.example/", "protocol-relative, which is the same host swap wearing a local shape"),
        ("/accounts/profile/", "local, real, and not the admin's to forward to"),
        (
            "/admin/../accounts/profile/",
            "a traversal: it passes a prefix test and leaves the admin anyway",
        ),
        (
            "/admin/%2E%2E/accounts/profile/",
            "the same traversal percent-encoded — `request.GET` decodes it before we look",
        ),
        (
            "/admin/%252E%252E/accounts/profile/",
            "doubly encoded: it survives the query decode as literal %2E%2E and the "
            "BROWSER collapses it when it follows the Location",
        ),
    ],
)
def test_the_admin_login_refuses_a_destination_that_is_not_a_page(
    api: Client, asked: str, why: str
) -> None:
    """Every `?next=` that is not somewhere inside the admin lands on the index.

    The five shapes in one case each, and the parametrization is the point: the
    failure this closes was ONE member of a set whose other four members were
    already right, so a test that checked "open redirects are refused" was
    green throughout.
    """
    person = create_user(email=f"next-{abs(hash(asked))}@example.com", is_staff=True)
    api.force_login(person)

    response = api.get(f"{ADMIN_LOGIN_URL}?next={asked}")

    assert response.status_code == 302
    assert response["Location"] == ADMIN_URL, why


def test_a_slashless_spelling_of_the_door_still_ends_at_the_index(api: Client) -> None:
    """`?next=/admin/login` — the same non-destination, missing its slash.

    Pinned by FOLLOWING rather than by asserting one `Location`, because what
    matters is where a browser stops, not how many hops it takes: without the
    collapsed-spelling comparison this URL misses the shadowed set (the
    reversed path has a trailing slash and this one does not), is honoured,
    and is handed back to `APPEND_SLASH`, which bounces it into the door a
    second time. That terminated, but only by luck of the second pass; this
    case is what makes it a property. The chain is asserted whole so that a
    change which adds a hop — or a loop — is a failure and not a shrug.
    """
    person = create_user(email="next-slashless@example.com", is_staff=True)
    api.force_login(person)

    response = api.get(f"{ADMIN_LOGIN_URL}?next=/admin/login", follow=True)

    assert response.status_code == 200
    assert response.redirect_chain == [(ADMIN_URL, 302)]
    assert response.request["PATH_INFO"] == ADMIN_URL


def test_the_admin_login_still_honours_a_real_page_inside_the_admin(api: Client) -> None:
    """The negative that keeps the fix from being "always go to the index".

    A staff member who followed a link to a change list and was bounced through
    the door arrives at the change list, which is the entire reason `?next=`
    exists here.
    """
    person = create_user(email="next-nested@example.com", is_staff=True)
    api.force_login(person)

    response = api.get(f"{ADMIN_LOGIN_URL}?next={ADMIN_NESTED_URL}")

    assert response.status_code == 302
    assert response["Location"] == ADMIN_NESTED_URL


# --- the admin's password pages -------------------------------------------------
#
# The door above is shut and these three were behind it, all measured on this
# rung's baseline with a staff session:
#
#     GET  /admin/password_change/              -> 200, 3 x type="password",
#                                                 "Password change | Django site admin"
#     POST /admin/password_change/              -> 302 /admin/password_change/done/
#                                                 and User.password CHANGED
#     GET  /admin/password_change/done/         -> 200 "Password change successful"
#     GET  /admin/accounts/user/<id>/password/  -> 200, 2 x type="password" (superuser)
#
# The last of those is `UserAdmin`'s own method rather than an `AdminSite` URL,
# which is why it is refused in the ModelAdmin and not in `config/urls.py`. The
# strongest case in this section is the POST one: a correct current password,
# a valid new one, and the hash on the row unchanged afterwards.


def test_the_admin_password_change_mount_is_ours_and_the_admin_names_are_untouched() -> None:
    """The shadow shape again, and the canary: sever the mount and this reds.

    Two `config/urls.py` lines ahead of `admin.site.urls`, and the admin still
    contributes both names — `admin:password_change` and
    `admin:password_change_done` reverse to the paths they always did, so a
    template or a product that reverses either keeps working.
    """
    assert resolve(ADMIN_PASSWORD_CHANGE_URL).func is admin_password_change
    assert resolve(ADMIN_PASSWORD_CHANGE_DONE_URL).func is admin_password_change
    assert reverse("admin:password_change") == ADMIN_PASSWORD_CHANGE_URL
    assert reverse("admin:password_change_done") == ADMIN_PASSWORD_CHANGE_DONE_URL


def test_the_admin_password_change_sends_an_anonymous_browser_to_the_one_door(
    api: Client,
) -> None:
    """Anonymous: the same 302 the login door gives, heading for the index.

    Not `?next=` back to this page — there is nothing here to come back to.
    """
    response = api.get(ADMIN_PASSWORD_CHANGE_URL)

    assert response.status_code == 302
    assert response["Location"] == f"{LOGIN_URL}?next={ADMIN_URL}"


@pytest.mark.parametrize("is_staff", [True, False])
def test_the_admin_password_change_reads_a_refusal_for_every_session(
    api: Client, is_staff: bool
) -> None:
    """Staff or not, the page is gone — and it is gone in our shell, saying why.

    This is where the two admin refusals differ: the login door turns on
    `is_staff`, because being staff is what it is a door for. A password page
    turns on nothing, because the credential it wrote is not ours to write for
    anybody.
    """
    person = create_user(
        email=f"pwchange-{is_staff}@example.com", password=PASSWORD, is_staff=is_staff
    )
    api.force_login(person)

    response = api.get(ADMIN_PASSWORD_CHANGE_URL)
    body = response.content.decode()

    assert response.status_code == 403
    assert PASSWORD_CHANGE_REFUSAL in body
    assert token_marker() in body
    assert "<form" not in body
    assert 'type="password"' not in body


def test_the_admin_password_change_done_page_is_the_same_refusal(api: Client) -> None:
    """The page that said "Password change successful" says the true thing now.

    Nothing links here any more, which is exactly why it is shadowed: a URL in
    somebody's history that renders a sentence about a credential store this
    deployment does not keep is the defect this section is about, one page along.
    """
    person = create_user(email="pwdone@example.com", password=PASSWORD, is_staff=True)
    api.force_login(person)

    response = api.get(ADMIN_PASSWORD_CHANGE_DONE_URL)
    body = response.content.decode()

    assert response.status_code == 403
    assert PASSWORD_CHANGE_REFUSAL in body
    assert "Password change successful" not in body


def test_posting_a_valid_password_change_to_the_admin_changes_no_hash(api: Client) -> None:
    """The case that matters: a correct current password, and the row untouched.

    On the baseline this POST answered 302 to `.../done/` and
    `User.password` came back different. It is the sibling of
    `test_posting_a_password_to_the_admin_authenticates_nobody` one URL deeper,
    and it asserts about the COLUMN rather than about the response, because the
    response is the thing a template change could fake.
    """
    person = create_user(email="pwpost@example.com", password=PASSWORD, is_staff=True)
    api.force_login(person)
    before = person.password

    response = api.post(
        ADMIN_PASSWORD_CHANGE_URL,
        {
            "old_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    person.refresh_from_db()

    assert response.status_code in (403, 405)
    assert person.password == before
    assert not person.check_password(NEW_PASSWORD)


def test_the_per_user_password_form_is_refused_for_a_superuser_too(api: Client) -> None:
    """`/admin/accounts/user/<id>/password/` — the third door, and the widest.

    A plain staff member was already 403 here for want of the permission; a
    superuser was not, and a superuser is exactly the population
    `createsuperuser` creates. GET rendered two `type="password"` inputs on the
    baseline and POST wrote ANOTHER PERSON'S hash, which is the one write in
    this family that needs no current password at all.
    """
    operator = create_user(email="pwsuper@example.com", password=PASSWORD, is_staff=True)
    operator.is_superuser = True
    operator.save(update_fields=["is_superuser"])
    subject = create_user(email="pwsubject@example.com", password=PASSWORD)
    api.force_login(operator)
    before = subject.password
    url = f"/admin/accounts/user/{subject.pk}/password/"

    page = api.get(url)
    posted = api.post(url, {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    subject.refresh_from_db()

    assert page.status_code == 403
    assert 'type="password"' not in page.content.decode()
    assert PASSWORD_CHANGE_REFUSAL in page.content.decode()
    assert posted.status_code == 403
    assert subject.password == before
    assert not subject.check_password(NEW_PASSWORD)


def test_the_admin_user_change_page_still_answers_a_superuser(api: Client) -> None:
    """The negative: refusing the password sub-view left the change page alone."""
    operator = create_user(email="pwnegative@example.com", password=PASSWORD, is_staff=True)
    operator.is_superuser = True
    operator.save(update_fields=["is_superuser"])
    api.force_login(operator)

    assert api.get(f"/admin/accounts/user/{operator.pk}/change/").status_code == 200
