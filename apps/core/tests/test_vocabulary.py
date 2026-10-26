"""The permission vocabulary: one shape, `<kind>.<verb>`, derived before declared.

Every first-party model is a **kind**; every kind carries `create`, `read`,
`update` and `delete` by derivation with a sentence; every other verb is a
status transition or a compound act an app **declares** on a kind; `core`
reserves one verb, `tenant.own`, for ownership. Roles are patterns over that
vocabulary, discovered from `apps/<x>/roles.py` exactly as policies are
discovered from `apps/<x>/policies.py`.

**Nothing here is stored.** The vocabulary is computed once at import from the
model registry and the declarations — Django's own precedent is the four
permissions it derives per model at `migrate`, and the reason to do it in
Python instead of in rows is that rows go stale against code the moment a
product adds a model.

The census below is a **ratchet**, not an assertion: the eighteen keys that do
not yet fit the shape belong to eight apps whose sweeps are separate rungs.
The list may shrink. It may never grow.
"""

from __future__ import annotations

import importlib.machinery
import io
import json
import logging
import sys
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import models

from apps.core import policies as core_policies
from apps.core.actor import Actor
from apps.core.authz import (
    RESERVED_PERMISSIONS,
    VIRTUAL_KINDS,
    DeclaredRole,
    _declarations,
    _discover_default_roles,
    allows,
    default_role_key,
    defaults_for,
    first_party_models,
    kind_of,
    kind_registry,
    kind_registry_of,
    non_conforming,
    policies,
    refusal_sentence,
    renamed_permissions,
    reset_policies,
    role_declarations,
    role_declarers,
    vocabulary,
)
from apps.core.management.commands.rename_permission import (
    TABLE_HEADER,
    declared_renames,
)
from apps.core.models import BaseModel
from apps.core.tests.isolation import isolated_apps
from apps.core.tests.unclaimed import unclaimed, unclaimed_role

#: **This module is a census over OTHER apps' declarations, and it says so here
#: so that nothing has to name it.** Every name below is a declaration module
#: `apps.core.authz._declarations` walks — `apps/<x>/policies.py` and
#: `apps/<x>/roles.py` — and the claim is: a rung that changes one of those
#: files in ANY app has moved what this module asserts about, so this module
#: belongs in that rung's `--loop` selection.
#:
#: WHY THE DECLARATION LIVES HERE AND NOT IN THE SELECTOR. `quality/djb/scope.py`
#: derives the seed by walking `apps/*/tests/test_*.py` for this marker, so the
#: selector names no app and no module: the census that wants to be run is the
#: thing that says so, and a product's own census joins the day it is written by
#: adding this line. The reverse — a path typed into the selector — is the hand
#: list the whole scope machinery exists to delete, and it is what the standing
#: case `the table names no app` refuses.
#:
#: The seed is ONE MODULE, never the `core` app: see `loop_scope__census_seed`.
CENSUS_SEEDED_BY = ("policies", "roles")

CRUD = ("create", "read", "update", "delete")


@pytest.fixture(autouse=True)
def _vocabulary_restored() -> Iterator[None]:
    """The vocabulary is process-wide and cached. Drop it around every test.

    Same reason `apps/usage/tests/test_policies.py` does it for the policy
    registry: a plant left behind becomes the bar somebody else's module is
    measured against, and the failure lands in their file.
    """
    reset_policies()
    yield
    reset_policies()


def plant_module(monkeypatch: pytest.MonkeyPatch, dotted: str, **attributes: Any) -> ModuleType:
    """Put a module where discovery will find it, and take it away again.

    `importlib.util.find_spec` consults `sys.modules` first, so a module object
    with a real `__spec__` in there IS discoverable — which means the plant
    exercises the discovery walk itself rather than a seam around it.
    """
    module = ModuleType(dotted)
    module.__spec__ = importlib.machinery.ModuleSpec(dotted, loader=None)
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, dotted, module)
    return module


# --- P1.1 · one kind per model, unique, or an opt-out with a reason -----------


def test_every_first_party_model_yields_a_unique_kind_or_an_opt_out_reason() -> None:
    """The population is the model registry, filtered by module — never a list.

    A central list of kinds is the thing this design exists to avoid: a product
    adds a model and gets its four permissions with no edit to `core`.
    """
    population = first_party_models()
    assert population, "the population is empty; this test would pass vacuously"

    kinds: dict[str, str] = {}
    for model in population:
        label = model._meta.label
        if getattr(model, "authz_kind_of", None) is not None:
            # **An owned child adds no kind of its own — that is what
            # `authz_kind_of` MEANS**, and `kind_registry_of` skips these for
            # exactly this reason. `kind_of` still answers for one (it resolves
            # to the parent's kind, which is the whole point at a selector), so
            # a uniqueness census that did not skip them would read a child and
            # its parent as two models claiming one kind. `files.FileVersion`
            # is the first of these on this tree and it is why this branch
            # exists; the condition is read off the model rather than naming it.
            assert kind_of(model) is not None, label
            continue
        kind = kind_of(model)
        if kind is None:
            assert getattr(model, "authz_kind_reason", ""), (
                f"{label} opted out of the vocabulary with no reason. "
                "`authz_kind = None` is a claim a reviewer has to be able to disagree with."
            )
            continue
        assert kind not in kinds, f"{label} and {kinds[kind]} both claim the kind {kind!r}"
        kinds[kind] = label

    assert kind_registry().keys() == kinds.keys()


def test_the_four_named_kinds_derive_from_the_class_name() -> None:
    """The examples the criteria pin, and only those: the algorithm is not pinned.

    A class name carrying an acronym (`SSOConnection`) derives whatever
    `snake_case` does with it, and the valve for that is `authz_kind`.
    """
    from apps.accounts.models import SsoConnection
    from apps.example.models import Widget, WidgetEntry
    from apps.workflows.models import WorkflowRun

    assert kind_of(Widget) == "widget"
    assert kind_of(WidgetEntry) == "widget_entry"
    assert kind_of(WorkflowRun) == "workflow_run"
    assert kind_of(SsoConnection) == "sso_connection"


def test_a_third_party_model_is_outside_the_population_by_module() -> None:
    """Outside the vocabulary, and therefore yielding no kind at all.

    `auth.Permission`, `socialaccount.SocialToken`, `admin.LogEntry` and the
    rest are tables this deployment did not design; a permission over one of
    them would be a permission nobody can act on.
    """
    from django.contrib.admin.models import LogEntry
    from django.contrib.auth.models import Permission

    population = set(first_party_models())
    assert LogEntry not in population
    assert Permission not in population
    for model in population:
        assert type(model).__module__ or True
        assert model.__module__.startswith("apps."), model._meta.label


@isolated_apps("apps.core")
def test_a_kind_collision_is_refused_at_import() -> None:
    """Two models, one kind: the vocabulary cannot be derived, so nothing starts.

    Refused rather than resolved, because either resolution — first wins, last
    wins — would make a permission mean a different row depending on import
    order.
    """

    class Widget(BaseModel):
        class Meta:
            app_label = "core"

    class Gadget(BaseModel):
        authz_kind = "widget"

        class Meta:
            app_label = "core"

    with pytest.raises(ImproperlyConfigured) as caught:
        kind_registry_of([Widget, Gadget])

    message = str(caught.value)
    assert "core.Widget" in message
    assert "core.Gadget" in message
    assert "widget" in message


@isolated_apps("apps.core")
def test_an_authz_kind_of_naming_a_non_cascade_fk_is_refused() -> None:
    """A child is authorized under its aggregate only when it DIES with it.

    `authz_kind_of` says "my writes are the parent's business". That is true of
    a `CASCADE` child and false of a `PROTECT` one, which outlives the parent
    and is therefore its own record.
    """

    class Aggregate(BaseModel):
        class Meta:
            app_label = "core"

    class Loose(BaseModel):
        aggregate = models.ForeignKey(Aggregate, on_delete=models.PROTECT)
        authz_kind_of = "aggregate"

        class Meta:
            app_label = "core"

    with pytest.raises(ImproperlyConfigured) as caught:
        kind_registry_of([Aggregate, Loose])

    assert "core.Loose" in str(caught.value)
    assert "CASCADE" in str(caught.value)


@isolated_apps("apps.core")
def test_a_cascade_child_is_authorized_under_its_parents_kind() -> None:
    """The right form, beside the refusal, so the refusal is not the only shape shown."""

    class Aggregate(BaseModel):
        class Meta:
            app_label = "core"

    class Part(BaseModel):
        aggregate = models.ForeignKey(Aggregate, on_delete=models.CASCADE)
        authz_kind_of = "aggregate"

        class Meta:
            app_label = "core"

    registry = kind_registry_of([Aggregate, Part])

    assert kind_of(Part) == "aggregate"
    assert registry["aggregate"] is Aggregate


@isolated_apps("apps.core")
def test_an_opt_out_without_a_reason_is_refused() -> None:
    """`authz_kind = None` is a claim; a claim with no sentence is not reviewable."""

    class Silent(BaseModel):
        authz_kind = None

        class Meta:
            app_label = "core"

    with pytest.raises(ImproperlyConfigured) as caught:
        kind_registry_of([Silent])

    assert "authz_kind_reason" in str(caught.value)


@isolated_apps("apps.core")
def test_an_opt_out_with_a_reason_leaves_the_registry() -> None:
    class Internal(BaseModel):
        authz_kind = None
        authz_kind_reason = "the platform's own bookkeeping; no door reaches a row of it"

        class Meta:
            app_label = "core"

    assert kind_of(Internal) is None
    assert kind_registry_of([Internal]) == {}


# --- P1.2 · four derived verbs per kind, each with a sentence -----------------


def test_every_kind_carries_its_four_verbs_with_sentences() -> None:
    """A builder cannot forget one: the four are derived, never typed."""
    words = vocabulary()
    derived = {action for action, permission in words.items() if permission.decided_by == "derived"}

    # Four per kind, plus each family verb a kind's markers derive (`Archivable`
    # → `archive`, `restore`) — read off the same roads the vocabulary reads.
    from apps.core.authz import family_verbs

    assert len(derived) == sum(4 + len(family_verbs(model)) for model in kind_registry().values())

    for kind in kind_registry():
        for verb in CRUD:
            action = f"{kind}.{verb}"
            assert action in words, f"{action} is not in the vocabulary"
            permission = words[action]
            assert permission.kind == kind
            assert permission.verb == verb
            assert permission.is_read is (verb == "read")
            assert permission.conforms
            assert permission.sentence, f"{action} carries no sentence"
            assert action not in permission.sentence, (
                f"{action}'s sentence is the dotted key; a refused caller reads English"
            )


def test_the_derived_sentences_read_as_english() -> None:
    """The four shapes, pinned on a kind whose app overrides none of them.

    `message` is chosen for exactly that reason: `apps/comms/policies.py`
    declares three verbs on it and no sentence for any of the four derived
    ones, so what is asserted here is the derivation and not a product's prose.
    """
    words = vocabulary()

    assert words["message.create"].sentence == "You may not create messages here."
    assert words["message.read"].sentence == "You may not read this message."
    assert words["message.update"].sentence == "You may not change this message."
    assert words["message.delete"].sentence == "You may not delete this message."


def test_an_app_that_already_wrote_the_sentence_keeps_its_words() -> None:
    """The override, in the tree rather than in a plant.

    `apps/example/policies.py` has always said "You may not create widgets in
    this organization." — a better sentence than the derivation, because it
    knows the tree exists. The key is still derived; only the words are the
    app's.
    """
    widget_create = vocabulary()["widget.create"]

    assert widget_create.sentence == "You may not create widgets in this organization."
    assert widget_create.decided_by == "derived"


def test_an_apps_prose_overrides_a_derived_sentence_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app owns the WORDS. It does not own whether the key exists."""
    from apps.example import policies as example_policies

    before = vocabulary()
    size = len(before)
    assert before["widget.read"].decided_by == "derived"

    reset_policies()
    monkeypatch.setitem(example_policies.ACTION_PROSE, "widget.read", "No peeking at widgets.")
    after = vocabulary()

    assert after["widget.read"].sentence == "No peeking at widgets."
    assert after["widget.read"].decided_by == "derived"
    assert after["widget.read"].conforms
    assert len(after) == size


# --- P1.3 · every declared key classified; the non-conforming ones are pinned --

#: **The ratchet, at zero.** It held eighteen names at P1, each in the
#: vocabulary and answering exactly as it always had, each belonging to an app
#: whose sweep was its own rung — and it shrank and never grew, one line per
#: sweep. The `accounts` sweep struck the last three
#: (`accounts.user.deactivate`, `accounts.user.erase`,
#: `identity_platform.configure`), so the pin below is `[]` and the assertion
#: under it is no longer a ratchet but a property: **every key this deployment
#: declares fits `<kind>.<verb>`.** It is kept as a list rather than deleted
#: because `test_the_census_refuses_a_nineteenth` plants against it, and an
#: empty population is exactly the population a plant has to be able to leave.
NON_CONFORMING: list[str] = []


def test_every_declared_key_conforms() -> None:
    """The ratchet reached zero at the `accounts` sweep, and this is what it became.

    It used to read "the non-conforming keys are exactly the pinned list", which
    is the sentence a shrinking backlog needs. There is no backlog now, so the
    honest sentence is the property itself — and a key that stopped conforming
    would red here with its own name rather than by failing to match a list.
    """
    assert sorted(non_conforming()) == []


def test_every_non_conforming_key_says_why_and_still_answers() -> None:
    """Classified, never dropped: the transition is not allowed to widen anything.

    A key the census calls non-conforming is still in `vocabulary()` and the
    policy lookup is untouched, so a product's `require` on one of these
    answers today's answer today.
    """
    words = vocabulary()
    for action, reason in non_conforming().items():
        assert action in words
        assert not words[action].conforms
        assert reason, f"{action} is non-conforming with no reason"
        assert words[action].non_conformance == reason


def test_a_declared_verb_on_a_registry_kind_conforms() -> None:
    words = vocabulary()

    for action in ("widget.approve", "organization.move", "invitation.revoke", "delivery.replay"):
        assert words[action].decided_by == "declared", action
        assert words[action].conforms, action


def test_the_census_refuses_a_nineteenth(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ratchet, driven: one planted key that does not fit and the pin is red.

    `gadget.view` is both halves at once — no kind `gadget`, and `view` is an
    alias for the one read verb — so the classification cannot pass it by
    luck.
    """
    from apps.example import policies as example_policies

    reset_policies()
    monkeypatch.setitem(example_policies.ACTION_PROSE, "gadget.view", "You may not view gadgets.")

    assert "gadget.view" in non_conforming()
    assert sorted(non_conforming()) != NON_CONFORMING
    assert len(non_conforming()) == len(NON_CONFORMING) + 1


def test_every_key_bearing_declaration_names_a_key_the_vocabulary_holds() -> None:
    """The other three dicts a `policies.py` declares, censused the way prose is.

    `ACTION_PROSE` is the declaration the vocabulary is BUILT from, so a key in
    it is a key by definition. `POLICIES`, `DEFAULT_ROLES` and
    `RENAMED_PERMISSIONS` are not: they name keys the vocabulary is supposed to
    already hold, and nothing checked that they do.

    **What a disagreement is, and why every layer stays green over one.** A
    `POLICIES` entry for a key no kind derives and no `ACTION_PROSE` declares is
    a predicate for a capability nobody can be given — `require` resolves the
    key, finds nothing in the vocabulary and never reaches the predicate — and
    it is invisible by construction: `vocabulary()` consults the registry only
    for keys it has already derived (`registry.get(action)` over `words`), so
    the key is absent from the vocabulary, absent from `non_conforming()`, and
    in no pinned list anywhere. A `DEFAULT_ROLES` key is the same defect wearing
    a default; a rename is the pair — its VALUE must be a key and its KEY must
    not be, because the old word is an alias the resolver answers and never a
    second entry.

    **Derived per app, printed by dict and app.** The population is
    `_declarations`' own discovery walk — the one the registry uses — so a
    product's `policies.py` joins this census the day it is written, and the
    failure names the app, the dict and the key rather than a count.
    """
    words = set(vocabulary())
    seen = 0
    disagreements: list[str] = []

    for attribute in ("POLICIES", "DEFAULT_ROLES"):
        for config, declared in _declarations("policies", attribute):
            for key in declared:
                seen += 1
                if key not in words:
                    disagreements.append(
                        f"{config.label}.{attribute} names {key!r}, which the vocabulary "
                        "does not hold"
                    )
    for config, declared in _declarations("policies", "RENAMED_PERMISSIONS"):
        for old, new in declared.items():
            seen += 1
            if new not in words:
                disagreements.append(
                    f"{config.label}.RENAMED_PERMISSIONS renames {old!r} onto {new!r}, "
                    "which the vocabulary does not hold"
                )
            if old in words:
                disagreements.append(
                    f"{config.label}.RENAMED_PERMISSIONS renames {old!r}, which is still "
                    "in the vocabulary — an alias is not a second key"
                )

    # Non-vacuous: this tree declares key-bearing dicts, so a census reading
    # none of them is a census that has stopped walking rather than one with
    # nothing to say.
    assert seen, "no key-bearing declaration was read at all"
    assert disagreements == [], disagreements


def test_a_read_alias_verb_is_non_conforming(monkeypatch: pytest.MonkeyPatch) -> None:
    """`read` is THE read verb. `view`, `list` and `get` are three more spellings."""
    from apps.example import policies as example_policies

    reset_policies()
    for verb in ("view", "list", "get"):
        monkeypatch.setitem(example_policies.ACTION_PROSE, f"widget.{verb}", "No.")
    census = non_conforming()

    for verb in ("view", "list", "get"):
        assert f"widget.{verb}" in census
        assert "read" in census[f"widget.{verb}"]


# --- P1.4 · the reserved key and the virtual kind ------------------------------


def test_the_reserved_key_is_declared_by_core_with_its_sentence() -> None:
    words = vocabulary()

    assert "tenant.own" in RESERVED_PERMISSIONS
    permission = words["tenant.own"]
    assert permission.decided_by == "reserved"
    assert permission.sentence == "You may not make somebody an owner of this tenant."
    assert permission.is_read is False
    assert permission.conforms


def test_a_pattern_never_matches_a_reserved_key_or_a_virtual_kind() -> None:
    """Two things a role pattern can never sweep up, and they are different things.

    `admin = ("*",)` is "everything but ownership", which is exactly today's
    admin — and it is the reason the rank table can retire without a ceiling
    going with it.

    **And everything but a VIRTUAL kind**, which is the second exclusion and
    arrived with the first key on one. A reserved key is withheld because
    ownership may not be handed out sideways; a virtual-kind key is withheld
    because there is no row to be given authority over at all, so it is in
    nobody's collection and its policy predicate is the whole rule. Both come
    out of `grantable_permissions()`, which is the one place either exclusion
    is expressed, and the set below is derived from `VIRTUAL_KINDS` rather than
    naming a key — a second virtual key needs no edit here.

    `defaults_for("owner")` is deliberately NOT filtered: it answers what the
    owner role IS, and `collection(OWNER_ROLE)` answers what an owner may be
    handed. `test_handing_out.py` holds that pair.
    """
    words = vocabulary()
    virtual = {action for action, word in words.items() if word.kind in VIRTUAL_KINDS}
    assert virtual, "no key on a virtual kind — this assertion has stopped measuring"

    assert defaults_for("admin") == set(words) - set(RESERVED_PERMISSIONS) - virtual
    assert "tenant.own" not in defaults_for("admin")
    assert "tenant.own" not in defaults_for("member")
    assert "tenant.own" in defaults_for("owner")
    assert defaults_for("admin") & virtual == set()
    assert defaults_for("member") & virtual == set()


def test_the_virtual_kinds_are_a_printed_list_of_one() -> None:
    """One virtual kind, with a reason, and now exactly one key on it.

    `deployment` exists for the platform-operator act that has no row and no
    tenant. It is a list of one so that "not a registry kind" stays a refusal
    rather than a shrug. The kind was declared with nothing on it; the
    `accounts` sweep gave it its one verb — `deployment.configure`, the key that
    used to be spelled `identity_platform.configure` on a kind no model derives.

    **Both halves are asserted**, because "a virtual kind" and "a DECLARED key
    on it" are two facts and only the second is a thing an app can get wrong:
    there is no model to derive four verbs from, so a key here is declared or it
    does not exist.
    """
    assert set(VIRTUAL_KINDS) == {"deployment"}
    assert VIRTUAL_KINDS["deployment"]

    words = vocabulary()
    assert [action for action in words if action.startswith("deployment.")] == [
        "deployment.configure"
    ]
    assert words["deployment.configure"].kind == "deployment"
    assert words["deployment.configure"].decided_by == "declared"
    assert words["deployment.configure"].conforms


# --- P1.5 · roles are discovered like policies ---------------------------------


def test_the_template_declares_admin_and_member_with_todays_meaning() -> None:
    declared = role_declarations()

    # The template's OWN declarations are core's; an app beside it may declare
    # more (the worked customer surface declares `customer`), read off the
    # registry rather than typed here.
    assert {key for key, app in role_declarers().items() if app == "core"} == {"admin", "member"}
    assert declared["admin"].permissions == ("*",)
    assert declared["member"].permissions == ("*.read",)
    assert declared["member"].is_default_for_new_members
    assert not declared["admin"].is_default_for_new_members
    assert default_role_key() == "member"

    # `- VIRTUAL` beside `- RESERVED`: a key on a kind with no table is in
    # nobody's collection, so `("*",)` does not reach it. `member` is
    # `("*.read",)` and no virtual key on this tree is a read, so its set is
    # unchanged — stated rather than assumed, because the day one is, this
    # line is where it shows.
    virtual = {action for action, word in vocabulary().items() if word.kind in VIRTUAL_KINDS}
    assert defaults_for("admin") == set(vocabulary()) - set(RESERVED_PERMISSIONS) - virtual
    reads = {action for action in vocabulary() if action.endswith(".read")}
    member_by_declaration = {
        action for action, roles in _discover_default_roles().items() if "member" in roles
    }
    assert defaults_for("member") == reads | member_by_declaration
    assert defaults_for("member") & virtual == set()


def test_a_scratch_key_a_product_took_is_lengthened_until_unclaimed() -> None:
    """A template case's word a product declared is never the case's undeclared key."""
    assert unclaimed("auditor", {"member"}) == "auditor"
    assert unclaimed("auditor", {"auditor", "auditorx"}) == "auditorxx"
    assert unclaimed_role("member") == "memberx"


def test_owner_is_the_whole_vocabulary_and_is_not_a_declaration() -> None:
    """The one platform role. Not a row, not a `roles.py` entry: the vocabulary."""
    assert "owner" not in role_declarations()
    assert defaults_for("owner") == set(vocabulary())


def test_a_role_nobody_declared_holds_nothing() -> None:
    assert defaults_for(unclaimed_role("auditor")) == frozenset()
    assert defaults_for("") == frozenset()


# --- the wall: a role a declared surface names holds exactly its declaration ---


def _walled_roles() -> set[str]:
    """Every declared role a DECLARED surface names — never one `staff` admits by totality."""
    from apps.core import surfaces

    return {
        key
        for key in role_declarations()
        if surfaces.named(surfaces.surface_for_role(key).roles) is not None
    }


def _listed_outside_its_declaration(role: str) -> list[str]:
    """The keys whose `default_roles` name `role` while its own declaration does not."""
    declared = defaults_for(role)
    return sorted(
        action
        for action, word in vocabulary().items()
        if role in word.default_roles and action not in declared
    )


def test_every_declared_role_is_listed_only_where_it_declares() -> None:
    """No compat residue on any role (clause (5) retired), walled or not.

    For every declared role, the vocabulary's `default_roles` column lists it on
    exactly the keys its patterns match and the `DEFAULT_ROLES` entries naming
    it — `defaults_for` — and nowhere else, so `collection()`, `defaults_for`
    and `introspect` cannot disagree about it. A virtual kind's key is in no
    `defaults_for` (`grantable_permissions`, the one exclusion), so it is set
    aside here. The planted sibling below proves it with a world of its own.
    """
    from apps.core.authz import VIRTUAL_KINDS

    virtual = {key for key, word in vocabulary().items() if word.kind in VIRTUAL_KINDS}
    roles = sorted(role_declarations())
    assert roles and virtual
    assert {
        role: [key for key in _listed_outside_its_declaration(role) if key not in virtual]
        for role in roles
    } == {role: [] for role in roles}


def _plant_the_two_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two scratch roles declaring the same one pattern, where discovery finds `roles.py`.

    `widget.create` is planted undeclared, so no role holds it but by its own pattern.
    """
    from apps.example import policies as example_policies

    monkeypatch.setattr(example_policies, "DEFAULT_ROLES", {})
    plant_module(
        monkeypatch,
        "apps.example.roles",
        ROLES={
            key: DeclaredRole(key, key, ("widget.read",), False)
            for key in ("zzz_walled", "zzz_open")
        },
    )


def _face(*roles: str) -> Any:
    """A scratch one-family surface admitting `roles`."""
    from apps.core import surfaces

    return surfaces.Surface(
        families={"widgets"},
        acts={"read"},
        roles=set(roles),
        tenant_rule="membership",
        screens=set(),
    )


def test_a_walled_role_and_an_open_role_each_hold_their_declaration_and_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both halves in one planted world, with no residue on either (clause (5) retired).

    Two scratch roles declaring the SAME pattern, and a scratch surface naming
    one of them: both hold exactly `widget.read`. The role no declared surface
    names used to hold `widget.create` and the rest of the residue; it holds its
    declaration now, as the walled one always did. Planted into the discovery
    walk (a `roles` and a `surfaces` module where discovery finds them), never a file.
    """
    from apps.core import surfaces

    _plant_the_two_roles(monkeypatch)
    plant_module(monkeypatch, "apps.example.surfaces", SURFACES={"zzz_face": _face("zzz_walled")})
    monkeypatch.setattr(surfaces, "_declared", None)
    reset_policies()

    assert "zzz_walled" in _walled_roles() and "zzz_open" not in _walled_roles()
    assert defaults_for("zzz_walled") == defaults_for("zzz_open") == {"widget.read"}
    assert _listed_outside_its_declaration("zzz_walled") == []
    assert _listed_outside_its_declaration("zzz_open") == []
    assert not {"zzz_open", "zzz_walled"} & set(vocabulary()["widget.create"].default_roles)


def test_a_surface_collision_is_rule_85s_to_report_and_the_vocabulary_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed surface declaration never takes the vocabulary down with it.

    Two surfaces naming one role is refused by the surfaces' union, and house
    rule 85 reports it beside every other field it judges — which it can only
    do while the vocabulary it reads the acts from still answers. The role two
    surfaces name is named either way, so it is walled either way.
    """
    from django.core.exceptions import ImproperlyConfigured

    from apps.core import surfaces

    _plant_the_two_roles(monkeypatch)
    plant_module(
        monkeypatch,
        "apps.example.surfaces",
        SURFACES={"zzz_left": _face("zzz_walled"), "zzz_right": _face("zzz_walled")},
    )
    monkeypatch.setattr(surfaces, "_declared", None)
    reset_policies()

    with pytest.raises(ImproperlyConfigured, match="admitted by two surfaces"):
        surfaces.declared()
    monkeypatch.setattr(surfaces, "_declared", None)
    assert _listed_outside_its_declaration("zzz_walled") == []
    assert _listed_outside_its_declaration("zzz_open") == []


def _plant_an_undeclared_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """`widget.publish` with a predicate and no `DEFAULT_ROLES` entry — a developer's own key."""
    from apps.example import policies as example_policies
    from apps.example.policies import can_create

    monkeypatch.setattr(
        example_policies, "POLICIES", {**example_policies.POLICIES, "widget.publish": can_create}
    )
    monkeypatch.setattr(
        example_policies,
        "ACTION_PROSE",
        {**example_policies.ACTION_PROSE, "widget.publish": "You may not publish that widget."},
    )


def test_the_declaration_owns_a_product_key_and_the_two_readers_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A product key with a predicate and no declaration is held as `defaults_for` says."""
    _plant_an_undeclared_publish(monkeypatch)
    reset_policies()

    declared = {role for role in role_declarations() if "widget.publish" in defaults_for(role)}
    assert set(vocabulary()["widget.publish"].default_roles) == {"owner"} | declared
    assert "member" not in vocabulary()["widget.publish"].default_roles


def test_a_noun_sweep_records_no_residue_yes_for_an_undeclared_product_key(
    monkeypatch: pytest.MonkeyPatch, db: None
) -> None:
    """The noun baseline renders `allows`: a role says yes only where its declaration holds it."""
    from apps.core.tests.permissions_world import noun_census
    from apps.example.models import Widget

    def _row(tenant: Any, owner: Any) -> Widget:
        from apps.core.services import root_organization

        return Widget.objects.create(
            tenant=tenant,
            organization=root_organization(tenant=tenant),
            owner_id=owner.pk,
            name=f"census-{owner.pk}",
        )

    _plant_an_undeclared_publish(monkeypatch)
    reset_policies()

    cells = noun_census(Widget, row=_row)["answers"]["widget.publish"]
    assert {role: cells[role] for role in role_declarations()} == {
        role: "widget.publish" in defaults_for(role) for role in role_declarations()
    }
    assert not any(cells[f"member{side}"] for side in ("", " · own", " · other")), cells


def test_a_platform_key_with_a_predicate_and_no_declaration_is_offered_to_nobody_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same undeclared key on a PLATFORM app is held as `defaults_for` says."""
    _plant_an_undeclared_publish(monkeypatch)
    reset_policies()

    declared = {role for role in role_declarations() if "widget.publish" in defaults_for(role)}
    holders = vocabulary()["widget.publish"].default_roles
    assert set(holders) == {"owner"} | declared, holders
    assert "member" not in holders


def test_a_surface_role_holds_its_declaration_and_nothing_more_in_a_flat_tenant(
    db: None,
) -> None:
    """`defaults_for(role) == collection(tenant, role)` for every walled role, on a flat world.

    The collection is what somebody HOLDS (the code layer,
    plus the tenant's rows — none here); for a role a declared surface names it
    is its declaration and nothing else.
    """
    from apps.core.authz import collection
    from apps.core.tests.permissions_world import flat_world

    tenant, _actors = flat_world()
    assert {role: collection(tenant, role) for role in _walled_roles()} == {
        role: defaults_for(role) for role in _walled_roles()
    }


def test_two_apps_declaring_one_role_key_refuse_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `usage` precedent: a collision against code stops the process."""
    plant_module(
        monkeypatch,
        "apps.example.roles",
        ROLES={"admin": DeclaredRole("admin", "Example admin", ("*",), False)},
    )
    reset_policies()

    with pytest.raises(ImproperlyConfigured) as caught:
        role_declarations()

    message = str(caught.value)
    assert "admin" in message
    assert "apps.core.roles" in message
    assert "apps.example.roles" in message


def test_two_default_roles_refuse_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "The role a new member gets" is one answer or none, never two."""
    plant_module(
        monkeypatch,
        "apps.example.roles",
        ROLES={"guest": DeclaredRole("guest", "Guest", ("*.read",), True)},
    )
    reset_policies()

    with pytest.raises(ImproperlyConfigured) as caught:
        default_role_key()

    message = str(caught.value)
    assert "guest" in message
    assert "member" in message


def test_a_declaration_named_owner_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """`owner` is the platform's, and redefining it is how a ceiling disappears."""
    plant_module(
        monkeypatch,
        "apps.example.roles",
        ROLES={"owner": DeclaredRole("owner", "Owner", ("*.read",), False)},
    )
    reset_policies()

    with pytest.raises(ImproperlyConfigured) as caught:
        role_declarations()

    assert "owner" in str(caught.value)


def test_a_declaration_keyed_on_a_reserved_permission_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plant_module(
        monkeypatch,
        "apps.example.roles",
        ROLES={"tenant.own": DeclaredRole("tenant.own", "Owner", (), False)},
    )
    reset_policies()

    with pytest.raises(ImproperlyConfigured) as caught:
        role_declarations()

    assert "tenant.own" in str(caught.value)


def test_a_default_roles_entry_widens_a_key_without_the_roles_author_knowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app-side half: "a member may set widget policies", said in the app, planted.

    The plant names a key no app declares for `member`, so it proves the entry and not the tree.
    """
    from apps.example import policies as example_policies

    assert "widget_policy.create" not in defaults_for("member")

    reset_policies()
    monkeypatch.setattr(
        example_policies,
        "DEFAULT_ROLES",
        {**example_policies.DEFAULT_ROLES, "widget_policy.create": frozenset({"member"})},
    )

    assert "widget_policy.create" in defaults_for("member")
    assert "member" in vocabulary()["widget_policy.create"].default_roles


# --- P1.6 · a renamed key answers as its new key -------------------------------

#: Core's own table, read — never retyped.
RENAMES = core_policies.RENAMED_PERMISSIONS

#: The kinds whose successors belong to `core`, so the test below can say "these
#: are core's three" without saying "and nobody else has swept yet".
CORE_KINDS = frozenset({"organization", "tenant", "membership", "invitation", "role", "grant"})


def test_core_declares_its_three_renames() -> None:
    """Core's three are in the table, discovered off core's own `policies.py`.

    **`<=` and not `==`, since P7.7.** `renamed_permissions()` is the WHOLE
    TREE's table — `_discover_renames` walks every app's `RENAMED_PERMISSIONS`,
    which is the mechanism, and the mechanism is what makes a per-app sweep cost
    one line in the app that owns the key. An equality here asserted that no
    other app had swept yet, which is a fact about the CALENDAR rather than
    about `core`, and it would red once per sweep with nothing wrong. So the
    assertion is now what this test's own name says, plus the half that made the
    equality worth having: core's three are the only ones core declares.
    """
    table = renamed_permissions()

    assert RENAMES.items() <= table.items()
    assert {old: new for old, new in table.items() if new.split(".")[0] in CORE_KINDS} == RENAMES


def test_the_renamed_sentences_are_byte_identical_under_the_new_keys() -> None:
    """Three keys change name; zero sentences change. A caller reads what they read."""
    assert refusal_sentence("organization.update") == "You may not rename that organization."
    assert refusal_sentence("tenant.update") == "You may not change this tenant's configuration."
    assert refusal_sentence("membership.delete") == "You may not remove that person's membership."

    for old, new in RENAMES.items():
        assert refusal_sentence(old) == refusal_sentence(new)


@pytest.mark.django_db
def test_a_renamed_key_answers_as_its_new_key_and_prints_one_deprecation(
    admin_actor: Actor, member_actor: Actor, caplog: pytest.LogCaptureFixture
) -> None:
    """The seam is one line before the policy lookup, so no window opens.

    Between this and the resolution rung, a product's `require(actor,
    "organization.rename", org)` has to answer exactly what it answered before,
    or the transition has silently widened something.
    """
    organization = admin_actor.org
    for old, new in RENAMES.items():
        for actor in (admin_actor, member_actor):
            assert allows(actor, old, organization) == allows(actor, new, organization), old

    reset_policies()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        allows(admin_actor, "organization.rename", organization)
        allows(admin_actor, "organization.rename", organization)

    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]
    renamed = [line for line in lines if line.get("event") == "core.authz.renamed"]
    assert len(renamed) == 1, lines
    assert renamed[0]["old"] == "organization.rename"
    assert renamed[0]["new"] == "organization.update"


@pytest.mark.django_db
def test_the_old_key_reaches_the_POLICY_and_not_the_role_default(
    owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the seam's PLACE closes, driven so it cannot pass by coincidence.

    On this tree the three renamed keys happen to get the same answer either
    way — resolution and the old role fallback agree for an owner, an admin and
    a member — so an equality over today's actors would go green with the seam
    severed. The discriminator is a policy that says **no to everybody**:
    with the alias resolved before the lookup the old key finds it and answers
    False; resolved after, the old key finds nothing, falls to the role default
    and an owner is silently allowed.

    The policy is planted for this test, which is its own victim: nothing found
    in the tree is reshaped.
    """
    reset_policies()
    monkeypatch.setitem(policies(), "organization.update", lambda actor, obj: False)

    assert not allows(owner_actor, "organization.update", owner_actor.org)
    assert not allows(owner_actor, "organization.rename", owner_actor.org)


def test_a_rename_onto_an_undeclared_key_is_refused_at_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An alias to a key nobody declared is an alias to silence."""
    from apps.example import policies as example_policies

    reset_policies()
    monkeypatch.setattr(
        example_policies,
        "RENAMED_PERMISSIONS",
        {"widget.bless": "widget.sanctify"},
        raising=False,
    )

    with pytest.raises(ImproperlyConfigured) as caught:
        renamed_permissions()

    assert "widget.sanctify" in str(caught.value)


def test_an_alias_chain_is_refused_at_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """`a → b → c` is a rename nobody can reason about; two lines say two things."""
    from apps.example import policies as example_policies

    reset_policies()
    monkeypatch.setattr(
        example_policies,
        "RENAMED_PERMISSIONS",
        {"widget.bless": "organization.rename"},
        raising=False,
    )

    with pytest.raises(ImproperlyConfigured) as caught:
        renamed_permissions()

    assert "organization.rename" in str(caught.value)


def test_a_renamed_key_is_not_itself_in_the_vocabulary() -> None:
    """The old name is an alias, not a second key: the census counts one."""
    words = vocabulary()
    for old, new in RENAMES.items():
        assert old not in words
        assert new in words
        assert words[new].renamed_from == (old,)


# --- P1.8 · what the census publishes -----------------------------------------


def test_every_permission_carries_the_full_record() -> None:
    """No row is allowed to be half-derived: the instrument prints all of it."""
    for action, permission in vocabulary().items():
        assert permission.action == action
        assert permission.decided_by in {"derived", "declared", "reserved"}
        assert permission.kind
        assert permission.verb
        assert permission.app
        assert permission.sentence
        assert isinstance(permission.default_roles, tuple)
        assert "owner" in permission.default_roles
        assert isinstance(permission.renamed_from, tuple)


def test_a_predicate_is_published_beside_the_key_it_decides() -> None:
    words = vocabulary()

    assert words["widget.update"].predicate is not None
    # `widget.approve`, not `organization.move`: the seven administrative keys
    # lost their predicate when resolution took the question over — "do you
    # administer this node" is now the declared `admin`'s collection at the node
    # the object names, and a predicate that re-asked the data half would be a
    # second copy of it. A key whose rule is genuinely about the ROW still
    # carries one, and this pin is about that.
    assert words["widget.approve"].predicate is not None
    assert words["organization.move"].predicate is None
    assert words["widget.read"].predicate is None


def test_the_vocabulary_is_a_read_only_mapping() -> None:
    """Computed, never stored — and never edited from a call site either."""
    words = vocabulary()
    assert isinstance(words, Mapping)
    with pytest.raises(TypeError):
        words["widget.create"] = None  # type: ignore[index]


# --- P1.7 · `roles.py` is a canonical module name everywhere --------------------


def test_a_product_roles_module_is_a_canonical_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, settings: Any
) -> None:
    """A discovery module is canonical everywhere, not recorded per app.

    `core` is exempt from rule 11's novel-name half, so `apps/core/roles.py`
    would have been legal without this — and a PRODUCT's `apps/<x>/roles.py`
    would have been `djb.E011` on sight. Recording it per app in `rules.yaml`
    is the one-shared-file-every-app-edits collision the discovery pattern
    exists to avoid; the `search` entry in the same constant is the precedent.
    """
    from apps.core import checks

    probe = tmp_path / "apps" / "zzz_probe"
    probe.mkdir(parents=True)
    (probe / "roles.py").write_text("ROLES = {}\n", encoding="utf-8")
    (probe / "policies.py").write_text("POLICIES = {}\n", encoding="utf-8")

    class _Config:
        label = "zzz_probe"
        path = str(probe)

    monkeypatch.setattr(checks, "_local_app_configs", lambda: [_Config()])
    # `check_canonical_shape` reports paths relative to `BASE_DIR`, so the probe
    # has to look like it lives under one. **`checks._rules` is `@cache`d and
    # reads `BASE_DIR / quality/rules.yaml`**, so a call made while `BASE_DIR`
    # points at a directory with no `quality/` in it caches an EMPTY rule set
    # for the rest of the worker process — and every later test that reads an
    # allow-list through it sees nothing. Paid for once, in a full `--loop`:
    # rule 32's valve came back empty and two tests in another module failed
    # with a leak list of nineteen paths that had never leaked. The cache is
    # dropped on the way out, and on the way in so this test is not measured
    # against whatever the previous test left in it.
    checks._rules.cache_clear()
    settings.BASE_DIR = tmp_path
    try:
        assert checks.check_canonical_shape() == []

        (probe / "helpers.py").write_text("", encoding="utf-8")
        banned = checks.check_canonical_shape()
        assert [message.id for message in banned] == ["djb.E011"], (
            "the probe proves nothing if the check cannot fail over the same directory"
        )
    finally:
        checks._rules.cache_clear()


@pytest.mark.parametrize("stem", ["meters", "lifecycle"])
def test_a_product_discovered_module_is_a_canonical_name(
    stem: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, settings: Any
) -> None:
    """A module a platform reader discovers in every app passes rule 11 in a product app."""
    from apps.core import checks

    probe = tmp_path / "apps" / "zzz_probe"
    probe.mkdir(parents=True)
    (probe / f"{stem}.py").write_text("", encoding="utf-8")

    class _Config:
        label = "zzz_probe"
        path = str(probe)

    monkeypatch.setattr(checks, "_local_app_configs", lambda: [_Config()])
    checks._rules.cache_clear()
    settings.BASE_DIR = tmp_path
    try:
        assert checks.check_canonical_shape() == []

        (probe / "wrangler.py").write_text("", encoding="utf-8")
        novel = checks.check_canonical_shape()
        assert [message.id for message in novel] == ["djb.E011"], (
            "the probe proves nothing if the check cannot fail over the same directory"
        )
    finally:
        checks._rules.cache_clear()


# --- P1.9 · the docstring example names a real key -----------------------------


def test_the_reach_grammar_example_names_a_key_that_exists() -> None:
    """A censused marker spelled in prose is a phantom registration.

    `may_be_named`'s worked example used a key this tree retires; the example
    now names a conforming key, so the docstring and the vocabulary agree.
    """
    from apps.core import authz

    source = authz.may_be_named.__doc__ or ""
    assert "preference.set" not in source
    assert "recipient.update" in source
    assert "recipient.update" in vocabulary()


# --- P1.10 · the release note's rename table is the command's OUTPUT ----------

#: The marker sentence a CHANGELOG table must sit under to be one of the tables
#: this census reads. It is the release note's own claim about itself — "the
#: table, derived from `renamed_permissions()`" — and a table nobody makes that
#: claim about is somebody else's table, not a copy of this one.
CHANGELOG_TABLE_MARKER = "derived from `renamed_permissions()`"

#: How far above a table's header the marker may sit, in lines, and the window
#: is JOINED before it is searched — the sentence is prose in a wrapped bullet,
#: so `derived from` and `` `renamed_permissions()` `` land on different lines
#: and a per-line search finds neither. Four covers the wrap plus the blank line
#: markdown needs before a table; wider and an unrelated paragraph further up
#: starts adopting tables it never mentioned.
CHANGELOG_MARKER_REACH = 4


def _changelog_lines() -> list[str]:
    from django.conf import settings

    return (settings.BASE_DIR / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()


def _changelog_rename_tables() -> list[list[str]]:
    """Every marker-introduced rename table in the note, dedented, header first.

    Dedented because the tables live INSIDE a markdown list item and therefore
    carry the list's indent: the release note cannot print the command's output
    at column zero without breaking out of the bullet it belongs to. The indent
    is the only difference this census forgives, and it forgives it by removing
    it rather than by comparing loosely.
    """
    lines = _changelog_lines()
    tables: list[list[str]] = []
    for index, line in enumerate(lines):
        if line.strip() != TABLE_HEADER:
            continue
        window = " ".join(lines[max(0, index - CHANGELOG_MARKER_REACH) : index])
        if CHANGELOG_TABLE_MARKER not in " ".join(window.split()):
            continue
        block: list[str] = []
        for candidate in lines[index:]:
            stripped = candidate.strip()
            if not stripped.startswith("|"):
                break
            block.append(stripped)
        tables.append(block)
    return tables


def _table_rows(block: Iterable[str]) -> list[tuple[str, str, str]]:
    """`(app, old, new)` for every data row of a rendered table block."""
    rows: list[tuple[str, str, str]] = []
    for line in block:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells == ["app", "old key", "new key"] or cells[0].startswith("-"):
            continue
        rows.append((cells[0], cells[1].strip("`"), cells[2].strip("`")))
    return rows


def _printed_table() -> str:
    out = io.StringIO()
    call_command("rename_permission", "--table", stdout=out)
    return out.getvalue()


def test_the_table_is_the_union() -> None:
    """`--table` prints `renamed_permissions()` and nothing else, in one order.

    The pair set is asserted against the union itself — the property that makes
    the command a READER of the table rather than a second copy of it — and the
    count is pinned only over `platform_apps`, so a product declaring its own
    rename joins the printed table without reding a platform census (the
    `platform_only` disposition `apps/exports/tests/test_census.py` records).
    """
    from quality.partition import platform_apps

    rows = _table_rows(_printed_table().splitlines())

    assert {(old, new) for _app, old, new in rows} == set(renamed_permissions().items())
    assert len(rows) == len(renamed_permissions())
    assert rows == sorted(rows), "the order is deterministic or the note diffs on every run"

    platform = [row for row in rows if row[0] in set(platform_apps())]
    assert len(platform) == 29, "this tree's platform renames; the list may shrink, never grow"


def test_the_table_names_the_app_that_declared_each_pair() -> None:
    """Column one is the declaring `policies.py`'s label, not a guess off the key.

    `accounts` declares `identity_platform.configure` and `core` does not, and
    nothing in either key's text says so: the attribution comes from the
    discovery walk or it is fiction.
    """
    declared = dict(((old, app) for app, old, _new in declared_renames()))

    assert declared["identity_platform.configure"] == "accounts"
    assert declared["organization.rename"] == "core"
    assert declared["usage.read_report"] == "usage"


@pytest.mark.django_db
def test_declared_is_idempotent() -> None:
    """`--declared` moves every pair at once; the second run moves nothing, and says so."""
    from apps.core.models import RolePermission, Tenant

    tenant_ = Tenant.objects.create(name="Rename Co", slug="rename-co")
    pairs = declared_renames()
    assert pairs, "the tree declares at least one rename"
    (_app_a, old_a, new_a), (_app_b, old_b, new_b) = pairs[0], pairs[-1]

    for key in (old_a, old_b):
        RolePermission.objects.create(
            tenant=tenant_,
            role_key="approver",
            permission=key,
            effect=RolePermission.Effect.INCLUDE,
        )

    first = io.StringIO()
    call_command("rename_permission", "--declared", stdout=first)
    moved = first.getvalue()

    assert f"{old_a} -> {new_a}" in moved
    assert f"{old_b} -> {new_b}" in moved
    assert "2 row(s) rewritten" in moved
    assert not RolePermission.objects.filter(permission__in=(old_a, old_b)).exists()
    assert RolePermission.objects.filter(permission__in=(new_a, new_b)).count() == 2

    second = io.StringIO()
    call_command("rename_permission", "--declared", stdout=second)
    again = second.getvalue()

    assert "nothing to rewrite" in again
    assert "row(s) rewritten." not in again
    assert RolePermission.objects.filter(permission__in=(new_a, new_b)).count() == 2


def test_every_declared_rename_is_in_the_changelog_table() -> None:
    """A pair declared in code and absent from the release note is a silent drift.

    **Why it exists.** The note told a reader the table was
    "derived from `renamed_permissions()`" while carrying twenty-five of the
    twenty-nine pairs the code declares: the four `apps/accounts` keys were
    missing, so an operator following the note moved twenty-five key's rows and
    left four tenants' `Grant` rows naming words nothing answers.

    **One-way, and scoped to `platform_apps`.** One-way because the note is a
    HISTORY: a pair swept away in a later release stays in the section that
    announced it, and a census that demanded the reverse would force a product
    to delete its own release notes. Scoped because a product's own app
    declares its own renames in its own note, and a platform test that demanded
    them here would red on a clone for doing the right thing.
    """
    from quality.partition import platform_apps

    tables = _changelog_rename_tables()
    assert tables, (
        f"no CHANGELOG table sits under {CHANGELOG_TABLE_MARKER!r} with the header "
        f"{TABLE_HEADER!r}. The census cannot look, which is not the same as passing."
    )

    published = {(old, new) for table in tables for _app, old, new in _table_rows(table)}
    assert published, "the marker was found and every table under it was empty"

    platform = set(platform_apps())
    declared = [row for row in declared_renames() if row[0] in platform]
    assert declared, "the platform declares at least one rename, or this cannot fail"

    missing = [(app, old, new) for app, old, new in declared if (old, new) not in published]
    assert not missing, (
        "declared in code and absent from the CHANGELOG's rename table:\n"
        + "\n".join(f"  {app}: {old} -> {new}" for app, old, new in missing)
        + "\nRegenerate the table with `manage.py rename_permission --table`."
    )


def _platform_rows_of_the_printed_table() -> list[str]:
    """`--table`'s own lines, keeping only the rows a `platform_apps` app declared.

    **The filter is the whole reason this is a helper.** `--table` prints the
    UNION, which is correct — a product running the command wants its own
    renames in the note it writes. This platform test is about THIS
    repository's note, so it compares the platform rows and nothing else: the
    unscoped form reds in a clone the day a product declares its first rename,
    and the only way out would be pasting the template's table plus its own
    into a file the template owns. Same scoping as the `29` pin above.
    """
    from quality.partition import platform_apps

    platform = set(platform_apps())
    printed = [line for line in _printed_table().splitlines() if line.strip()]
    head, rows = printed[:2], printed[2:]
    return head + [
        line for line in rows if _table_rows([line]) and _table_rows([line])[0][0] in platform
    ]


def test_the_changelog_carries_the_commands_table_verbatim() -> None:
    """One of the note's tables IS `--table`'s platform rows, byte for byte once dedented.

    The census above is one-way and would be satisfied by a hand-written
    superset in the right order. This is the other half: the note carries what
    the command prints, so regenerating it is a copy and never a merge.
    """
    printed = _platform_rows_of_the_printed_table()
    blocks = _changelog_rename_tables()

    assert any(block == printed for block in blocks), (
        "no CHANGELOG rename table equals `manage.py rename_permission --table`'s "
        f"platform rows. The command prints {len(printed)} of them; the note carries "
        f"{[len(block) for block in blocks]}."
    )


class _PlantedConfig:
    """The shape `authz._declarations` yields: something with a `.label`."""

    def __init__(self, label: str) -> None:
        self.label = label


def _plant_declarations(
    monkeypatch: pytest.MonkeyPatch, *extra: tuple[str, dict[str, str]]
) -> None:
    """Append `(app label, RENAMED_PERMISSIONS)` pairs to the discovery walk.

    Its own victim: nothing found in the tree is reshaped, and the plants are
    apps no `apps/` directory holds, which is exactly what a product app looks
    like from inside a platform test.
    """
    from apps.core.management.commands import rename_permission as command

    def planted(module: str, attribute: str) -> list[tuple[Any, dict[Any, Any]]]:
        # `_declarations` from `apps.core.authz`, which this module already
        # imports — never reached through the command module, whose copy is an
        # import and not an export.
        found: list[tuple[Any, dict[Any, Any]]] = list(_declarations(module, attribute))
        if (module, attribute) == ("policies", "RENAMED_PERMISSIONS"):
            found += [(_PlantedConfig(label), dict(declared)) for label, declared in extra]
        return found

    monkeypatch.setattr(command, "_declarations", planted)


def test_a_product_apps_rename_joins_the_table_and_leaves_the_note_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clone declaring its own rename must not red a test about OUR note.

    The unscoped form of the check above went red here: the printed table grows
    by the product's row, the template's `CHANGELOG.md` does not, and the only
    remedy a product would have is editing a platform test or a platform file.
    """
    from apps.core.management.commands import rename_permission as command

    before = len(_platform_rows_of_the_printed_table())
    real_union = dict(renamed_permissions())

    _plant_declarations(monkeypatch, ("zzz_product", {"gizmo.polish": "gizmo.update"}))
    monkeypatch.setattr(
        command, "renamed_permissions", lambda: {**real_union, "gizmo.polish": "gizmo.update"}
    )

    whole = _table_rows(_printed_table().splitlines())
    assert ("zzz_product", "gizmo.polish", "gizmo.update") in whole, (
        "the plant proves nothing if the product's rename never reached the printed table"
    )
    assert len(_platform_rows_of_the_printed_table()) == before

    test_the_changelog_carries_the_commands_table_verbatim()


def test_two_apps_declaring_one_old_key_are_refused_by_both_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agreeing about the successor is not agreeing about who owns the key.

    `authz._discover_renames` refuses two declarers that DISAGREE about the
    successor; two that agree pass it, and the table's first column then names
    whichever app the registry walked last — silently, and wrongly for one of
    them. This is the refusal for that case, and it names both.
    """
    from django.core.management.base import CommandError

    pair = {"gizmo.polish": "gizmo.update"}
    _plant_declarations(monkeypatch, ("zzz_left", dict(pair)), ("zzz_right", dict(pair)))

    with pytest.raises(CommandError) as caught:
        declared_renames()

    assert "zzz_left" in str(caught.value)
    assert "zzz_right" in str(caught.value)
    assert "gizmo.polish" in str(caught.value)
    assert caught.value.returncode == 2


def test_the_image_ships_the_partition_lockfile_a_runtime_command_reads() -> None:
    """`.dockerignore` un-ignores the lockfile `manage.py declare` reads at runtime."""
    from django.conf import settings

    ignore = (Path(settings.BASE_DIR) / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!quality/partition.yaml" in ignore
