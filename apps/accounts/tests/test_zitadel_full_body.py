"""Every Zitadel `PUT` this product sends carries the resource's FULL field set.

**One shape, three sightings.** Zitadel's management and admin `PUT`s are
REPLACES, not merges: a body that omits a field sets that field to its zero
value. `ensure_label_policy` sent six of the label policy's eleven keys, so
`hideLoginNameSuffix`, `themeMode`, `warnColor`, `warnColorDark` and
`primaryColorDark` were wiped on every branding sync;
`ensure_oidc_identity_provider` omitted `usePkce`, so every SSO sync switched
off a PKCE somebody had enabled in the console; and the sibling
platform's login-policy writer is the same class again. None of the three was
visible from inside the product, because each writer's own no-op check and
`zitadel_audit` both read only the keys the writer had sent.

**So this module is the convention's instrument.** `zitadel.PUT_FIELD_SETS`
declares, per resource, the full field set read out of the API the pinned build
serves; this census drives every writer in that population and asserts, for
every `PUT` it sent, that the body's key set is **equal** to the declaration. A
strict subset fails by name, saying which writer and which keys are missing —
which is the shape the future `rules.yaml` check will take, reading the same
constants.

**Closed question over a discoverable population.** The census does not assert
about the writers it happens to know: it asserts that every member of
`PUT_FIELD_SETS` was reached by a drive in this module (`test_every_declared_
resource_is_driven`), so a writer added with a declaration and no drive fails
here rather than going quietly unmeasured — and a `PUT` to a path with **no**
declaration fails too, because an undeclared writer is exactly the one nobody
would notice.

Nothing here dials Zitadel. `FakeZitadel` is the socket, as in every other
identity test; the surfaces this module drives that the shared fake does not
route are routed here, following the precedent
`test_zitadel_console_surfaces.py` and `test_identity_branding.py` set for the
same reason: a shared fixture object is every identity test's, and these
surfaces are this module's subject.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from apps.accounts import zitadel
from apps.accounts.tests.conftest import FakeZitadel

pytestmark = pytest.mark.django_db

# An org that HAS a label policy of its own, as the pinned build answers it —
# the same eleven-key shape `test_identity_branding.py` measured, minus the
# booleans, because proto3 omits its zero values and a fake that sent `false`
# would let a reader keying on presence pass here and fail against the real API.
ORG_OWN_LABEL_POLICY: dict[str, Any] = {
    "primaryColor": "#3f4a5a",
    "primaryColorDark": "#2073c4",
    "backgroundColor": "#fafafa",
    "backgroundColorDark": "#111827",
    "warnColor": "#cd3d56",
    "warnColorDark": "#ff3b5b",
    "fontColor": "#000000",
    "fontColorDark": "#ffffff",
    "themeMode": "THEME_MODE_AUTO",
    "details": {"resourceOwner": "387613333072707590", "sequence": "25"},
}

# An org that HAS a login policy of its own, MEASURED off the running v4.17.1
# stack on 2026-09-07 (`GET /management/v1/policies/login`): no `isDefault`, the
# resourceOwner is the org, `allowRegister` is ABSENT — and the five lifetimes
# and both factor lists are there, which is the half a partial PUT would zero.
ORG_OWN_LOGIN_POLICY: dict[str, Any] = {
    "details": {"sequence": "73", "resourceOwner": "387613333072707590"},
    "allowUsernamePassword": True,
    "allowExternalIdp": True,
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
    "ignoreUnknownUsernames": True,
    # The lifetime below is a protobuf Duration (10 days), not a credential;
    # detect-secrets keys on the word in the field name, so it is allowlisted.
    "passwordCheckLifetime": "864000s",  # pragma: allowlist secret
    "externalLoginCheckLifetime": "864000s",
    "mfaInitSkipLifetime": "0s",
    "secondFactorCheckLifetime": "64800s",
    "multiFactorCheckLifetime": "43200s",
    "secondFactors": ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"],
    "allowDomainDiscovery": True,
    "disableLoginWithPhone": True,
}


class Surfaces:
    """The PUT-shaped surfaces the shared fake does not route, as state.

    A holder rather than loose dicts so a drive can put a surface INTO a state —
    "this org has its own label policy" is the state in which the label writer
    takes its `PUT` branch at all, and a census that only ever reached the
    `POST` branch would be green while proving nothing about the `PUT`s it
    exists to judge.
    """

    def __init__(self) -> None:
        self.label: dict[str, Any] = dict(ORG_OWN_LABEL_POLICY)
        self.org_login: dict[str, Any] = dict(ORG_OWN_LOGIN_POLICY)


@pytest.fixture
def surfaces(instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch) -> Surfaces:
    """`FakeZitadel` plus the two ORG-scoped surfaces this census drives.

    The instance's three (`/admin/v1/policies/login`, `.../policies/lockout`,
    `/admin/v1/restrictions`) come from the shared fake, because `zitadel_seed`
    writes them on every run and three modules need the same socket. These two
    are org-scoped and this module is the only place that drives their `PUT`s.
    """
    held = Surfaces()
    # The three instance surfaces back in the state a NEWLY CREATED Zitadel is
    # in, because that is the state in which each writer takes its `PUT` branch
    # at all. `conftest.py`'s `instance` fixture closes them so that every other
    # identity test's audit is about its own subject; a census run against a
    # closed instance would send no `PUT`s and judge nothing — green, and empty.
    instance.instance_login_policy["allowRegister"] = True
    instance.lockout_policy.pop("maxPasswordAttempts", None)
    instance.restrictions.pop("disallowPublicOrgRegistration", None)
    # And the machine credential back to the state `scripts/setup.sh` leaves
    # it in — `IAM_OWNER` and no login-client role — because that is the state
    # in which its writer takes the `PUT` branch at all. The shared fixture
    # grants the role so that every identity test about something else agrees;
    # a census run against an already-granted credential would send no `PUT`
    # and judge nothing.
    instance.instance_members[str(instance.machine["id"])] = ["IAM_OWNER"]
    original: Callable[[str, str, dict[str, Any]], dict[str, Any]] = instance._route

    def routed(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "/policies/label":
            if method == "GET":
                return {"policy": held.label}
            if method == "PUT":
                held.label = {**body, "details": held.label["details"]}
                return {}
        if method == "POST" and path == "/policies/label/_activate":
            return {}
        if path == "/policies/login":
            if method == "GET":
                return {"policy": held.org_login}
            if method == "PUT":
                held.org_login = {
                    **{key: value for key, value in body.items() if value not in (False, "")},
                    "details": held.org_login["details"],
                }
                return {}
        return original(method, path, body)

    monkeypatch.setattr(instance, "_route", routed)
    return held


# --- the drives: one per declared resource -----------------------------------
#
# Each puts its surface in the state where the writer takes its `PUT` branch,
# and returns nothing: what the census reads is `instance.bodies`, the fake's
# log of every request and its body.


def _drive_label_policy(instance: FakeZitadel) -> None:
    zitadel.ensure_label_policy(
        accent="#123456",
        background_color="#fafafa",
        font_color="#000000",
        background_color_dark="#111827",
        font_color_dark="#ffffff",
    )


def _drive_oidc_identity_provider(instance: FakeZitadel) -> None:
    made = zitadel.ensure_oidc_identity_provider(
        name="acme:1",
        issuer="https://idp.acme.example",
        client_id="acme-client",
        client_secret="acme-secret",  # pragma: allowlist secret
    )
    # The second call is the one that PUTs: the first had no provider to update
    # and took the create branch.
    zitadel.ensure_oidc_identity_provider(
        name="acme:1",
        issuer="https://idp.acme.example",
        client_id="acme-client",
        client_secret="acme-secret",  # pragma: allowlist secret
        existing_id=made.id,
    )


def _drive_google_identity_provider(instance: FakeZitadel) -> None:
    made = zitadel.ensure_google_identity_provider(
        name="Workforce Google",
        client_id="google-client",
        client_secret="google-secret",  # pragma: allowlist secret
    )
    zitadel.ensure_google_identity_provider(
        name="Workforce Google",
        client_id="google-client",
        client_secret="google-secret",  # pragma: allowlist secret
        existing_id=made.id,
    )


def _drive_login_policy(instance: FakeZitadel) -> None:
    # The instance's own policy AND an org's, because the two surfaces share one
    # declaration and a census that drove only one would let the other drift.
    zitadel.ensure_login_policy(allow_register=False)
    # `True` on the org, deliberately: the measured org policy already has
    # `allowRegister` absent, so asking for `False` there would be a no-op and
    # this drive would prove nothing about the management surface's body.
    zitadel.ensure_login_policy(allow_register=True, prefix=zitadel.MANAGEMENT)


def _drive_lockout_policy(instance: FakeZitadel) -> None:
    zitadel.ensure_lockout_policy(max_password_attempts=100)


def _drive_restrictions(instance: FakeZitadel) -> None:
    zitadel.ensure_restrictions(is_public_org_registration_disallowed=True)


def _drive_oidc_app_config(instance: FakeZitadel) -> None:
    """The browser client, created and then RECONCILED onto a new origin.

    The second call is the one that `PUT`s: the first had no application to
    update and took the create branch, which is the same two-step every IdP
    drive above uses. The origin moves, because a reconcile with nothing to
    reconcile sends no body at all — which is the writer's idempotence and
    would make this drive prove nothing.
    """
    project = zitadel.ensure_project(name="Pilecap")
    zitadel.ensure_web_application(
        project_id=project.id,
        name="Web",
        redirect_uris=["http://localhost:8000/accounts/oidc/zitadel/login/callback/"],
        post_logout_uris=["http://localhost:8000/"],
        dev_mode=True,
    )
    zitadel.ensure_web_application(
        project_id=project.id,
        name="Web",
        redirect_uris=["http://localhost:9000/accounts/oidc/zitadel/login/callback/"],
        post_logout_uris=["http://localhost:9000/"],
        dev_mode=True,
    )


def _drive_iam_member(instance: FakeZitadel) -> None:
    """The machine credential, granted the role the login-v2 finalize needs.

    The credential is already an `IAM_OWNER` — every deployment's is — so this
    writer takes the `PUT` branch on its first call rather than on its second,
    unlike every drive above: `POST /admin/v1/members` is the create path and
    it is reached only by a user who holds no instance role at all.

    This is the smallest declared field set in the module and the one with the
    largest blast radius: a body naming only `IAM_LOGIN_CLIENT` takes
    `IAM_OWNER` off the user every other call in `zitadel.py` authenticates as,
    and the next run would fail on its first management call with nothing left
    that could grant it back.
    """
    zitadel.ensure_instance_member_role(
        user_id=str(instance.machine["id"]), role=zitadel.LOGIN_CLIENT_ROLE
    )


#: Every declared resource, and the drive that makes its writer send a `PUT`.
#: The census asserts this covers `zitadel.PUT_FIELD_SETS` exactly, so the
#: population is discoverable rather than remembered.
DRIVES: dict[str, Callable[[FakeZitadel], None]] = {
    "/policies/login": _drive_login_policy,
    "/policies/password/lockout": _drive_lockout_policy,
    "/restrictions": _drive_restrictions,
    "/policies/label": _drive_label_policy,
    "/idps/generic_oidc/{id}": _drive_oidc_identity_provider,
    "/idps/google/{id}": _drive_google_identity_provider,
    "/projects/{id}/apps/{id}/oidc_config": _drive_oidc_app_config,
    "/members/{id}": _drive_iam_member,
}


def _puts(instance: FakeZitadel) -> list[tuple[str, dict[str, Any]]]:
    """Every `PUT` the fake recorded, as (path, body)."""
    return [(path, body) for method, path, body in instance.bodies if method == "PUT"]


# --- the census --------------------------------------------------------------


def test_every_declared_resource_is_driven() -> None:
    """The population is closed: a declaration with no drive is a failure here.

    Without this the census is only as wide as whoever last remembered to add a
    drive — the masking shape a floor written as `>= 1` has, where one member
    can go blind while the count stays green.
    """
    assert set(DRIVES) == set(zitadel.PUT_FIELD_SETS), (
        "every resource declared in zitadel.PUT_FIELD_SETS needs a drive here, "
        "and every drive needs a declaration: "
        f"declared-not-driven {sorted(set(zitadel.PUT_FIELD_SETS) - set(DRIVES))}, "
        f"driven-not-declared {sorted(set(DRIVES) - set(zitadel.PUT_FIELD_SETS))}"
    )


@pytest.mark.parametrize("resource", sorted(DRIVES))
def test_the_writer_sends_the_resources_full_field_set(
    resource: str, surfaces: Surfaces, instance: FakeZitadel
) -> None:
    """The convention, as one assertion per resource: `set(body) == FIELDS`.

    Equality rather than containment in both directions. A strict SUBSET is the
    bug this exists for — Zitadel zeroes what the body omits. A strict SUPERSET
    is a body carrying a key the resource does not have, which Zitadel ignores
    silently, so a writer sending one is a writer whose author believed
    something the API does not do.
    """
    instance.bodies.clear()
    DRIVES[resource](instance)

    expected = zitadel.PUT_FIELD_SETS[resource]
    sent = [
        (path, body) for path, body in _puts(instance) if zitadel.put_field_set(path) is expected
    ]
    assert sent, f"the drive for {resource} sent no PUT — it cannot judge the body it never saw"
    for path, body in sent:
        missing = sorted(expected - set(body))
        extra = sorted(set(body) - expected)
        assert not missing and not extra, (
            f"PUT {path} does not send {resource}'s full field set — "
            f"missing {missing}, unexpected {extra}. Zitadel's PUT is a REPLACE: "
            "every field this body omits is zeroed on the live resource."
        )


def test_no_put_goes_to_an_undeclared_resource(surfaces: Surfaces, instance: FakeZitadel) -> None:
    """A `PUT` this population does not know about is the one nobody would catch.

    The census's own blind spot, closed: a writer added without a declaration
    would otherwise send whatever it liked and every assertion above would stay
    green, because they only ever look at the resources that ARE declared.
    """
    instance.bodies.clear()
    for drive in DRIVES.values():
        drive(instance)

    undeclared = [path for path, _ in _puts(instance) if zitadel.put_field_set(path) is None]
    assert not undeclared, (
        f"these PUTs go to resources with no declared field set: {sorted(set(undeclared))}. "
        "Declare the resource's full field set in zitadel.PUT_FIELD_SETS, read out "
        "of the API the pinned build serves, and add a drive to DRIVES here."
    )
