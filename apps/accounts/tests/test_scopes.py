"""The ceiling a bearer token carries (ADR ident-7), proved end to end.

Eight properties, one per criterion of the rung that built them, and they are
about behaviour a caller can see rather than about the machinery underneath:
the vocabulary is a census, the derivation is total over the real registry, the
door refuses before the service, a scope grants nothing, the two mint doors both
demand a choice, a token minted before any of this existed still works, and the
published document says which scope every operation needs.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings

import apps as apps_package
from apps.accounts.models import ApiToken, User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.api import docs, scopes
from apps.core.api.docs import llms_text
from apps.core.audit import AuditEntry
from apps.core.exceptions import Invalid
from apps.core.models import Membership, Organization, Tenant
from apps.core.tests.tree_census import source_text, source_tree, vanishing_source_file
from apps.example.models import Widget
from config.api import api as the_api

WIDGETS = "/api/v1/widgets/"
TOKENS = "/api/v1/tokens/"
MEMBERSHIPS = "/api/v1/memberships/"


def _bearer(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _body(response: Any) -> Any:
    return json.loads(response.content)


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    """Every operation in the published document: (method, path, operation)."""
    document = the_api.get_openapi_schema()
    return [
        (method, path, operation)
        for path, methods in document.get("paths", {}).items()
        for method, operation in methods.items()
        if isinstance(operation, dict)
    ]


# --- 1 · the column ------------------------------------------------------------


def test_the_ceiling_column_is_nullable_and_carries_no_ceiling_by_default() -> None:
    """Expand-only: an existing row gets a column whose empty value means what it did.

    A non-nullable column, or one with a default that is a list, would have
    rewritten what every token already minted is allowed to do — which is not
    something adding a column is allowed to decide.
    """
    field = ApiToken._meta.get_field("scopes")
    assert field.null is True
    assert field.blank is True
    assert field.default is None


# --- 2 · the vocabulary is a census -------------------------------------------


def test_the_vocabulary_is_every_section_crossed_with_read_and_write() -> None:
    """No hand list exists to diverge from: the two sides are computed apart.

    The families come from what the apps declare beside their routers; the
    document's own sections come from the mount's separate walk over the same
    declarations. Pinning them equal is what would catch a vocabulary that had
    quietly become a copy.
    """
    document_sections = {str(entry["name"]) for entry in the_api.get_openapi_schema()["tags"]}
    assert set(scopes.families()) == document_sections
    assert set(scopes.vocabulary()) == {
        f"{family}:{verb}" for family in document_sections for verb in ("read", "write")
    }


def test_a_hyphenated_section_is_a_scope_like_any_other() -> None:
    """`tenant-settings` is the one section whose key is not a single word.

    Every other family is, so a parser that split on the first separator, or
    that assumed one word per half, would have been right nine times out of ten
    and silently wrong about the tenth — which is the shape of defect nobody
    finds by reading.
    """
    assert "tenant-settings" in scopes.families()
    assert "tenant-settings:read" in scopes.vocabulary()
    assert scopes.parse_scope("tenant-settings:read") == ("tenant-settings", "read")
    assert scopes.parse_scope("tenant-settings:write") == ("tenant-settings", "write")
    assert scopes.within_ceiling(ceiling=["tenant-settings:read"], scope="tenant-settings:read")
    assert not scopes.within_ceiling(
        ceiling=["tenant-settings:read"], scope="tenant-settings:write"
    )


# --- the two verbs are levels, not flags (owner ruling, 2026-08-24) ------------


def test_a_write_scope_carries_its_own_sections_read() -> None:
    """The ruling, as the predicate every door asks.

    Nobody minting a token for an agent that files invoices should have to
    remember to ask for reading them as well — and the half that gets forgotten
    is the half that fails in the middle of the night. So the verbs are levels:
    a write carries its family's read.
    """
    assert scopes.within_ceiling(ceiling=["widgets:write"], scope="widgets:read")
    assert scopes.within_ceiling(ceiling=["widgets:write"], scope="widgets:write")
    assert scopes.granted_scopes(["widgets:write"]) == {"widgets:write", "widgets:read"}


def test_the_implication_runs_one_way_only() -> None:
    """A read scope is still a read scope, which is the whole point of halves."""
    assert not scopes.within_ceiling(ceiling=["widgets:read"], scope="widgets:write")
    assert scopes.granted_scopes(["widgets:read"]) == {"widgets:read"}


def test_the_implication_never_crosses_a_section() -> None:
    """`widgets:write` says nothing whatever about anybody else's section."""
    for scope in scopes.vocabulary():
        if scope.startswith("widgets:"):
            continue
        assert not scopes.within_ceiling(ceiling=["widgets:write"], scope=scope), scope


@pytest.fixture
def scratch_tagged_app(tmp_path: Path) -> Iterator[str]:
    """A brand-new app with a tagged router, and nothing else in the tree touched.

    Written into a directory that is added to the `apps` package's own search
    path rather than into the repository, so the plant leaves nothing behind:
    the claim under test is that declaring a tag is the whole of joining the
    vocabulary, and a fixture that had to edit a second file would be proving
    the opposite.
    """
    package = tmp_path / "scratchscopes"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\n"
        "class ScratchScopesConfig(AppConfig):\n"
        '    name = "apps.scratchscopes"\n'
        '    label = "scratchscopes"\n'
        '    depends_on = ("core",)\n'
    )
    (package / "api.py").write_text(
        "from ninja import Router\n\n"
        "from apps.accounts.auth import API_AUTH\n"
        "from apps.core.api.docs import Tag\n\n"
        'PREFIX = "doodads"\n'
        'TAGS = {"doodads": Tag("Doodads", "A section that did not exist yesterday.")}\n'
        'router = Router(tags=["doodads"], auth=API_AUTH)\n'
    )
    apps_package.__path__.append(str(tmp_path))
    installed = [*settings.INSTALLED_APPS, "apps.scratchscopes"]
    try:
        with override_settings(INSTALLED_APPS=installed):
            yield "doodads"
    finally:
        apps_package.__path__.remove(str(tmp_path))
        for name in [key for key in sys.modules if key.startswith("apps.scratchscopes")]:
            del sys.modules[name]


def test_a_new_app_grows_the_vocabulary_with_nothing_else_edited(
    scratch_tagged_app: str,
) -> None:
    """The census claim, planted: declaring the tag is the whole of joining."""
    assert scratch_tagged_app in scopes.families()
    assert f"{scratch_tagged_app}:read" in scopes.vocabulary()
    assert f"{scratch_tagged_app}:write" in scopes.vocabulary()


# --- 2b · the three-way split, and the day a key freezes -----------------------
# The owner's ruling of 2026-08-24 (`docs/product/design-agreements.md`, "the
# three-way scope split"). What shipped as ONE `organizations` family is three,
# because the persona seat could finally see the ceiling was too wide to be
# worth narrowing: `organizations:write` bought creating an org, granting a role
# and issuing an invitation in one string, so the narrowest token that did any
# of those jobs did all three. The keys are MEANING-NAMED — the exception, not
# the default (`django-conventions` §6 carries the choosing pattern) — because
# `memberships:write` on a credential travelling without its API is a string
# nobody can place, while `roles:write` maps one-to-one onto the role-based
# access-control vocabulary an ONC audit is read in.
#
# The paths did NOT move. Key is not path (the TAG-1 shape): `/organizations/`,
# `/memberships/` and `/invitations/` answer exactly as they did.


def test_the_one_membership_family_is_now_three_meaning_named_families() -> None:
    """The ruling, read off the live census rather than off a list kept here."""
    live = set(scopes.families())
    assert {"org-structure", "roles", "invitations"} <= live, sorted(live)
    assert "organizations" not in live, (
        "the retired family key is live again — a token minted before the split "
        "would be silently re-armed against a capability nobody granted it"
    )


def test_the_three_carry_the_display_names_the_owner_phrased() -> None:
    """A key is wire vocabulary and a display name is prose; both are declared."""
    published = {
        str(entry["name"]): str(entry.get("x-displayName") or "")
        for entry in the_api.get_openapi_schema()["tags"]
    }
    assert published["org-structure"] == "Organizational structure"
    assert published["roles"] == "Roles & members"
    assert published["invitations"] == "Invitations"


def test_the_split_moved_no_path() -> None:
    """The three resources answer where they always did — the key moved, not the URL."""
    paths = the_api.get_openapi_schema()["paths"]
    for path in ("/api/v1/organizations/", "/api/v1/memberships/", "/api/v1/invitations/"):
        assert path in paths, sorted(paths)


def test_each_of_the_three_bounds_its_own_operations_and_no_others() -> None:
    """The point of splitting, read off the published document rather than claimed.

    Every operation under each resource derives the family that resource belongs
    to, and nothing anywhere derives the retired key.
    """
    expected = {
        "/api/v1/organizations/": "org-structure",
        "/api/v1/memberships/": "roles",
        "/api/v1/invitations/": "invitations",
    }
    seen: dict[str, set[str]] = {family: set() for family in expected.values()}
    for method, path, operation in _operations():
        for prefix, family in expected.items():
            if path.startswith(prefix):
                derived = scopes.required_scope(
                    tags=list(operation.get("tags") or []), methods=[method]
                )
                assert derived.startswith(f"{family}:"), f"{method.upper()} {path} -> {derived}"
                seen[family].add(derived)
    for family, reached in seen.items():
        assert reached, f"nothing derived {family} — this test would pass vacuously"


def test_a_ceiling_on_one_of_the_three_reaches_none_of_the_others() -> None:
    """The narrowing the split exists to make possible, as the predicate."""
    for held, other in (
        ("org-structure", "roles"),
        ("roles", "invitations"),
        ("invitations", "org-structure"),
    ):
        assert scopes.within_ceiling(ceiling=[f"{held}:write"], scope=f"{held}:read")
        assert not scopes.within_ceiling(ceiling=[f"{held}:write"], scope=f"{other}:read")


def test_minting_with_the_retired_key_is_refused_and_told_its_successors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """No shim. The old string is refused — and the refusal is followable.

    A compatibility alias was rejected: an alias would make `organizations:write`
    go on granting all three capabilities forever, which is the ceiling the
    ruling exists to retire. What a refusal owes instead is the sentence that
    lets the next attempt be right, so it names all three successors rather than
    leaving somebody to guess which one their job needs.
    """
    api.force_login(owner)
    response = api.post(
        TOKENS,
        data=json.dumps({"name": "stale", "scopes": ["organizations:write"]}),
        content_type="application/json",
        headers={"x-tenant": tenant.slug},
    )
    assert response.status_code == 400, response.content
    said = json.dumps(_body(response))
    for successor in ("org-structure:write", "roles:write", "invitations:write"):
        assert successor in said, said
    assert not ApiToken.objects.filter(name="stale").exists()


def test_the_shell_door_refuses_the_retired_key_with_the_same_advice(
    tenant: Tenant, owner: User
) -> None:
    """One refusal, both mint doors — the browser and the shell cannot disagree."""
    with pytest.raises(CommandError) as refused:
        call_command(
            "issue_token",
            email=owner.email,
            tenant=tenant.slug,
            name="stale",
            scopes=["organizations:read"],
        )
    said = str(refused.value)
    for successor in ("org-structure:read", "roles:read", "invitations:read"):
        assert successor in said, said


def test_a_string_that_was_never_a_family_is_refused_without_rename_advice() -> None:
    """The advice is for a key that WAS ours. A typo gets the plain refusal."""
    with pytest.raises(Invalid) as refused:
        scopes.ceiling_from_request(["orgnaizations:read"])
    said = str(refused.value.detail)
    assert "orgnaizations:read" in said
    assert "renamed" not in said.lower(), said


# --- 2c · a family key freezes the day a token could name it -------------------
# The enforceable half of the same ruling. A family key is not a label: it is
# the string sitting in an `ApiToken.scopes` row on somebody else's machine, and
# renaming it kills that ceiling silently — the token goes on authenticating and
# starts being refused at every door, with nothing anywhere saying why.


def test_every_frozen_family_key_is_still_live() -> None:
    """The clean tree, and the instrument's own subject."""
    assert scopes.FROZEN_FAMILIES, "the census is empty — this test would pass vacuously"
    assert scopes.family_freeze_findings() == ()


def test_the_frozen_census_is_the_whole_live_vocabulary() -> None:
    """A family shipped and not written down is not yet frozen — so this is pinned.

    The census cannot be derived from the live families (that would make it a
    copy of the very thing it exists to remember), so what keeps it current is
    this test: a new family fails here, by name, in the commit that ships it.
    """
    assert set(scopes.FROZEN_FAMILIES) == set(scopes.families())


def test_a_frozen_key_that_vanished_is_refused_with_the_reason() -> None:
    """Planted: the live vocabulary loses a key a minted token may hold."""
    live = [family for family in scopes.families() if family != "roles"]
    findings = scopes.family_freeze_findings(live)
    assert findings, "the freeze said nothing about a key that disappeared"
    said = " ".join(findings)
    assert "roles:read" in said and "roles:write" in said, said
    assert "last cheap rename" in said.lower(), said


def test_the_retired_key_coming_back_is_refused_too() -> None:
    """Planted the other way: the old key live again is the same class of harm."""
    findings = scopes.family_freeze_findings([*scopes.families(), "organizations"])
    assert findings, "the freeze said nothing about a retired key returning"
    assert "organizations" in " ".join(findings)


def test_a_family_key_nobody_has_shipped_yet_is_free_to_arrive(
    scratch_tagged_app: str,
) -> None:
    """Growth is free; only a DEPARTURE is refused. Planted with the real app.

    The freeze must not become a hand list every new app has to be added to
    before it may have a door — that would undo the census this whole module
    exists to be.
    """
    assert scratch_tagged_app in scopes.families()
    assert scopes.family_freeze_findings() == ()


def test_the_three_renames_are_recorded_as_the_sanctioned_migration() -> None:
    """The one departure this tree has taken, written down with what it became."""
    assert scopes.SANCTIONED_RENAMES["organizations"] == (
        "org-structure",
        "roles",
        "invitations",
    )
    for successors in scopes.SANCTIONED_RENAMES.values():
        for successor in successors:
            assert successor in scopes.FROZEN_FAMILIES


# --- 3 · the derivation is total over the real registry ------------------------


def test_every_published_operation_derives_its_scope() -> None:
    """Walked over the document the deployment actually serves, not a fixture list.

    Total means total: an operation the walk cannot answer for raises rather
    than falling back, because a fallback would be a route standing outside
    every ceiling in the product with nothing ever saying so.
    """
    operations = _operations()
    assert operations, "the document has no operations, so this test cannot fail"
    for method, path, operation in operations:
        scope = scopes.required_scope(tags=operation["tags"], methods=[method])
        assert scope in scopes.vocabulary(), f"{method.upper()} {path} derived {scope!r}"
        parsed = scopes.parse_scope(scope)
        assert parsed is not None
        family, verb = parsed
        assert family == operation["tags"][0]
        assert verb == ("read" if method.upper() in {"GET", "HEAD"} else "write")


def test_the_method_decides_the_half() -> None:
    assert scopes.verb_class(["GET"]) == "read"
    assert scopes.verb_class(["HEAD"]) == "read"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert scopes.verb_class([method]) == "write"


def test_an_operation_with_no_single_tag_refuses_to_derive() -> None:
    """A broken declaration is a loud failure, never a permissive default."""
    with pytest.raises(scopes.UnderivableScope):
        scopes.required_scope(tags=[], methods=["GET"])
    with pytest.raises(scopes.UnderivableScope):
        scopes.required_scope(tags=["widgets", "runs"], methods=["GET"])


def test_the_rendering_path_shrugs_where_the_enforcement_seam_refuses() -> None:
    """The two callers of one derivation want opposite things, and both get them.

    A seam deciding a CALL must refuse what it cannot place: guessing would put
    a capability outside every ceiling in the product. A seam writing PROSE must
    not, because the document is also how the problem gets reported — house rule
    41's one-tag census reads the rendered document, so a document that could
    not be built reports nothing about the very route that broke it.

    This is a regression, not a hypothetical: rule 41's canary plants a two-tag
    route on purpose, and while rendering raised, the API died at import and two
    dozen unrelated canaries went silent at once.
    """
    assert docs.derived_scope(tags=["widgets"], methods=["GET"]) == "widgets:read"
    assert docs.derived_scope(tags=["widgets", "runs"], methods=["GET"]) is None
    assert docs.derived_scope(tags=[], methods=["GET"]) is None

    # And nothing is invented in its place: no sentence beats a wrong one.
    assert docs.with_required_scope("The prose.", None) == "The prose."
    assert "widgets:read" in docs.with_required_scope("The prose.", "widgets:read")


def test_a_two_tagged_operation_still_renders_into_the_document() -> None:
    """The whole document survives a route that derives nothing.

    Built the way `config/api.py` builds one — a router carrying two tags, bound
    to a throwaway API — so the assertion is about the rendering pass and not
    about a helper called in isolation. The operation is present, has its prose,
    and simply carries no scope line; rule 41 is then free to say the true thing
    about it.
    """
    from ninja import NinjaAPI, Router

    router = Router(tags=["zzz-one", "zzz-two"], auth=None)

    @router.get("/doodads/", url_name="doodad-list")
    def list_doodads(request: Any) -> list[str]:
        """List doodads

        Every doodad, for a test that needs a route carrying two tags.
        """
        return []

    scratch = NinjaAPI(title="scratch", version="scratch", urls_namespace="scratch-two-tags")
    scratch.add_router("/", router)

    for bound in scratch._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            for operation in path_view.operations:
                assert len(operation.tags or []) == 2
                rendered = docs.with_required_scope(
                    operation.description or "",
                    docs.derived_scope(tags=operation.tags or [], methods=operation.methods),
                )
                assert "doodad" in rendered.lower() or rendered == (operation.description or ""), (
                    path
                )
                assert "Token scope:" not in rendered


# --- 4 · the ceiling refuses at the door, before the service -------------------


@pytest.mark.django_db
def test_a_narrow_token_reads_and_is_refused_on_the_write(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The whole of the rung in one test, from a caller's seat.

    The refusal names the scope that was missing, because "no" without the name
    of what to ask for leaves the agent's human with nothing to act on; and the
    write leaves no trace at all, because the door turned it away before
    anything below it ran.
    """
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="narrow",
        scopes=["widgets:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    listed = api.get(WIDGETS, headers=_bearer(plaintext))
    assert listed.status_code == 200, listed.content

    refused = api.post(
        WIDGETS,
        data=json.dumps({"name": "Should not exist"}),
        content_type="application/json",
        headers=_bearer(plaintext),
    )
    assert refused.status_code == 403, refused.content
    body = _body(refused)
    assert body["code"] == "insufficient_scope"
    assert "widgets:write" in body["detail"]
    assert body["remedies"], "a refusal with no way out is a dead end with a status code"
    assert all(remedy["label"] and remedy["destination"] for remedy in body["remedies"])

    assert Widget.objects.count() == 0
    assert not AuditEntry.objects.filter(action="example.create_widget").exists()


@pytest.mark.django_db
def test_a_write_only_token_may_also_read_that_section_over_the_wire(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The owner's ruling, at the door a client actually meets.

    A token minted `widgets:write` and nothing else creates a widget AND lists
    them, because within one section the write carries the read. Asserted over
    the wire rather than on the predicate, because the predicate agreeing and
    the door disagreeing is exactly the class of defect a unit test misses.

    And it stops at the section boundary: the same token is refused on another
    section's read, so the implication is a level within a family and not a
    quiet widening across the product.
    """
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="write-only",
        scopes=["widgets:write"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    created = api.post(
        WIDGETS,
        data=json.dumps({"name": "Written"}),
        content_type="application/json",
        headers=_bearer(plaintext),
    )
    assert created.status_code == 201, created.content

    listed = api.get(WIDGETS, headers=_bearer(plaintext))
    assert listed.status_code == 200, listed.content
    assert [row["name"] for row in _body(listed)["items"]] == ["Written"]

    elsewhere = api.get(MEMBERSHIPS, headers=_bearer(plaintext))
    assert elsewhere.status_code == 403, elsewhere.content
    assert _body(elsewhere)["code"] == "insufficient_scope"


@pytest.mark.django_db
def test_the_mint_echoes_the_read_a_write_scope_carried(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Explicitness lives at the mint, not on the wire.

    Somebody who asked for `widgets:write` gets the read as well, and the mint
    is where they are told so — rather than finding out by trying, or never
    finding out and minting a second token they did not need.
    """
    api.force_login(owner)
    minted = api.post(
        TOKENS,
        data=json.dumps({"name": "writer", "scopes": ["widgets:write"]}),
        content_type="application/json",
    )
    assert minted.status_code == 201, minted.content
    assert _body(minted)["effective_scopes"] == ["widgets:read", "widgets:write"]


@pytest.mark.django_db
def test_the_same_person_signed_in_is_untouched(api: Client, tenant: Tenant, owner: User) -> None:
    """A ceiling is a property of a credential handed to a machine.

    Nobody handed a browser session to anybody, so there is nothing to narrow —
    and a change that quietly narrowed the human door would have broken every
    screen in the product.
    """
    issue_token(
        user=owner,
        tenant=tenant,
        name="narrow",
        scopes=["widgets:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    api.force_login(owner)
    created = api.post(
        WIDGETS,
        data=json.dumps({"name": "From a browser"}),
        content_type="application/json",
    )
    assert created.status_code == 201, created.content


@pytest.mark.django_db
def test_a_token_minted_with_no_limit_behaves_as_it_always_did(
    api: Client, tenant: Tenant, owner: User
) -> None:
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="wide",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    created = api.post(
        WIDGETS,
        data=json.dumps({"name": "Wide open"}),
        content_type="application/json",
        headers=_bearer(plaintext),
    )
    assert created.status_code == 201, created.content


# --- 5 · a scope grants nothing ------------------------------------------------


@pytest.mark.django_db
def test_a_write_scope_does_not_promote_anybody(
    api: Client, tenant: Tenant, root_org: Organization, member: User
) -> None:
    """The ceiling narrows and the role decides; the two never swap jobs.

    A `member` holding a token scoped to the whole of `roles` — the widest
    ceiling there is over granting one — is still a member. What refuses is the
    escalation wall, not the scope check, and the refusal a caller sees has to
    be the wall's, or somebody will read "insufficient_scope" and go and mint a
    wider token that changes nothing.
    """
    membership = Membership.objects.get(user=member, tenant=tenant)
    _, plaintext = issue_token(
        user=member,
        tenant=tenant,
        name="wide-in-its-family",
        scopes=["roles:write"],
        actor=actor_for(user=member, tenant=tenant),
    )
    refused = api.patch(
        f"{MEMBERSHIPS}{membership.pk}/role/",
        data=json.dumps({"role": "owner"}),
        content_type="application/json",
        headers=_bearer(plaintext),
    )
    assert refused.status_code == 403, refused.content
    assert _body(refused)["code"] == "forbidden"
    membership.refresh_from_db()
    assert membership.role == Membership.Role.MEMBER


# --- 6 · the mint contract, at both doors --------------------------------------


@pytest.mark.django_db
def test_minting_over_the_wire_requires_a_choice(api: Client, tenant: Tenant, owner: User) -> None:
    api.force_login(owner)

    silent = api.post(TOKENS, data=json.dumps({"name": "silent"}), content_type="application/json")
    assert silent.status_code == 400, silent.content
    assert _body(silent)["code"] == "invalid"
    assert "scopes" in _body(silent)["errors"]

    empty = api.post(
        TOKENS,
        data=json.dumps({"name": "empty", "scopes": []}),
        content_type="application/json",
    )
    assert empty.status_code == 400, empty.content
    assert "could not do anything" in _body(empty)["detail"]

    unknown = api.post(
        TOKENS,
        data=json.dumps({"name": "unknown", "scopes": ["widgets:destroy"]}),
        content_type="application/json",
    )
    assert unknown.status_code == 400, unknown.content
    detail = _body(unknown)["detail"]
    assert "widgets:destroy" in detail
    assert "llms.txt" in detail, "an unknown name has to say where the real ones are"

    assert ApiToken.objects.count() == 0


@pytest.mark.django_db
def test_minting_over_the_wire_echoes_the_ceiling_and_what_the_role_can_back(
    api: Client, tenant: Tenant, member: User
) -> None:
    """BUILD NOTE 1: an agent that asked for dead power learns at the mint.

    A `member` may read widely and write almost nothing, so a mint that asked
    for a write family comes back saying so — hours before the first refusal
    would have said it in a log nobody is watching.
    """
    api.force_login(member)
    minted = api.post(
        TOKENS,
        data=json.dumps({"name": "agent", "scopes": ["widgets:read", "org-structure:write"]}),
        content_type="application/json",
    )
    assert minted.status_code == 201, minted.content
    body = _body(minted)
    assert body["scopes"] == ["org-structure:write", "widgets:read"]
    # The write they asked for is dead weight for a member — and the READ it
    # carried is not, so the echo says so rather than dropping the family
    # entirely (owner ruling, 2026-08-24: the verbs are levels).
    assert body["effective_scopes"] == ["org-structure:read", "widgets:read"]
    assert "org-structure:write" not in body["effective_scopes"]
    assert body["token"].startswith("djb_")


@pytest.mark.django_db
def test_minting_over_the_wire_with_a_star_stores_no_ceiling(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    minted = api.post(
        TOKENS,
        data=json.dumps({"name": "no limit", "scopes": ["*"]}),
        content_type="application/json",
    )
    assert minted.status_code == 201, minted.content
    assert _body(minted)["scopes"] is None
    assert _body(minted)["effective_scopes"] is None
    assert ApiToken.objects.get(name="no limit").scopes is None


@pytest.mark.django_db
def test_the_shell_door_requires_the_same_choice(tenant: Tenant, owner: User) -> None:
    """The same contract, and — the point — the same sentence.

    Two doors onto one act is two places a refusal can be worded, and the day
    they differ somebody is reading the wrong one.
    """
    with pytest.raises(CommandError) as silent:
        call_command("issue_token", email=owner.email, name="silent")
    assert "Say which scopes" in str(silent.value)

    with pytest.raises(CommandError) as unknown:
        call_command("issue_token", email=owner.email, name="unknown", scopes=["nope:read"])
    assert "nope:read" in str(unknown.value)

    assert ApiToken.objects.count() == 0


@pytest.mark.django_db
def test_the_shell_door_mints_with_a_ceiling(tenant: Tenant, owner: User) -> None:
    call_command(
        "issue_token",
        email=owner.email,
        tenant=tenant.slug,
        name="from a shell",
        scopes=["widgets:read"],
    )
    assert ApiToken.objects.get(name="from a shell").scopes == ["widgets:read"]


# --- 7 · a token minted before any of this existed -----------------------------


@pytest.mark.django_db
def test_a_token_from_before_ceilings_existed_keeps_every_power(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The grandfather, proved on a row shaped exactly like a pre-migration one.

    `scopes` is `NULL` — which is what an `AddField` leaves behind — and the
    token goes on reading and writing as it did the day it was minted. Anything
    else would have taken power away from every integration already running,
    with nobody having decided to.
    """
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="grandfathered", actor=actor_for(user=owner, tenant=tenant)
    )
    ApiToken.objects.filter(name="grandfathered").update(scopes=None)
    assert ApiToken.objects.get(name="grandfathered").scopes is None

    listed = api.get(WIDGETS, headers=_bearer(plaintext))
    assert listed.status_code == 200, listed.content
    created = api.post(
        WIDGETS,
        data=json.dumps({"name": "Still allowed"}),
        content_type="application/json",
        headers=_bearer(plaintext),
    )
    assert created.status_code == 201, created.content


def test_no_ceiling_means_every_scope_including_ones_added_later() -> None:
    for scope in scopes.vocabulary():
        assert scopes.within_ceiling(ceiling=None, scope=scope)
    assert scopes.within_ceiling(ceiling=None, scope="a-section-nobody-has-built-yet:write")


# --- 8 · the document derives the requirement ----------------------------------


def _bearer_scheme_names(document: dict[str, Any]) -> set[str]:
    """Which published security schemes are a bearer token."""
    schemes = document.get("components", {}).get("securitySchemes", {})
    return {name for name, scheme in schemes.items() if scheme.get("scheme") == "bearer"}


def _reachable_by_token(operation: dict[str, Any], bearer: set[str]) -> bool:
    """The document's own answer to "can a bearer token make this call".

    The **document** half of `docs.reachable_by_token`, and deliberately a
    second reading of the same published fact rather than a call to the same
    function: the mount computes the footer from the authenticator objects, this
    computes the expectation from the `security` block ninja wrote from those
    same objects, and the test below is what proves the two agree. Asking the
    mount would have made that agreement an assumption instead of a measurement.

    An operation with no `security` at all is reachable — it authenticates
    nobody and refuses nobody, which is the inbound webhook receiver.
    """
    if "security" not in operation:
        return True
    return any(bearer & set(requirement) for requirement in operation["security"])


def test_every_published_operation_states_the_scope_it_needs() -> None:
    """Derived and applied to all of them, so none can be forgotten.

    **Two truths, and which one an operation owes is decided by the predicate,
    never by its name.** Almost every operation owes the scope a token needs.
    An operation no bearer token reaches owes the opposite fact — that there is
    no scope and no token to go and get — because printing "mint a token
    carrying `tokens:write`" on the route that refuses every token sent a
    refused caller round a loop, back to the route that had just refused them
    (measured on `POST /tokens/`).

    Nothing here enumerates that route. The carve-out is the `security` block
    the document publishes, so a second session-only operation added tomorrow is
    held to the second truth automatically, and an operation that *stops* being
    session-only is held back to the first one.
    """
    document = the_api.get_openapi_schema()
    bearer = _bearer_scheme_names(document)
    assert bearer, "no bearer scheme is published at all, so this census is blind"

    session_only = 0
    for method, path, operation in _operations():
        where = f"{method.upper()} {path}"
        description = operation["description"]
        if not _reachable_by_token(operation, bearer):
            session_only += 1
            assert docs.SESSION_ONLY_SCOPE_SENTENCE in description, where
            # And the loop is gone: no scope is offered as the way in, because
            # there is no scope that works.
            assert "**Token scope:** a bearer token must carry" not in description, where
            continue
        scope = scopes.required_scope(tags=operation["tags"], methods=[method])
        assert f"`{scope}`" in description, where

    # The carve-out is not allowed to be empty: if it ever is, this test has
    # quietly stopped checking the half it was written for.
    assert session_only, (
        "no operation in the document is session-only, so the session-only half "
        "of this census never ran"
    )


def test_the_mint_publishes_the_refusal_it_exists_to_explain() -> None:
    """`session_required` reaches `x-refusal-codes`, not just the raise site.

    Measured before the fix: the mint declared
    `@refuses("session_required", "invalid", …)` and the published 403 said
    `x-refusal-codes: ["forbidden"]`. The declaration was right and the document
    dropped it, because `_document_operation` groups declared codes by looking
    each one up in `CODE_STATUS` and silently skips a code with no entry — and
    `session_required` had none, its 403 coming from `Forbidden` up the class
    tree instead. So the one refusal this route exists to explain was the one an
    agent reading the contract could not find.

    Asserted on the code and not on the prose: `x-refusal-codes` is the machine
    half, and an agent choosing what to do next reads that.
    """
    mint = the_api.get_openapi_schema()["paths"][TOKENS]["post"]
    codes = mint["responses"][403]["x-refusal-codes"]
    assert "session_required" in codes, codes
    # And the fact reaches the human half of the same response too, off the
    # registry rather than off anything written here.
    assert "session_required" in mint["responses"][403]["description"]


def test_the_mints_footer_does_not_send_a_refused_caller_back_to_the_mint() -> None:
    """The circular sentence, gone — and the true one in its place.

    It published, on the one route no token may call: "a bearer token must carry
    `tokens:write` to make this call … `POST /tokens/` is where a token with
    this scope is minted." Every instruction in it is a loop. A caller refused
    here was told to mint a token — here — using a token.
    """
    mint = the_api.get_openapi_schema()["paths"][TOKENS]["post"]
    description = mint["description"]

    assert docs.SESSION_ONLY_SCOPE_SENTENCE in description
    assert "must carry `tokens:write` to make this call" not in description
    assert "is where a token with this scope is minted" not in description


def test_the_operations_a_token_can_reach_still_get_the_scope_footer() -> None:
    """The pair: the variant did not quietly swallow everybody else's footer.

    Without this, a predicate that answered `False` for every operation would
    pass the census above by carving all of them out.
    """
    widgets = the_api.get_openapi_schema()["paths"][WIDGETS]["post"]
    assert "`widgets:write`" in widgets["description"]
    assert docs.SESSION_ONLY_SCOPE_SENTENCE not in widgets["description"]


def test_the_predicate_reads_what_an_authenticator_publishes_about_itself() -> None:
    """The unit, so the census above cannot be the only thing holding it.

    Three shapes: the bearer authenticator the API actually mounts, the mint's
    own narrowing, and an operation with no authenticators at all.
    """
    from apps.accounts.auth import API_AUTH, MINT_AUTH

    assert docs.reachable_by_token(API_AUTH) is True
    assert docs.reachable_by_token(MINT_AUTH) is False
    # No authentication is not the same as no token: a route that refuses
    # nobody is reached by a caller holding one like anybody else.
    assert docs.reachable_by_token([]) is True


def test_the_mint_operation_says_where_the_vocabulary_comes_from() -> None:
    mint = the_api.get_openapi_schema()["paths"]["/api/v1/tokens/"]["post"]
    for expected in (":read", ":write", "llms.txt", '["*"]'):
        assert expected in mint["description"]


def test_llms_txt_tells_an_agent_which_scopes_it_can_ask_for() -> None:
    """The agent map had no scope surface at all until this fix.

    An agent reading it could learn every capability and nothing about what to
    ask its human to mint, which is the half of the remedy that matters.
    """
    text = llms_text(the_api)
    assert "## Token scopes" in text
    for scope in scopes.vocabulary():
        assert scope in text
    assert "insufficient_scope" in text


def _binding_scope_literals(source: Path) -> list[str]:
    """Scope-shaped strings in one module that are not documentation.

    A docstring, a field's `description=`/`help_text=`, and a declared `example`
    are all places the vocabulary is QUOTED — which is what the document is for.
    Anywhere else, a string that looks like a scope is a route or a check
    carrying its own copy of a requirement that has one derivation, and the day
    the copy is wrong the door and the document disagree while only the caller
    finds out.
    """
    tree = source_tree(source)
    documentation: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                documentation.add(id(first.value))
        if isinstance(node, ast.Call):
            named = node.func
            callee = getattr(named, "id", None) or getattr(named, "attr", None)
            if callee in {"example", "gettext", "_"}:
                for argument in ast.walk(node):
                    documentation.add(id(argument))
            for keyword in node.keywords:
                if keyword.arg in {"description", "help_text", "help", "detail", "fact"}:
                    for argument in ast.walk(keyword.value):
                        documentation.add(id(argument))

    known = {f"{family}:{verb}" for family in scopes.families() for verb in ("read", "write")}
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in documentation:
            continue
        for scope in known:
            if scope in node.value:
                found.append(f"line {node.lineno}: {scope}")
    return found


def test_no_route_carries_a_hand_written_scope_annotation() -> None:
    """The claim that there is nothing to annotate, checked as a shape.

    A per-route literal is how a derived contract turns into a maintained one.
    The derivation is the one writer, so a scope-shaped string that is not
    documentation — anywhere under `apps/` or in the mount, outside the module
    that owns the vocabulary and the tests that walk it — is a finding.
    """
    root = Path(__file__).resolve().parents[2]
    owner_module = root / "core" / "api" / "scopes.py"
    sources = [
        source
        for source in [*root.rglob("*.py"), *(root.parent / "config").rglob("*.py")]
        if source != owner_module
        and "/tests/" not in str(source)
        and not source.name.startswith("test_")
    ]
    assert sources, "nothing was walked, so this test cannot fail"
    offenders = {
        str(source): found for source in sources if (found := _binding_scope_literals(source))
    }
    assert offenders == {}


def test_the_derivation_is_asked_only_by_the_door_plumbing() -> None:
    """Few callers, each of them plumbing, and none of them a route or a tool.

    A route or a tool that derived its own requirement would be the per-route
    annotation one function call further along. So the callers are three: the
    module that owns the derivation, the machine mount (per registered tool),
    and the rendering helper the HTTP mount asks through — which exists because
    a document has to survive an operation a check would refuse, and is the one
    caller allowed to answer `None` instead of raising.
    """
    root = Path(__file__).resolve().parents[2]
    asks = re.compile(r"(?<![\w])(required_scope|derived_scope)\(")
    callers = {
        str(source.relative_to(root.parent))
        for source in [*root.rglob("*.py"), *(root.parent / "config").rglob("*.py")]
        if "/tests/" not in str(source)
        and not source.name.startswith("test_")
        and asks.search(source_text(source))
    }
    assert callers == {
        "apps/core/api/scopes.py",
        "apps/core/api/docs.py",
        "apps/core/mcp.py",
        "config/api.py",
    }


def test_the_scope_literal_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """The falsifier for the tolerant read. RED before RACE-1: `FileNotFoundError`.

    The plant holds no scope-shaped string, so passing means it was skipped.
    """
    with vanishing_source_file() as planted:
        test_no_route_carries_a_hand_written_scope_annotation()
        assert not planted.exists(), "the census never opened the plant — this drove nothing"
