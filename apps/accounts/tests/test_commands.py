"""`manage.py issue_token` — the same door, for someone with a shell."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import ApiToken, User
from apps.accounts.services import authenticate_token
from apps.core.api.scopes import effective_scopes
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


def _run(**options: object) -> str:
    out = StringIO()
    call_command("issue_token", stdout=out, **options)
    return out.getvalue()


def test_it_prints_a_token_that_works(tenant: Tenant, owner: User) -> None:
    printed = _run(email=owner.email, tenant=tenant.slug, name="laptop", scopes=["*"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[0] == owner
    assert resolved[1] == tenant

    token = ApiToken.objects.get(name="laptop")
    assert token.tenant_id == tenant.pk
    assert plaintext not in token.key_hash


def test_without_a_tenant_the_token_resolves_one_per_request(tenant: Tenant, owner: User) -> None:
    printed = _run(email=owner.email, name="unpinned", scopes=["*"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))
    assert ApiToken.objects.get(name="unpinned").tenant_id is None
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[1] == tenant


def test_it_refuses_an_unknown_user(tenant: Tenant) -> None:
    with pytest.raises(CommandError):
        _run(email="nobody@example.com", tenant=tenant.slug, name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


def test_it_refuses_an_unknown_tenant(owner: User) -> None:
    with pytest.raises(CommandError):
        _run(email=owner.email, tenant="not-a-tenant", name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


def test_it_refuses_a_tenant_the_user_does_not_belong_to(owner: User, other_tenant: Tenant) -> None:
    """The command cannot mint what the doors would refuse to honour."""
    with pytest.raises(CommandError):
        _run(email=owner.email, tenant=other_tenant.slug, name="x", scopes=["*"])
    assert ApiToken.objects.count() == 0


# --- the two lines about reach, and the one that used to lie ------------


def _line(printed: str, label: str) -> str:
    """The value on the `label:` line, or `""` when the command printed none."""
    for line in printed.splitlines():
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


def test_an_ordinary_write_mint_says_nothing_is_wrong(tenant: Tenant, owner: User) -> None:
    """The warning fired on every `:write` mint, naming nothing.

    The check was `set(usable) != set(token.scopes)`, and those two sets differ
    by design on any write mint: asking for `widgets:write` carries
    `widgets:read`, so `usable` is legitimately *larger*. The sentence was then
    built from `set(token.scopes) - set(usable)`, which is empty — so the shell
    printed "role cannot back  today" with a hole where the list should be, on a
    mint with nothing at all wrong with it.

    An owner can back both halves, so there is nothing to warn about and the
    command says nothing. That is the property: silence when it is fine.
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="agent", scopes=["widgets:write"])
    assert "note:" not in printed, printed
    assert "cannot back" not in printed, printed


def test_the_note_still_fires_and_names_the_dead_scope(tenant: Tenant, member: User) -> None:
    """And it did not stop warning — a member asking to write cannot, and is told.

    The sibling of the test above, and the reason the fix is not "delete the
    warning": this is the case it exists for. Writing needs an administrator
    under the default rule, so a plain member's `org-structure:write` is dead
    weight the moment the token is minted, and the list in the sentence is not
    empty.
    """
    printed = _run(
        email=member.email, tenant=tenant.slug, name="agent", scopes=["org-structure:write"]
    )
    assert "org-structure:write" in _line(printed, "note")


def test_the_shell_shows_the_expansion_the_wire_has_always_shown(
    tenant: Tenant, owner: User
) -> None:
    """`effective:` — the same echo `POST /tokens/` returns.

    The expansion is the fact that shrank a field test's list from twelve scopes
    to six: within a section the write scope carries the read, so an operator
    who asks for six write scopes has handed over twelve. The HTTP mint has
    echoed that since ADR ident-7; the shell — the door somebody setting a
    machine up actually stands at — printed only what was asked for.

    Asserted against `effective_scopes` itself rather than against a literal
    pair, so this test says "the shell prints the derivation" and cannot come to
    mean "the shell prints these two words".
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="agent", scopes=["widgets:write"])
    expected = effective_scopes(user=owner, tenant=tenant, scopes=["widgets:write"])
    assert expected is not None
    assert _line(printed, "effective") == ", ".join(expected)
    assert _line(printed, "scopes") == "widgets:write"


def test_an_unlimited_token_says_so_on_both_lines(tenant: Tenant, owner: User) -> None:
    """`--scope '*'` stores no ceiling, so there is nothing to expand or to trim.

    The line still prints. A missing one reads as "we did not work it out",
    which is not what happened.
    """
    printed = _run(email=owner.email, tenant=tenant.slug, name="wide", scopes=["*"])
    assert _line(printed, "scopes") == "(no limit)"
    assert _line(printed, "effective") == "(no limit)"
    assert "note:" not in printed


# --- the alarm that fired on every unpinned mint -----------------------

PER_REQUEST = "(per request — resolved at the door)"


def test_an_unpinned_mint_says_where_the_reach_is_worked_out(owner: User) -> None:
    """No `--tenant` means no role here to work a set out against.

    `effective_scopes` is derived from the role this person holds *in the
    token's tenant*. An unpinned token has no tenant at the mint — it resolves
    one per request, at the door, from whichever membership the request lands
    on — so the mint was asking a question it could not have an answer to, and
    `effective_scopes(user, tenant=None, ...)` obliged: no membership found,
    rank zero, the empty set. That is an answer about what the *command* does
    not know, and it was printed as an answer about what the *person* cannot
    do, under a `note:` naming every scope asked for.

    The red, on this very fixture: `owner` is an OWNER of `acme` — the role
    that backs everything there is — and the shell told them their role backs
    nothing, on a token that then authenticated, resolved `acme`, and carried
    exactly the scope they asked for. The alarm did not fire for `owner` in
    particular; it fired for *everybody*, on every unpinned mint with a
    ceiling, which is the whole of the defect: a warning that fires when
    nothing is wrong is a warning nobody reads the day something is.
    """
    printed = _run(email=owner.email, name="unpinned-reach", scopes=["widgets:read"])

    assert _line(printed, "tenant") == "(per request)"
    assert _line(printed, "effective") == PER_REQUEST
    assert "note:" not in printed, printed
    assert "cannot back" not in printed, printed
    assert "(nothing this role can back today)" not in printed, printed


def test_the_unpinned_token_the_mint_kept_quiet_about_actually_works(
    tenant: Tenant, owner: User
) -> None:
    """The other half: the token the false alarm was about is fine.

    A warning is only wrong if the thing it warns about is not true, so this is
    the test that makes the one above a defect report rather than a preference.
    The same mint, taken to the door: the token authenticates, the door resolves
    the tenant the mint declined to guess, and the scope the shell called dead
    is live against the role the door found.
    """
    printed = _run(email=owner.email, name="unpinned-works", scopes=["widgets:read"])
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved.tenant == tenant
    at_the_door = effective_scopes(
        user=resolved.user, tenant=resolved.tenant, scopes=resolved.token.scopes
    )
    assert at_the_door == ["widgets:read"]


def test_the_unpinned_line_does_not_depend_on_who_is_minting(nomad: User) -> None:
    """And it says the same thing for somebody who belongs nowhere — deliberately.

    `nomad` holds no membership at all, so their unpinned token really will find
    no tenant at the door. The mint still cannot say so: it does not know which
    request this token will arrive on, and "this person belongs nowhere" is a
    fact about the person that the *door* discovers, not one the mint may
    announce from an empty query. The line is about where the answer comes from,
    so it is the same line for everyone — which is exactly what stops it drifting
    back into a claim about a role.
    """
    printed = _run(email=nomad.email, name="hopeful", scopes=["widgets:read"])
    assert _line(printed, "effective") == PER_REQUEST
    assert "note:" not in printed, printed


def test_an_unpinned_unlimited_mint_still_says_no_limit(owner: User) -> None:
    """`--scope '*'` is outside the fix, and stays outside it.

    A token with no ceiling has nothing to expand and nothing to trim, so
    "(no limit)" is the whole truth whether a tenant was named or not. Pinned
    here because the tempting fix — branch on `tenant is None` and be done —
    would have replaced a complete answer with a vaguer one on this path.
    """
    printed = _run(email=owner.email, name="unpinned-wide", scopes=["*"])
    assert _line(printed, "scopes") == "(no limit)"
    assert _line(printed, "effective") == "(no limit)"
    assert "note:" not in printed


def test_naming_the_tenant_is_what_turns_the_computed_answer_on(
    tenant: Tenant, member: User
) -> None:
    """The contrast the rung is about, one person and one scope, both ways.

    With `--tenant` nothing changed: the set is computed from the role, and the
    `note:` still names what that role cannot back — this is `member` asking to
    write, the case the warning exists for. Without it, the same request gets
    the line that says where the answer is worked out, and no warning, because
    nothing was worked out to warn about.
    """
    pinned = _run(
        email=member.email, tenant=tenant.slug, name="pinned", scopes=["org-structure:write"]
    )
    unpinned = _run(email=member.email, name="not-pinned", scopes=["org-structure:write"])

    assert _line(pinned, "effective") == "org-structure:read"
    assert "org-structure:write" in _line(pinned, "note")

    assert _line(unpinned, "effective") == PER_REQUEST
    assert "note:" not in unpinned, unpinned
