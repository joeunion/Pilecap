"""Writes for the core app.

Tenants and memberships are rows like any other: nothing else creates them, and
nothing calls `.save()` on them outside this module. Each function is
`@service` — keyword-only, atomic, traced, logged, audited.

The one asymmetry worth stating: `create_tenant` writes no audit row, because
there is no tenant to scope it to until the moment it returns. The tenant row
itself, with its `created_at`, is the record of its own creation. Everything
that happens *inside* a tenant is audited from the first membership onwards.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# `Membership.user` is declared with `settings.AUTH_USER_MODEL` and typed here as
# `AbstractBaseUser`, so that `core` imports no app above it.
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.urls import reverse

# rule-25: invitation mail is core's own; core may not import the comms app (rule 7)
from apps.core import bridge, events, mail
from apps.core.actor import Actor, system_actor
from apps.core.authz import (
    OWNER_ROLE,
    RESERVED_PERMISSIONS,
    VIRTUAL_KINDS,
    collection,
    default_role_key,
    defaults_for,
    effective_permissions,
    grantable_permissions,
    may_be_named,
    read_kinds_by_node,
    refusal_sentence,
    require,
    role_declarations,
    vocabulary,
)
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound, Remedy, as_invalid
from apps.core.flags import FLAGS_KEY
from apps.core.ids import uuid7
from apps.core.log import get_logger
from apps.core.models import (
    PATH_MAX_DEPTH,
    PATH_MAX_LENGTH,
    PATH_SEPARATOR,
    ROOT_SEGMENT,
    Grant,
    Invitation,
    Membership,
    Organization,
    PathOverflow,
    Role,
    RolePermission,
    Tenant,
    ancestor_paths,
    child_path,
    decode_path_segment,
    is_descendant_path,
    path_depth,
    subtree_q,
)
from apps.core.roads import road
from apps.core.schemas import GrantOut, MembershipOut, RoleOut, event_payload
from apps.core.service import service, write_audit

# import order: the hub first — families import it at their head, it imports them last
from apps.core.services._hub import (
    INVITATION_DAYS,
    INVITATION_TOKEN_BYTES,
    LOG_KEYS,
    MOVE_BATCH_SIZE,
    MOVE_ORGANIZATION_WORKFLOW,
    OWNERSHIP_PERMISSION,
    RESERVED_TENANT_SLUGS,
    TOO_DEEP,
    create_tenant,
    log,
    root_organization,
)
from apps.core.services._hub import _ask_for_an_identity_home as _ask_for_an_identity_home
from apps.core.services._hub import _create_root_organization as _create_root_organization
from apps.core.services._hub import _landing_node as _landing_node
from apps.core.services.grants import (
    DeletedRole,
    RevokedGrant,
    create_grant,
    create_role,
    delete_grant,
    delete_role,
    rename_permission_rows,
    set_role_collection,
    update_role,
)
from apps.core.services.grants import _expand_patterns as _expand_patterns
from apps.core.services.grants import _kick_if_a_read_was_taken as _kick_if_a_read_was_taken
from apps.core.services.grants import _kick_the_holders_of as _kick_the_holders_of
from apps.core.services.grants import _publish as _publish
from apps.core.services.grants import (
    _refuse_a_key_the_code_layer_owns as _refuse_a_key_the_code_layer_owns,
)
from apps.core.services.grants import (
    _refuse_undeclared_permissions as _refuse_undeclared_permissions,
)
from apps.core.services.grants import _role_out as _role_out
from apps.core.services.grants import _undeclared_or_reserved as _undeclared_or_reserved
from apps.core.services.invitations import (
    INVITE_LANDING_URL,
    PROVISION_INVITED_PERSON_WORKFLOW,
    REDACTED_EMAIL_DOMAIN,
    accept_invitation,
    hash_invitation_token,
    invite_member,
    redact_invitations,
    revoke_invitation,
)
from apps.core.services.invitations import _invited_role as _invited_role
from apps.core.services.invitations import _provision_invited_person as _provision_invited_person
from apps.core.services.invitations import (
    _refuse_a_role_that_stopped_existing as _refuse_a_role_that_stopped_existing,
)
from apps.core.services.memberships import (
    RevokedMembership,
    add_membership,
    known_role_keys,
    revoke_membership,
    role_label,
    set_role,
)
from apps.core.services.memberships import _missing_sentences as _missing_sentences
from apps.core.services.memberships import _placement as _placement
from apps.core.services.memberships import _refuse_escalation as _refuse_escalation
from apps.core.services.memberships import _refuse_handing_out as _refuse_handing_out
from apps.core.services.memberships import (
    _refuse_orphaning_the_tenant as _refuse_orphaning_the_tenant,
)
from apps.core.services.memberships import _refuse_taking_back as _refuse_taking_back
from apps.core.services.memberships import _refuse_unknown_role as _refuse_unknown_role
from apps.core.services.memberships import _write_role_and_kick as _write_role_and_kick
from apps.core.services.organizations import _deepest_descendant_depth as _deepest_descendant_depth
from apps.core.services.organizations import _next_child_index as _next_child_index
from apps.core.services.organizations import _refuse_impossible_move as _refuse_impossible_move
from apps.core.services.organizations import (
    apply_organization_move,
    create_organization,
    move_organization,
    rename_organization,
)
from apps.core.services.sockets import (
    KICK_MEMBERSHIP_REVOKED,
    KICK_ORGANIZATION_MOVED,
    KICK_PERMISSIONS_NARROWED,
    KICK_TENANT_CLOSED,
    KICK_TENANT_SUSPENDED,
    close_sockets,
    close_sockets_on_commit,
    close_tenant_sockets,
    close_tenant_sockets_on_commit,
    kick_if_reads_narrowed,
)
from apps.core.services.sockets import _members_losing_sight_of as _members_losing_sight_of
from apps.core.services.sockets import _register_kick as _register_kick
from apps.core.services.tenants import (
    close_tenant,
    create_first_tenant,
    resume_tenant,
    set_flag,
    suspend_tenant,
    update_tenant_settings,
)
from apps.core.surfaces import absolute_url, surface_for_role
from apps.core.time import in_days, is_past, now
from apps.core.types import Swept

__all__ = [
    "AbstractBaseUser",
    "Actor",
    "Any",
    "Callable",
    "Conflict",
    "DeletedRole",
    "FLAGS_KEY",
    "Forbidden",
    "Grant",
    "GrantOut",
    "INVITATION_DAYS",
    "INVITATION_TOKEN_BYTES",
    "INVITE_LANDING_URL",
    "Invalid",
    "Invitation",
    "Iterable",
    "KICK_MEMBERSHIP_REVOKED",
    "KICK_ORGANIZATION_MOVED",
    "KICK_PERMISSIONS_NARROWED",
    "KICK_TENANT_CLOSED",
    "KICK_TENANT_SUSPENDED",
    "LOG_KEYS",
    "MOVE_BATCH_SIZE",
    "MOVE_ORGANIZATION_WORKFLOW",
    "Mapping",
    "Membership",
    "MembershipOut",
    "NotFound",
    "OWNERSHIP_PERMISSION",
    "OWNER_ROLE",
    "Organization",
    "PATH_MAX_DEPTH",
    "PATH_MAX_LENGTH",
    "PATH_SEPARATOR",
    "PROVISION_INVITED_PERSON_WORKFLOW",
    "PathOverflow",
    "REDACTED_EMAIL_DOMAIN",
    "RESERVED_PERMISSIONS",
    "RESERVED_TENANT_SLUGS",
    "ROOT_SEGMENT",
    "Remedy",
    "RevokedGrant",
    "RevokedMembership",
    "Role",
    "RoleOut",
    "RolePermission",
    "Swept",
    "TOO_DEEP",
    "Tenant",
    "UUID",
    "VIRTUAL_KINDS",
    "ZoneInfo",
    "ZoneInfoNotFoundError",
    "absolute_url",
    "accept_invitation",
    "add_membership",
    "ancestor_paths",
    "annotations",
    "apply_organization_move",
    "as_invalid",
    "bridge",
    "child_path",
    "close_sockets",
    "close_sockets_on_commit",
    "close_tenant",
    "close_tenant_sockets",
    "close_tenant_sockets_on_commit",
    "collection",
    "create_first_tenant",
    "create_grant",
    "create_organization",
    "create_role",
    "create_tenant",
    "dataclass",
    "decode_path_segment",
    "default_role_key",
    "defaults_for",
    "delete_grant",
    "delete_role",
    "effective_permissions",
    "event_payload",
    "events",
    "fnmatchcase",
    "get_logger",
    "grantable_permissions",
    "hash_invitation_token",
    "hashlib",
    "in_days",
    "invite_member",
    "is_descendant_path",
    "is_past",
    "kick_if_reads_narrowed",
    "known_role_keys",
    "log",
    "mail",
    "may_be_named",
    "move_organization",
    "now",
    "path_depth",
    "read_kinds_by_node",
    "redact_invitations",
    "refusal_sentence",
    "rename_organization",
    "rename_permission_rows",
    "require",
    "resume_tenant",
    "reverse",
    "revoke_invitation",
    "revoke_membership",
    "road",
    "role_declarations",
    "role_label",
    "root_organization",
    "secrets",
    "service",
    "set_flag",
    "set_role",
    "set_role_collection",
    "subtree_q",
    "surface_for_role",
    "suspend_tenant",
    "system_actor",
    "transaction",
    "update_role",
    "update_tenant_settings",
    "uuid7",
    "vocabulary",
    "write_audit",
]
