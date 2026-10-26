"""Who may file, read, replace and archive a document. Policies are code, found by discovery.

Any member may file and replace; archive and restore take an administrator of the document's node.
`file.read` comes from `member`'s `*.read`; which documents a hat sees is rule 24's.
There is no `file.download`: issuing a presigned URL IS the read, audited as `file.read`.
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
    # `file.read` is the role layer's question; see the module docstring.
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


DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "file.create": frozenset({"member"}),
    "file.replace": frozenset({"member"}),
    "file.archive": frozenset({"member"}),
    "file.restore": frozenset({"member"}),
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
