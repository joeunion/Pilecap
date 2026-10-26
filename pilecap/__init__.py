"""The product developer's one import: the bases, the service contract, the refusals and roads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pilecap._lazy import lazy

if TYPE_CHECKING:
    #: ActorKind — Who is acting: `"human"`, `"agent"` or `"system"`.
    from apps.core.actor import Actor, ActorKind
    from apps.core.audit import AuditEntry
    from apps.core.authz import (
        DeclaredRole,
        DeclaresRoles,
        Permission,
        #: Policy — A permission predicate `(actor, row) -> bool`, declared in an app's `POLICIES`.
        Policy,
        holds,
        is_member,
        may_be_named,
        refuses_system,
        require,
    )

    #: BlockerFn — A blocker hook: given the row, the `Blocker`s that stop the verb.
    from apps.core.blockers import BlockerFn

    #: Outcome — One bulk item's result: `"done"`, `"unchanged"` or `"refused"`.
    from apps.core.bulk import BulkReport, BulkResult, Outcome, run_bulk
    from apps.core.concurrency import require_version
    from apps.core.context import current_actor
    from apps.core.exceptions import (
        #: NON_FIELD_KEY — Where a validation message lands when it is the object's, not a field's.
        NON_FIELD_KEY,
        ArchiveBlocked,
        Archived,
        Blocked,
        Blocker,
        Conflict,
        DomainError,
        Forbidden,
        Invalid,
        InvalidSignature,
        MergeBlocked,
        Merged,
        MergeSurvivor,
        MoveBlocked,
        NoActingScope,
        NotFound,
        RateLimited,
        Refusal,
        Remedy,
        RestoreBlocked,
        RunFailed,
        StaleVersion,
        Unavailable,
        as_invalid,
        register_refusal,
        wire_refusal,
    )
    from apps.core.fields import EncryptedCharField, EncryptedJSONField
    from apps.core.headers import (
        CAUSATION_HEADER,
        CORRELATION_HEADER,
        ORG_HEADER,
        TENANT_HEADER,
        USER_HEADER,
    )

    #: IDEMPOTENCY_KEY_HEADER — The request header that makes a write replayable: `Idempotency-Key`.
    from apps.core.idempotency import HEADER as IDEMPOTENCY_KEY_HEADER
    from apps.core.lifecycle import AppendOnlyViolation, Lifecycle, LifecycleKind, LifecycleRegistry
    from apps.core.log import get_logger
    from apps.core.middleware import declare_signed_door
    from apps.core.models import (
        Archivable,
        BaseModel,
        Duplicable,
        Duplicate,
        InheritedDownward,
        Mergeable,
        Movable,
        OrgScopedModel,
        ScopedManager,
        ScopedQuerySet,
        TenantScopedModel,
        Versioned,
        ancestor_paths,
        child_path,
        duplicate_key_constraint,
        is_descendant_path,
        subtree_q,
    )
    from apps.core.money import CurrencyMismatch, Money, money_fields
    from apps.core.policies import may_archive, may_merge, may_move
    from apps.core.roads import road
    from apps.core.schemas import (
        EXAMPLE_ORGANIZATION_ID,
        EXAMPLE_VERSION,
        ActsOut,
        ActsPage,
        ArchivedByOut,
        ArchivedOut,
        BulkArchiveIn,
        BulkIdsIn,
        BulkMoveIn,
        BulkOut,
        BulkRefusalOut,
        BulkRestoreIn,
        BulkResultOut,
        EventPayload,
        HistoryActorOut,
        HistoryEntryOut,
        HistoryPage,
        HomedOut,
        ListPage,
        MeasuredBasisOut,
        MeasuredOut,
        MoveIn,
        RefusalOut,
        RefusalRemedyOut,
        RepointOut,
        Show,
        StrictIn,
        VersionedIn,
        VersionedMoveIn,
        VersionedOut,
        acts_field,
        event_payload,
        example,
        personal,
    )
    from apps.core.service import service
    from apps.core.time import (
        #: UTC — The UTC zone every stored time is in.
        UTC,
        as_tenant_time,
        end_of_day,
        in_days,
        is_past,
        now,
        start_of_day,
        today,
    )
    from apps.core.verbs import (
        ROADS,
        Importer,
        MergeOutcome,
        Repointed,
        Repointer,
        allowed_acts,
        archive_row,
        duplicate_row,
        merge_counts,
        merge_rows,
        page_acts,
        parse_subject,
        rehome,
        require_live,
        require_no_merged_losers,
        resolve_subject,
        restore_row,
        shown,
        subject_for,
        with_allowed_acts,
    )

    #: The release this tree stands on: the SDK's version is the template's.
    __version__: str

if not TYPE_CHECKING:
    _reexport = lazy(__name__)

    def __getattr__(name: str) -> Any:
        """`__version__` from the settings; every other name from its module, on first read."""
        if name == "__version__":
            from django.conf import settings

            return settings.TEMPLATE_VERSION
        return _reexport(name)


__all__ = [
    "CAUSATION_HEADER",
    "CORRELATION_HEADER",
    "EXAMPLE_ORGANIZATION_ID",
    "EXAMPLE_VERSION",
    "IDEMPOTENCY_KEY_HEADER",
    "NON_FIELD_KEY",
    "ORG_HEADER",
    "ROADS",
    "TENANT_HEADER",
    "USER_HEADER",
    "UTC",
    "Actor",
    "ActorKind",
    "ActsOut",
    "ActsPage",
    "AppendOnlyViolation",
    "AuditEntry",
    "Archivable",
    "ArchiveBlocked",
    "Archived",
    "ArchivedByOut",
    "ArchivedOut",
    "BaseModel",
    "Blocked",
    "Blocker",
    "BlockerFn",
    "BulkArchiveIn",
    "BulkIdsIn",
    "BulkMoveIn",
    "BulkOut",
    "BulkRefusalOut",
    "BulkReport",
    "BulkRestoreIn",
    "BulkResult",
    "BulkResultOut",
    "Conflict",
    "CurrencyMismatch",
    "DeclaredRole",
    "DeclaresRoles",
    "DomainError",
    "EncryptedCharField",
    "EncryptedJSONField",
    "Duplicable",
    "Duplicate",
    "EventPayload",
    "Forbidden",
    "HistoryActorOut",
    "HistoryEntryOut",
    "HistoryPage",
    "HomedOut",
    "Importer",
    "InheritedDownward",
    "Invalid",
    "InvalidSignature",
    "Lifecycle",
    "LifecycleKind",
    "LifecycleRegistry",
    "ListPage",
    "MeasuredBasisOut",
    "MeasuredOut",
    "MergeBlocked",
    "MergeOutcome",
    "MergeSurvivor",
    "Mergeable",
    "Merged",
    "Money",
    "Movable",
    "MoveBlocked",
    "MoveIn",
    "NoActingScope",
    "NotFound",
    "OrgScopedModel",
    "Outcome",
    "Permission",
    "Policy",
    "RateLimited",
    "Refusal",
    "RefusalOut",
    "RefusalRemedyOut",
    "RepointOut",
    "Remedy",
    "Repointed",
    "Repointer",
    "RestoreBlocked",
    "RunFailed",
    "ScopedManager",
    "ScopedQuerySet",
    "Show",
    "StaleVersion",
    "StrictIn",
    "TenantScopedModel",
    "Unavailable",
    "Versioned",
    "VersionedIn",
    "VersionedMoveIn",
    "VersionedOut",
    "acts_field",
    "allowed_acts",
    "ancestor_paths",
    "archive_row",
    "as_invalid",
    "as_tenant_time",
    "child_path",
    "current_actor",
    "declare_signed_door",
    "duplicate_key_constraint",
    "duplicate_row",
    "end_of_day",
    "event_payload",
    "example",
    "get_logger",
    "holds",
    "in_days",
    "is_descendant_path",
    "is_member",
    "is_past",
    "may_archive",
    "may_be_named",
    "may_merge",
    "may_move",
    "merge_counts",
    "merge_rows",
    "money_fields",
    "now",
    "page_acts",
    "parse_subject",
    "personal",
    "refuses_system",
    "register_refusal",
    "rehome",
    "require",
    "require_live",
    "require_no_merged_losers",
    "require_version",
    "resolve_subject",
    "restore_row",
    "road",
    "run_bulk",
    "service",
    "shown",
    "start_of_day",
    "subject_for",
    "subtree_q",
    "today",
    "wire_refusal",
    "with_allowed_acts",
]
