"""`manage.py revoke_token` — the shell door that was missing, and its refusals.

Three things are under test here and they are not the same thing:

1. **The revocation happens through the service**, so the row moves and the
   socket kick the REST door gets is the one the shell door gets (house rule
   10). Nothing here writes to `ApiToken` and neither does the command.
2. **Revocation is effective at the door.** Not "the column changed" —
   `test_a_revoked_token_is_refused_at_the_door` mints a bearer, uses it over
   the wire, revokes it *from the shell*, and drives the same request again for
   a `401`. A column is a hypothesis; a `401` is the property.
3. **No refusal is silent.** Every way this command can decline is driven, and
   each assertion reads the message for the fact it must name:
   a refusal that prints nothing and exits 0 is indistinguishable from success
   to the script and to the person, and the person then believes a live
   credential is dead.

`call_command` raises `CommandError` rather than exiting, so "exits non-zero" is
tested as "raises `CommandError`" — Django's `execute_from_command_line` turns
one into the other, and `test_the_refusals_reach_a_real_shell_non_zero` drives
the real `manage.py` path once to hold that mapping honest.
"""

from __future__ import annotations

import subprocess
import sys
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client

from apps.accounts.models import ApiToken, User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.exceptions import Invalid
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

#: The command's own source, addressed from this file rather than from the
#: working directory, so the rule-10 read below says the same thing whatever
#: pytest was invoked from.
COMMAND_FILE = Path(__file__).resolve().parents[1] / "management" / "commands" / "revoke_token.py"

#: The repository root, for the one test that drives `manage.py` as a shell
#: would. Same reasoning: `subprocess` inherits a working directory, and a test
#: that depends on which one is a test nobody can move.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(**options: object) -> str:
    out = StringIO()
    call_command("revoke_token", stdout=out, **options)
    return out.getvalue()


def _mint(user: User, tenant: Tenant | None, name: str) -> tuple[ApiToken, str]:
    return issue_token(
        user=user, tenant=tenant, name=name, scopes=["*"], actor=actor_for(user=user, tenant=tenant)
    )


def _value(printed: str, label: str) -> str:
    """The value on the `label:` line, or `""` when the command printed none."""
    for line in printed.splitlines():
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


# --- the door works ----------------------------------------------------------


def test_it_revokes_by_user_and_name(tenant: Tenant, owner: User) -> None:
    token, _ = _mint(owner, tenant, "load1b-drive")

    printed = _run(user=owner.email, name="load1b-drive")

    token.refresh_from_db()
    assert token.revoked_at is not None
    assert _value(printed, "revoked") == str(token.pk)
    assert _value(printed, "name") == "load1b-drive"
    assert _value(printed, "revoked at") == token.revoked_at.isoformat()


def test_it_revokes_by_id(tenant: Tenant, owner: User) -> None:
    token, _ = _mint(owner, tenant, "boot1-door-225257")

    printed = _run(token_id=str(token.pk))

    token.refresh_from_db()
    assert token.revoked_at is not None
    assert _value(printed, "revoked") == str(token.pk)
    assert _value(printed, "user") == owner.email


def test_it_revokes_an_unpinned_token_and_says_so(owner: User) -> None:
    """A token with no tenant is revocable and the output does not pretend it has one."""
    token, _ = _mint(owner, None, "unpinned")

    printed = _run(token_id=str(token.pk))

    token.refresh_from_db()
    assert token.revoked_at is not None
    assert _value(printed, "tenant") == "(per request)"


def test_it_revokes_a_token_belonging_to_someone_else(
    tenant: Tenant, owner: User, stranger: User, other_tenant: Tenant
) -> None:
    """The whole reason the command exists: no session as the minting user.

    The REST route is self-only by design. This one addresses any row, which is
    what an operator holding a shell and a ledger of stray token ids needs.
    """
    theirs, _ = _mint(stranger, other_tenant, "stray")

    _run(user=stranger.email, name="stray")

    theirs.refresh_from_db()
    assert theirs.revoked_at is not None


def test_the_command_writes_nothing_itself(tenant: Tenant, owner: User) -> None:
    """House rule 10, read off the module rather than asserted about behaviour.

    The command's only write is `services.revoke_token`; it imports that and no
    model-writing verb. A future edit that reached for `.save()` or `.update()`
    fails here before it fails in review.
    """
    source = COMMAND_FILE.read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # past the module docstring
    for forbidden in (".save(", ".delete(", ".create(", ".update("):
        assert forbidden not in body, f"the command writes directly: {forbidden}"


# --- revocation is effective AT THE DOOR -------------------------------------


def test_a_revoked_token_is_refused_at_the_door(
    api: Client, tenant: Tenant, owner: User, other_tenant: Tenant, stranger: User
) -> None:
    """Mint, use over the wire, revoke from the shell, use again: `200` then `401`.

    `GET /api/v1/auth/sso-connections/` is this app's own authenticated read, so
    the probe names no other app's URL. It is a `GET`, so it is repeatable and
    changes nothing between the two halves — the only variable is the token.
    """
    _, plaintext = _mint(owner, tenant, "wire")
    bearer = {"Authorization": f"Bearer {plaintext}"}

    live = api.get("/api/v1/auth/sso-connections/", headers=bearer)
    assert live.status_code == 200, live.content

    _run(user=owner.email, name="wire")

    dead = api.get("/api/v1/auth/sso-connections/", headers=bearer)
    assert dead.status_code == 401, dead.content


# --- no refusal is silent ----------------------------------------------------


def test_it_refuses_an_unknown_user(tenant: Tenant, owner: User) -> None:
    with pytest.raises(CommandError, match="No user with email nobody@example.com"):
        _run(user="nobody@example.com", name="whatever")


def test_it_refuses_an_unknown_name_and_lists_what_they_do_have(
    tenant: Tenant, owner: User
) -> None:
    live, _ = _mint(owner, tenant, "boot1-alpha")
    _mint(owner, tenant, "boot1-beta")

    with pytest.raises(CommandError) as refusal:
        _run(user=owner.email, name="boot1")

    said = str(refusal.value)
    assert "has no token named 'boot1'" in said
    assert "'boot1-alpha'" in said and "'boot1-beta'" in said
    live.refresh_from_db()
    assert live.revoked_at is None


def test_the_catalogue_says_so_when_there_is_nothing_to_list(tenant: Tenant, owner: User) -> None:
    with pytest.raises(CommandError, match="They hold no live tokens"):
        _run(user=owner.email, name="anything")


def test_it_refuses_an_unknown_id(tenant: Tenant, owner: User) -> None:
    missing = uuid4()
    with pytest.raises(CommandError, match=f"No token with id {missing}"):
        _run(token_id=str(missing))


def test_it_refuses_something_that_is_not_an_id(tenant: Tenant, owner: User) -> None:
    with pytest.raises(CommandError, match="is not a token id"):
        _run(token_id="boot1-door-225257")


def test_it_refuses_an_already_revoked_token_without_moving_the_timestamp(
    tenant: Tenant, owner: User
) -> None:
    """The audit fact stays where it was. The bare service would overwrite it."""
    token, _ = _mint(owner, tenant, "twice")
    _run(user=owner.email, name="twice")
    token.refresh_from_db()
    first = token.revoked_at
    assert first is not None

    with pytest.raises(CommandError) as refusal:
        _run(user=owner.email, name="twice")

    assert "already revoked at" in str(refusal.value)
    assert first.isoformat() in str(refusal.value)
    token.refresh_from_db()
    assert token.revoked_at == first


def test_it_refuses_a_tenant_the_token_is_not_pinned_to(
    tenant: Tenant, owner: User, other_tenant: Tenant
) -> None:
    token, _ = _mint(owner, tenant, "pinned")

    with pytest.raises(CommandError) as refusal:
        _run(user=owner.email, name="pinned", tenant=other_tenant.slug)

    said = str(refusal.value)
    assert tenant.slug in said and other_tenant.slug in said
    token.refresh_from_db()
    assert token.revoked_at is None


def test_it_accepts_the_tenant_it_is_pinned_to(tenant: Tenant, owner: User) -> None:
    token, _ = _mint(owner, tenant, "confirmed")

    _run(user=owner.email, name="confirmed", tenant=tenant.slug)

    token.refresh_from_db()
    assert token.revoked_at is not None


def test_it_refuses_a_tenant_slug_that_does_not_exist(tenant: Tenant, owner: User) -> None:
    token, _ = _mint(owner, tenant, "guarded")

    with pytest.raises(CommandError, match="No tenant with slug not-a-tenant"):
        _run(user=owner.email, name="guarded", tenant="not-a-tenant")

    token.refresh_from_db()
    assert token.revoked_at is None


def test_it_refuses_when_nothing_names_a_token(tenant: Tenant, owner: User) -> None:
    with pytest.raises(CommandError, match="Name the token to revoke"):
        _run()


def test_it_refuses_a_half_address(tenant: Tenant, owner: User) -> None:
    with pytest.raises(CommandError, match="--name is missing"):
        _run(user=owner.email)
    with pytest.raises(CommandError, match="--user is missing"):
        _run(name="laptop")


def test_it_refuses_two_addresses_at_once(tenant: Tenant, owner: User) -> None:
    token, _ = _mint(owner, tenant, "both")
    with pytest.raises(CommandError, match="--id names a token on its own"):
        _run(token_id=str(token.pk), user=owner.email, name="both")
    token.refresh_from_db()
    assert token.revoked_at is None


# --- the ambiguity the criteria anticipated cannot exist ---------------------


def test_a_user_and_a_name_can_only_ever_mean_one_row(tenant: Tenant, owner: User) -> None:
    """Why there is no "several candidates" refusal to test.

    The criteria asked for one — two live tokens matching `--user` + `--name`,
    refused with the candidates listed. That state is unreachable, and it is
    refused twice over: `issue_token` runs `full_clean()` and answers the
    domain's `Invalid`, and underneath it `ApiToken.Meta.constraints` carries
    `apitoken_unique_name_per_user`, so a row that reached the database another
    way is refused there too.

    Both halves are pinned, because they fail differently: drop the constraint
    and the second assertion goes; drop the `full_clean()` and the first does.
    Either way the missing "several candidates" refusal fails here by name,
    rather than by an operator revoking whichever row came back first.
    """
    first, _ = _mint(owner, tenant, "only-one")

    with pytest.raises(Invalid):
        _mint(owner, tenant, "only-one")

    with pytest.raises(IntegrityError), transaction.atomic():
        ApiToken.objects.create(
            user=owner,
            tenant=tenant,
            name="only-one",
            key_hash="0" * 64,  # pragma: allowlist secret - not a key, a filler
        )

    assert ApiToken.objects.filter(user=owner, name="only-one").count() == 1
    assert ApiToken.objects.get(user=owner, name="only-one").pk == first.pk


# --- and the refusal really is non-zero out of a real shell ------------------


def test_the_refusals_reach_a_real_shell_non_zero() -> None:
    """`CommandError` becomes a non-empty stderr and a non-zero status.

    `call_command` raises; a shell does not. This drives `manage.py` in a
    subprocess once so the whole file's "raises `CommandError`" assertions mean
    what the operator's exit status will mean. It names no row and touches no
    database — an unparseable id is refused during resolution, before any read.
    """
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "manage.py", "revoke_token", "--id", "not-a-uuid"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert done.returncode != 0
    assert "is not a token id" in done.stderr
    assert done.stdout.strip() == ""
