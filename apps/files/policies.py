"""Who may file, read, replace and archive a document. Policies are code.

`core.authz.require(actor, "file.replace", file)` finds this by discovery — this
file is never registered anywhere. The key is `<noun>.<verb>`, the predicate
takes the acting `Actor` and the object, and it returns a bool.

**The rule for this app is one sentence: anybody in the tenant may put a
document in and take one out; only an administrator of the document's own node
may archive one, or restore it.**

**After the sweep this file asks no role, and two of its four predicates are
gone.** What `admin` and `member` are is `apps/core/roles.py`'s, a tenant's own
`Role`, `RolePermission` and `Grant` rows compose with it, and the node half of
every question is `core.authz.where_of`'s — a `file.*` key is a key of the
registry kind `file` now (`StoredFile.authz_kind`), so it is asked at the row's
own organization instead of nowhere in particular.

* `can_read` asked "does this actor carry a membership in the tenant" and never
  looked at the document. `member` holds `*.read` by its declared pattern, so
  the role layer answers it and no declaration had to move.
* `can_archive` asked for an owner or an admin. It is now the family's one
  predicate, `core.policies.may_archive`, for archive AND restore: whoever
  administers the document's own node (`organization.update` held there,
  inheriting downward) — and never the system actor, which a person's archive
  refuses (the sweep's archive of an emptied document is its own service).

**DEFERRED, by the PM's ruling of 2026-09-16, and named here so it is not
mistaken for an oversight: `can_file` and `can_replace` still admit any
membership.** The sweep's shape puts that half in `DEFAULT_ROLES` — "a `member`
may file, and may replace" as data rather than as a predicate — and a
`DEFAULT_ROLES` entry moves what `defaults_for("member")` answers, which is a
pin of the flat product that no per-app sweep may move alone. So both keep their
membership half as transitional residue, `member` goes on holding them through
the vocabulary's own compat column, and `tests/authz_baseline.json` measures
that rather than claiming it.

Filing and reading are ordinary product work. Gating them behind a role would
push a product into writing its own upload path — which is the exact bypass the
storage seam exists to close, and the same argument `apps/comms/policies.py`
makes about sending. And a role bar would buy nothing anyway: WHICH documents a
hat can see is already answered one layer down by rule 24's
`for_tenant(t).visible_to(actor)` and, for a document named by id, by
`core.authz.may_be_named` — a branch manager reading their own branch's files
learns nothing they could not have listed.

**Archive is the exception because it is the nearest thing to a delete this app
has**, and it is not one: `archived_at` hides the document from every reader in
the branch while the objects stay in the bucket until purge lands (ADR files-2 §
exclusions, and `StoredFile.lifecycle` says so). So it is an act that makes a
tenant's own record less complete without making the liability smaller — which
is an administrative decision rather than an ordinary one.

**There is no `file.download` and no `file.issue_url`.** Issuing a presigned
download URL IS the read, and giving it a second action would invite a
deployment to grant one without the other, which cannot mean anything: a reader
who may see the metadata and not the bytes is a reader who has been told the
document exists. The audit row for an issuance names `file.read` for the same
reason.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.core.policies import may_archive


def can_file(actor: Actor, obj: Any = None) -> bool:
    """Anybody in the tenant may put a document in, under the hat they are wearing.

    Where it lands is not this predicate's question: ADR core-20's placement law
    puts a created row at the ACTING HAT and never at the root, and a version
    lands where its document lives (`FileVersion.derive_org_from`).
    """
    return membership_for(actor) is not None


def can_replace(actor: Actor, obj: Any = None) -> bool:
    """Adding a version is ordinary work, and it destroys nothing.

    This is the verb `add_version` authorizes, and the reason it sits with
    filing rather than with archiving is that a replace is **additive**: version
    n stays readable, stays presignable, and stays true for whatever cited it.
    What changes is which version a reader gets when they do not name one.
    """
    return membership_for(actor) is not None


POLICIES: dict[str, Policy] = {
    # `file.read` is the role layer's question and it answers it — see the
    # module docstring. `file.create` and `file.replace` are here only until the
    # deferred `DEFAULT_ROLES` rung moves their membership half.
    "file.create": can_file,
    "file.replace": can_replace,
    # The archive pair is the family's one predicate (`core.policies.may_archive`,
    # which declares `@refuses_system`): an administrator of the document's OWN
    # node, inheriting downward, and never the product acting for itself. Both
    # keys are derived from `StoredFile` declaring `Archivable`; restore is the
    # same question as archive, because a narrower door back would be a second,
    # weaker door onto the same state.
    "file.archive": may_archive,
    "file.restore": may_archive,
}


# The kinds this app's two models used to yield, renamed onto the one they yield
# now (ADR core-25). **Derived keys, not declared ones**: nobody ever typed
# `stored_file.read` — the registry produced it from the class name, and
# `StoredFile.authz_kind` deletes it. `core.authz.allows` resolves an alias one
# line BEFORE the policy lookup, so anything still saying an old word gets the
# new key's answer rather than falling to the role default with nothing saying
# so. A deployment whose `Grant` or `RolePermission` ROWS carry one runs
# `manage.py rename_permission`; a row is inert until it does.
RENAMED_PERMISSIONS: dict[str, str] = {
    "stored_file.create": "file.create",
    "stored_file.read": "file.read",
    "stored_file.update": "file.update",
    "stored_file.delete": "file.delete",
    "file_version.create": "file.create",
    "file_version.read": "file.read",
    "file_version.update": "file.update",
    "file_version.delete": "file.delete",
}


# The sentence a refused caller reads. Plain language, never the action name;
# a product declares these beside its policies and never edits `core`.
ACTION_PROSE: dict[str, str] = {
    "file.create": (
        "You may not file documents in this organization. Filing is open to "
        "anybody with a place in the tenant, so signing in under a hat you hold "
        "here is what opens it."
    ),
    "file.read": (
        "You may not read this organization's documents. Documents belong to the "
        "part of the organization that filed them, and you are acting as a part "
        "that does not include it."
    ),
    "file.replace": (
        "You may not add a version to this document. Replacing is open to "
        "anybody with a place in the tenant, so signing in under a hat that "
        "covers this document is what opens it."
    ),
    "file.archive": (
        "You may not archive this document. Archiving takes it out of everyone's "
        "working set while the stored bytes remain, so it is kept to the people "
        "who administer this part of the organization."
    ),
    "file.restore": (
        "You may not restore this document. Bringing an archived document back into "
        "everyone's working set is kept to the people who administer this part of the "
        "organization, the same people who may archive it."
    ),
}
