"""What `pilecap` keeps back from a product: one reason per name, and the classes a reason opens."""

from __future__ import annotations

#: The classes a keep-back reason opens with: `<class>: <the reason>`.
REASON_CLASSES: dict[str, str] = {
    "activity": "a write an activity performs for the workflow that owns it",
    "token": "a token or hash primitive the door that checks it owns",
    "identity": "the identity platform's, configured through its own services (rule 27)",
    "socket": "the socket spine's: a product never closes or narrows a socket (rule 58)",
    "tenant-lifecycle": "the operator's tenant lifecycle, never a product feature's",
    "engine": "the platform's own machinery: registries, censuses and checks the gate reads",
    "door": "a platform door's own wiring: a product's door takes the public road instead",
    "wire": "a shape crossing a platform workflow's boundary: the platform's own runs",
    "row": "a row its app's services own: a product reads it through the selectors",
    "plumbing": "a module's own logger, type variable or private constant",
}

#: `apps/core` modules outside the SDK's surface: none of their names joins the population.
INTERNAL_MODULES: dict[str, str] = {
    "apps.core.activities": "engine: the platform's own periodic activity",
    "apps.core.apps": "engine: core's AppConfig: registration by discovery",
    "apps.core.asgi_middleware": "door: the socket door's tenant and hat resolution",
    "apps.core.checks": "engine: the Django system checks the house rules run",
    "apps.core.discovery": "engine: the one discovery walk the mounts call",
    "apps.core.health": "door: the orchestrator's liveness and readiness door",
    "apps.core.ids": "engine: the row identifier BaseModel mints",
    "apps.core.integrations": "engine: the derived census of external services",
    "apps.core.lexicon": "engine: the service-verb matcher rule 16 reads",
    "apps.core.mail": "engine: core's own invitation mail; a product sends through pilecap.comms",
    "apps.core.observability": "engine: the one place telemetry and logging are configured",
    "apps.core.reach": "engine: the drawer's scope_extensions joined onto rules 3, 11 and 16",
    "apps.core.reason_floor": "engine: the reason floor the image carries for a product's valves",
    "apps.core.reporting": "engine: the exception reporter filter the settings name",
    "apps.core.retry": "engine: the deployment's first-retry interval for workflow arguments",
    "apps.core.route_table": "engine: the face's route table, the image's twin of rule 71's reader",
    "apps.core.script_source": "engine: the face's script scanner, the image's twin of the gate's",
    "apps.core.throttling": "door: the doors' rate limiting and its refusal",
    "apps.core.views": "door: the root page listing this deployment's doors",
    "apps.core.workflows": "engine: the standing integrations prober's workflow",
}

#: Every population name `pilecap` does not export: its defining module's key and why.
INTERNAL: dict[str, str] = {
    "apps.accounts.events.IDENTITY_HOME_CREATED": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.authorize_url_for": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_connection_for_email": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_direct_google_links": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_dormant_claim_tenant": (
        "engine: accounts' own reader for erasure and dormant claims"
    ),
    "apps.accounts.selectors.get_enforcing_connection_for": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_first_admin_vouch": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_member": (
        "engine: accounts' own reader for erasure and dormant claims"
    ),
    "apps.accounts.selectors.get_platform_issuer": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_platform_login_url": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_platform_provider_id": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_realm_for_email": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_realm_of_assertion": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_realm_ref": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_tenant_realm": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.get_workforce_domains": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.list_sso_connections": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.list_stale_staff_joins": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.selectors.list_tenants_this_user_alone_owns": (
        "engine: accounts' own reader for erasure and dormant claims"
    ),
    "apps.accounts.services.authenticate_token": (
        "token: the accounts door hashes or checks this credential; a product never holds one"
    ),
    "apps.accounts.services.create_sso_connection": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.disable_sso_connection": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.grant_staff": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.hash_token": (
        "token: the accounts door hashes or checks this credential; a product never holds one"
    ),
    "apps.accounts.services.provision_sso_identity": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.record_identity": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.record_staff_realm": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.retire_direct_google_links": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.retire_stale_staff_join": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.set_identity_branding": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.mark_first_admin_vouch_spent": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.start_identity_home": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.sync_identity_config": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.sync_identity_home": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.sync_workforce_identity_config": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.touch_token": (
        "token: the accounts door hashes or checks this credential; a product never holds one"
    ),
    "apps.accounts.services.unlink_zitadel_identity": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.update_sso_connection": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.verify_sso_domain": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.services.issue_first_admin_vouch": (
        "identity: identity-platform configuration and sign-in, kept on its own road"
    ),
    "apps.accounts.types.IdentityConfigApplied": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.IdentityConfigSync": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.IdentityHomeApplied": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.IdentityHomeAsk": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.InvitationMessage": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.InvitedIdentity": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.InvitedPerson": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.accounts.types.InvitedPersonProvisioned": (
        "wire: a payload of accounts's own workflows, built only by the platform"
    ),
    "apps.comms.services.close_suppression_surge": (
        "engine: comms.services's own machinery, read by the platform"
    ),
    "apps.comms.services.hash_push_token": (
        "token: the comms door hashes or checks this credential; a product never holds one"
    ),
    "apps.comms.services.issue_delivery_nonce": (
        "token: the comms door hashes or checks this credential; a product never holds one"
    ),
    "apps.comms.services.mark_message_sending": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.record_delivery_status": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.record_engagement": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.record_message_failed": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.record_message_sent": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.send_step": (
        "activity: comms's workflow writes this from an activity, never a product"
    ),
    "apps.comms.services.start_suppression_surge": (
        "engine: comms.services's own machinery, read by the platform"
    ),
    "apps.comms.types.DeliverMessage": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.DeliveryAttempt": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.DeliveryStatus": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.MessageOutcome": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.PolicyStep": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.SendStep": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.comms.types.StepStarted": (
        "wire: a payload of comms's own workflows, built only by the platform"
    ),
    "apps.connections.providers.ExampleProvider": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.inbound_handler": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.registered": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.registered_inbound_handlers": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.registered_webhook_verifiers": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.unregister": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.unregister_inbound_handler": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.unregister_webhook_verifier": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.providers.webhook_verifier": (
        "engine: connections.providers's own machinery, read by the platform"
    ),
    "apps.connections.services.apply_inbound_webhook": (
        "activity: connections's workflow writes this from an activity, never a product"
    ),
    "apps.connections.services.purge_inbound_webhooks": (
        "activity: connections's workflow writes this from an activity, never a product"
    ),
    "apps.connections.types.HandleInboundWebhook": (
        "wire: a payload of connections's own workflows, built only by the platform"
    ),
    "apps.connections.types.PurgeInboundWebhooks": (
        "wire: a payload of connections's own workflows, built only by the platform"
    ),
    "apps.connections.types.PurgeOutcome": (
        "wire: a payload of connections's own workflows, built only by the platform"
    ),
    "apps.core.actor.ACTOR_ATTR": ("door: core.actor wires the platform's own door"),
    "apps.core.actor.TOKEN_ATTR": ("door: core.actor wires the platform's own door"),
    "apps.core.actor.TOKEN_AUTH_ATTR": ("door: core.actor wires the platform's own door"),
    "apps.core.actor.actor_from_request": ("door: core.actor wires the platform's own door"),
    "apps.core.admin.AuditEntryAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.InvitationAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.MembershipAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.MoveOrganizationForm": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.OrganizationAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.REFUSAL_ATTR": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.ReadOnlyModelAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.TenantAdmin": ("door: core.admin wires the platform's own door"),
    "apps.core.admin.is_guarded": ("door: core.admin wires the platform's own door"),
    "apps.core.api.acting.require_hat": ("door: core.api.acting wires the platform's own door"),
    "apps.core.api.docs.ADMINISTRATIVE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.ALSO_REFUSES_ATTR": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.CONTRACT_DIVIDER": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.DOOR_LEVEL_ALWAYS": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.DOOR_LEVEL_REFUSALS": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.EVERYDAY": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.METHOD_ORDER": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.OVERVIEW_TEMPLATE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.PLANES": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.REFUSALS_ATTR": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.REFUSAL_SHAPE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.REQUIRED_SCOPE_SENTENCE": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.RESPONSE_HEADERS": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.RETRY_AFTER_HEADER": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.ResponseHeader": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.SCALAR": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.SCALAR_BUNDLE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.SCALAR_CONFIGURATION": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.SCALAR_PAGE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.SCOPES_LINE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.SESSION_ONLY_SCOPE_SENTENCE": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.Scalar": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.TAG_LINE": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.TITLE_MAX_LENGTH": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.UNGROUPED_HEADING": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.URL_NAME_EXTENSION": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.ViewT": ("plumbing: apps.core.api.docs's own type variable"),
    "apps.core.api.docs.WRITE_INCLUDES_READ_SENTENCE": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.add_examples": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.add_response_headers": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.added_refusals": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.contract_half": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.declared_refusals": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.declared_response_headers": (
        "door: core.api.docs wires the platform's own door"
    ),
    "apps.core.api.docs.derived_refusals": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.derived_scope": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.description_of": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.door_level_refusals": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.example_census": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.header_parameter": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.llms_text": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.llms_txt": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.mechanical_tells": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.noun_of": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.on_every_response": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.overview": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.plane_bullets": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.reachable_by_token": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.reads_header": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.refusal_component": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.refusal_response": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.refuses_with": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.tag_entry": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.title_faults": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.title_of": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.url_name_extension": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.with_added": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.with_door_level": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.with_required_scope": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.docs.workshop_half": ("door: core.api.docs wires the platform's own door"),
    "apps.core.api.frozen_families.DRAWER": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.DeclaredBy": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.FROZEN_FAMILIES": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.Released": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.SANCTIONED_RENAMES": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.drawer_families": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.frozen_families.with_drawer": (
        "engine: core.api.frozen_families's own machinery, read by the platform"
    ),
    "apps.core.api.mount.bound_operations": (
        "engine: core.api.mount's own machinery, read by the platform"
    ),
    "apps.core.api.mount.route_table_paths": (
        "engine: core.api.mount's own machinery, read by the platform"
    ),
    "apps.core.api.pagination.CURSOR_VERSION": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.CursorPage": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.DESCENDING": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.FOREIGN_COLLECTION": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.FOREIGN_CURSOR": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.UNBOUND_COLLECTION": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.UNIDENTIFIED_COLLECTION": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.answers_cursor_envelope": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.decode_cursor": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.encode_cursor": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.pagination.offers_pagination_controls": (
        "door: core.api.pagination wires the platform's own door"
    ),
    "apps.core.api.query.ARCHIVED_SWITCH": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.query.DESCENDING": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.query.RANDOM": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.query.RetiredQuery": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.query.offers_query": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.query.refuse_retired_query": (
        "door: core.api.query wires the platform's own door"
    ),
    "apps.core.api.query.retired_query_of": ("door: core.api.query wires the platform's own door"),
    "apps.core.api.routes.INVITATION_ORDERING": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.INVITATION_SEARCH_FIELDS": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.MEMBERSHIP_ORDERING": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.ORGANIZATION_ORDERING": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.ORGANIZATION_SEARCH_FIELDS": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.PREFIX": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.ROLE_ORDERING": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.TAGS": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.accept_invitation_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.add_membership_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.create_organization_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.create_role_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.delete_grant_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.delete_role_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.get_flags_route": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.get_organization_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.get_role_route": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.get_settings_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.invitations_router": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.invite_member_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_grants_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_invitations_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_memberships_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_organizations_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_permissions_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.list_roles_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.membership_permissions_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.move_organization_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.org_structure_router": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.rename_organization_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.revoke_invitation_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.revoke_membership_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.roles_router": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.router": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.set_flag_route": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.set_grant_route": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.set_role_permissions_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.set_role_route": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.settings_router": ("door: core.api.routes wires the platform's own door"),
    "apps.core.api.routes.update_role_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.routes.update_settings_route": (
        "door: core.api.routes wires the platform's own door"
    ),
    "apps.core.api.scopes.InsufficientScope": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.READ": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.RENAME_IS_CLOSED": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.SCOPE_SEPARATOR": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.UNSCOPED": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.UnderivableScope": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.VERB_CLASSES": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.WRITE": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.ceiling_from_request": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.effective_scopes": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.families": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.family_freeze_findings": (
        "door: core.api.scopes wires the platform's own door"
    ),
    "apps.core.api.scopes.granted_scopes": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.parse_scope": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.required_scope": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.verb_class": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.vocabulary": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.api.scopes.within_ceiling": ("door: core.api.scopes wires the platform's own door"),
    "apps.core.asyncdb.run_async": ("engine: core.asyncdb's own machinery, read by the platform"),
    "apps.core.audit.AuditEntryManager": (
        "engine: core.audit's own machinery, read by the platform"
    ),
    "apps.core.audit.AuditEntryQuerySet": (
        "engine: core.audit's own machinery, read by the platform"
    ),
    "apps.core.audit.AuditImmutable": ("engine: core.audit's own machinery, read by the platform"),
    "apps.core.authz.ADMIN_RANK": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.CRUD_VERBS": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.EVENT_KINDS_ATTRIBUTE": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.NOUN_SEGMENT": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.OWNER_ROLE": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.READ_ALIAS_VERBS": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.RESERVED_PERMISSIONS": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.ROLE_RANK": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.VIRTUAL_KINDS": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.action_prose": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.actor_role": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.chain_over": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.collection": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.declared_roles": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.default_role_key": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.defaults_for": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.effective_permissions": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.event_kinds_of": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.family_verbs": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.first_party_models": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.grantable_permissions": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.is_org_scoped_kind": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.is_read": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.kind_of": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.kind_of_event": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.kind_registry_of": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.log": ("plumbing: apps.core.authz's own logger"),
    "apps.core.authz.membership_for": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.memberships_in": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.non_conforming": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.policies": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.rank": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.read_kinds": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.read_kinds_by_node": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.refusing_system": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.renamed_permissions": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.replace_permission": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.resolve_renamed": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.role_declarations": (
        "engine: core.authz's own machinery, read by the platform"
    ),
    "apps.core.authz.role_declarers": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.snake_case": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.authz.where_of": ("engine: core.authz's own machinery, read by the platform"),
    "apps.core.blockers.ATTRIBUTE": ("engine: core.blockers's own machinery, read by the platform"),
    "apps.core.blockers.BLOCKER_VERBS": (
        "engine: core.blockers's own machinery, read by the platform"
    ),
    "apps.core.blockers.blockers_for": (
        "engine: core.blockers's own machinery, read by the platform"
    ),
    "apps.core.blockers.declared_blockers": (
        "engine: core.blockers's own machinery, read by the platform"
    ),
    "apps.core.bridge.BuildsWorkflowId": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.ENSURE_IDENTITY_HOME": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.EmitsEvent": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.EnsuresIdentityHome": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.KICK": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.KICK_TENANT": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.KicksTenant": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.KicksUser": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.PLATFORM_CONTEXT": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.PushesToSockets": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.REALTIME_PUSH": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.ReadsPlatformContext": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.ReadsSignatureWindow": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.ReadsWorkflowContext": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.SHAPES": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.SIGNATURE_MATCHES": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.SIGNATURE_V2_MATCHES": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.SIGNATURE_V2_TOLERANCE": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.START_WORKFLOW_ON_COMMIT": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.StartsWorkflowOnCommit": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.VERIFY_AND_STORE": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.VerifiesAndStores": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.VerifiesSignature": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.WORKFLOW_CONTEXT": (
        "engine: core.bridge's own machinery, read by the platform"
    ),
    "apps.core.bridge.WORKFLOW_ID": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.is_registered": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bridge.log": ("plumbing: apps.core.bridge's own logger"),
    "apps.core.bridge.strict": ("engine: core.bridge's own machinery, read by the platform"),
    "apps.core.bulk.MAX_ITEMS": ("engine: core.bulk's own machinery, read by the platform"),
    "apps.core.bulk.check_ids": ("engine: core.bulk's own machinery, read by the platform"),
    "apps.core.concurrency.EPOCH": (
        "engine: core.concurrency's own machinery, read by the platform"
    ),
    "apps.core.concurrency.TICK": (
        "engine: core.concurrency's own machinery, read by the platform"
    ),
    "apps.core.context.ContextUnbound": (
        "engine: core.context's own machinery, read by the platform"
    ),
    "apps.core.context.Door": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.KEYS": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.bound": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.child_of_current": (
        "engine: core.context's own machinery, read by the platform"
    ),
    "apps.core.context.clear": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.from_headers": (
        "engine: core.context's own machinery, read by the platform"
    ),
    "apps.core.context.get": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.hash_session": (
        "engine: core.context's own machinery, read by the platform"
    ),
    "apps.core.context.new_correlation_id": (
        "engine: core.context's own machinery, read by the platform"
    ),
    "apps.core.context.new_id": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.unbind": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.context.value": ("engine: core.context's own machinery, read by the platform"),
    "apps.core.determinism.CANCELLED": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.COMPLETED": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.FAILED": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.FINISH_ACTIVITY": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.FINISH_RETRY": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.FINISH_TIMEOUT": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.REASON_DEPTH": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.ROAD": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.RunFinished": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.cancelled_by_the_server": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.finish_run": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.reason_of": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.determinism.retry_policy": (
        "engine: core.determinism's own machinery, read by the platform"
    ),
    "apps.core.exceptions.BARE_STATUS_CODES": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.BOUNDARIES": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.Boundary": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.CAUSE_LINKS": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.CODE_PATTERN": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.CODE_STATUSES": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.CONNECTION_SQLSTATES": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.CONNECTION_SQLSTATE_CLASS": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.DATABASE_RETRY_AFTER_SECONDS": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.DatabaseUnavailable": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.InvalidCursor": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.NOUN_SLOT": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.REFUSALS": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.REFUSAL_CONTENT_TYPE": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.REFUSAL_EXTRA_MARKER": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.REFUSAL_STATUS_RANGE": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.ROAD": ("engine: core.exceptions's own machinery, read by the platform"),
    "apps.core.exceptions.SearchUnavailable": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.WIRE_COMMON_KEYS": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.as_remedies": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.bare_status_refusals": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.class_for_code": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.database_unavailable": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.declared_by": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.declaring_app": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.envelope_codes": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.fill_noun": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.is_connection_shaped": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.log": ("plumbing: apps.core.exceptions's own logger"),
    "apps.core.exceptions.refusal_extra": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.refusal_for": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.refusal_message": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.remedies_for_noun": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.exceptions.sqlstate_of": (
        "engine: core.exceptions's own machinery, read by the platform"
    ),
    "apps.core.fields.encryption_keys": (
        "engine: core.fields's own machinery, read by the platform"
    ),
    "apps.core.fields.fernet": ("engine: core.fields's own machinery, read by the platform"),
    "apps.core.flags.FLAGS_KEY": ("engine: core.flags's own machinery, read by the platform"),
    "apps.core.idempotency.EMITTABLE": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.EXCEPTION_FOR": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.IN_PROGRESS": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.IdempotencyInProgress": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.IdempotencyKeyReuse": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.IdempotencyMiddleware": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.IdempotencyRecord": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.KEY_REUSE": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.METHODS": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.REPLAYABLE_BELOW": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.REPLAYED_HEADER": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.REQUESTED": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.RESOLVED": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.RESOLVED_TENANT_ATTR": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.TenantResolver": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.UNNAMED": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.acting_tenant": ("door: core.idempotency wires the platform's own door"),
    "apps.core.idempotency.credential_for": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.fingerprint_for": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.purge_expired": (
        "activity: core's workflow writes this from an activity, never a product"
    ),
    "apps.core.idempotency.register_tenant_resolver": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.requested_tenant": (
        "door: core.idempotency wires the platform's own door"
    ),
    "apps.core.idempotency.scope_for": ("door: core.idempotency wires the platform's own door"),
    "apps.core.lifecycle.LIFECYCLE_ATTR": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.declared_lifecycles": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.declared_populations": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.lifecycle_of": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.population_sources": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.third_party_lifecycles": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.lifecycle.undeclared_models": (
        "engine: core.lifecycle's own machinery, read by the platform"
    ),
    "apps.core.log.REDACTED": ("engine: core.log's own machinery, read by the platform"),
    "apps.core.mcp.ARGUMENT_SENTENCES": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.CEILING_WRAPPED_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.InvalidArguments": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.LISTING_WRAPPED_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.MCP_PATH": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.NO_CEILING_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.NotAuthenticated": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.Principal": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.SCOPE_KEY": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.SERIALIZED_OUTPUT_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.STRICT_WRAPPED_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.SURFACE_LISTING_ATTR": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.TOOL_ERROR_SENTENCE": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.TOOL_SCOPE_SENTENCE": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.TOOL_WRITE_INCLUDES_READ": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.acting_org": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.ceiling_of": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.ceiling_refusal": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.described_with_scope": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.forbid_unknown_arguments": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.install_ceiling_gate": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.install_scope_lines": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.install_serialized_output_schemas": (
        "door: core.mcp wires the platform's own door"
    ),
    "apps.core.mcp.install_strict_arguments": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.install_surface_listing": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.listed_here": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.principal": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.rate_limit_refusal": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.reaches_no_capability": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.refuse_off_surface": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.refuse_out_of_ceiling": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.refuse_unstructured_results": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.register": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.register_tenancy_tools": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.release_connections": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.reset_scope_derivation": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.scope_for_tool": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.serialize_output_schemas": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.service_verbs": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.surface_named": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.surface_refusal": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.tool_scopes": ("door: core.mcp wires the platform's own door"),
    "apps.core.mcp.twin_of": ("door: core.mcp wires the platform's own door"),
    "apps.core.middleware.AUTHORIZATION_HEADER": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.ActingUser": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.AddressingHeaderNotHonoured": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.AmbiguousTenant": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.CORRELATION_ID_HEADER": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.ContextMiddleware": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.HOST_HEADER": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.ORG_HEADER": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.REQUEST_ID_HEADER": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.SIGNED_DOOR_UNREAD_HEADERS": (
        "door: the headers the platform's signed-door check refuses"
    ),
    "apps.core.middleware.SignedDoorRefusal": (
        "door: the refusal-factory type `declare_signed_door` takes"
    ),
    "apps.core.middleware.TENANT_HEADER": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.TenantMiddleware": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.addressing_refusal": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.request_addressing_refusal": (
        "door: core.middleware wires the platform's own door"
    ),
    "apps.core.middleware.resolve_tenant": ("door: core.middleware wires the platform's own door"),
    "apps.core.middleware.was_sent": ("door: core.middleware wires the platform's own door"),
    "apps.core.models.APPEND_ONLY_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.ARCHIVABLE_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.ARCHIVED_AT": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.ARCHIVED_BY": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.ARCHIVE_SCOPE_ALL": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.ARCHIVE_SCOPE_ARCHIVED": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.ARCHIVE_SCOPE_LIVE": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.AUTHZ_KIND_DERIVED": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.DUPLICABLE_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.DUPLICATE_KEY_CHECK_ID": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.DUPLICATE_KEY_CONSTRAINT": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.DuplicateKeyField": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.Invitation": (
        "row: core's tenancy services own it; read it through pilecap.tenancy"
    ),
    "apps.core.models.MERGEABLE_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.MOVABLE_ATTR": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.MembershipQuerySet": (
        "row: core's tenancy services own it; read it through pilecap.tenancy"
    ),
    "apps.core.models.ORG_FIELD": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.PATH_ALPHABET": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.PATH_MAX_DEPTH": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.PATH_MAX_LENGTH": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.PATH_SEGMENT_LIMIT": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.PATH_SEGMENT_WIDTH": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.PATH_SEPARATOR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.PathOverflow": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.ROOT_SEGMENT": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.Role": (
        "row: core's tenancy services own it; read it through pilecap.tenancy"
    ),
    "apps.core.models.RolePermission": (
        "row: core's tenancy services own it; read it through pilecap.tenancy"
    ),
    "apps.core.models.VERSIONED_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.WALL_GUARD_ATTR": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.archivable_models": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.decode_path_segment": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.encode_path_segment": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.is_archivable": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_duplicable": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_inherited_downward": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.is_mergeable": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_movable": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_org_scoped": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_versioned": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.models.is_wall_guarded": (
        "engine: core.models's own machinery, read by the platform"
    ),
    "apps.core.models.path_depth": ("engine: core.models's own machinery, read by the platform"),
    "apps.core.money.CURRENCY_LENGTH": ("engine: core.money's own machinery, read by the platform"),
    "apps.core.money.DECIMAL_PLACES": ("engine: core.money's own machinery, read by the platform"),
    "apps.core.money.DEFAULT_CURRENCY": (
        "engine: core.money's own machinery, read by the platform"
    ),
    "apps.core.money.MAX_DIGITS": ("engine: core.money's own machinery, read by the platform"),
    "apps.core.policies.ACTION_PROSE": (
        "engine: core.policies's own machinery, read by the platform"
    ),
    "apps.core.policies.ADMINISTERS_THE_NODE": (
        "engine: core.policies's own machinery, read by the platform"
    ),
    "apps.core.policies.POLICIES": ("engine: core.policies's own machinery, read by the platform"),
    "apps.core.policies.RENAMED_PERMISSIONS": (
        "engine: core.policies's own machinery, read by the platform"
    ),
    "apps.core.roads.JOB_KEY": ("engine: core.roads's own machinery, read by the platform"),
    "apps.core.roads.REGISTRY": ("engine: core.roads's own machinery, read by the platform"),
    "apps.core.roads.T": ("plumbing: apps.core.roads's own type variable"),
    "apps.core.roles.ROLES": ("engine: core.roles's own machinery, read by the platform"),
    "apps.core.schedules.ID_SEPARATOR": (
        "engine: core.schedules's own machinery, read by the platform"
    ),
    "apps.core.schedules.PLATFORM_SEGMENT": (
        "engine: core.schedules's own machinery, read by the platform"
    ),
    "apps.core.schedules.daily_purge": (
        "engine: core.schedules's own machinery, read by the platform"
    ),
    "apps.core.schedules.platform_id": (
        "engine: core.schedules's own machinery, read by the platform"
    ),
    "apps.core.schemas.ARCHIVER_ID": ("engine: core.schemas's own machinery, read by the platform"),
    "apps.core.schemas.FlagIn": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.FlagsOut": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.GrantIn": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.GrantOut": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.GrantPage": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.HeldPermissionOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.InvitationAcceptIn": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.InvitationFilter": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.InvitationIn": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.InvitationIssuedOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.InvitationOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.InvitationPage": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.MembershipFilter": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.MembershipIn": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.MembershipOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.MembershipPage": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.MembershipPermissionsOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.MembershipRolePatch": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationFilter": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationIn": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationMoveIn": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationPage": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.OrganizationPatch": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.PERSONAL_KEY": (
        "engine: core.schemas's own machinery, read by the platform"
    ),
    "apps.core.schemas.PermissionFilter": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.PermissionOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.PermissionPage": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.PingOut": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RoleFilter": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RoleIn": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RoleOut": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RolePage": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RolePatch": ("door: a shape of core's own tenancy door, not a product's"),
    "apps.core.schemas.RolePermissionsIn": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.SHOW_WORDS": ("engine: core.schemas's own machinery, read by the platform"),
    "apps.core.schemas.TenantSettingsIn": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.TenantSettingsOut": (
        "door: a shape of core's own tenancy door, not a product's"
    ),
    "apps.core.schemas.per_viewer_paths": (
        "engine: core.schemas's own machinery, read by the platform"
    ),
    "apps.core.schemas.personal_paths": (
        "engine: core.schemas's own machinery, read by the platform"
    ),
    "apps.core.schemas.without_per_viewer": (
        "engine: core.schemas's own machinery, read by the platform"
    ),
    "apps.core.service.AUDIT_OBJECT_ATTR": (
        "engine: core.service's own machinery, read by the platform"
    ),
    "apps.core.service.DEFAULT_LOG_KEYS": (
        "engine: core.service's own machinery, read by the platform"
    ),
    "apps.core.service.INPUT_KEY": ("engine: core.service's own machinery, read by the platform"),
    "apps.core.service.log": ("plumbing: apps.core.service's own logger"),
    "apps.core.service.redact": ("engine: core.service's own machinery, read by the platform"),
    "apps.core.service.trace_id": ("engine: core.service's own machinery, read by the platform"),
    "apps.core.service.write_audit": ("engine: core.service's own machinery, read by the platform"),
    "apps.core.services.grants.rename_permission_rows": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.services.invitations.hash_invitation_token": (
        "token: the core door hashes or checks this credential; a product never holds one"
    ),
    "apps.core.services.invitations.redact_invitations": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.services.memberships.known_role_keys": (
        "engine: core.services.memberships's own machinery, read by the platform"
    ),
    "apps.core.services.memberships.role_label": (
        "engine: core.services.memberships's own machinery, read by the platform"
    ),
    "apps.core.services.sockets.close_sockets": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.core.services.sockets.close_sockets_on_commit": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.core.services.sockets.close_tenant_sockets": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.core.services.sockets.close_tenant_sockets_on_commit": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.core.services.sockets.kick_if_reads_narrowed": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.core.services.tenants.close_tenant": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.services.tenants.create_first_tenant": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.services.tenants.resume_tenant": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.services.tenants.suspend_tenant": (
        "tenant-lifecycle: an operator's write over a whole tenant, run by commands"
    ),
    "apps.core.surfaces.ALL": ("engine: core.surfaces's own machinery, read by the platform"),
    "apps.core.surfaces.DECLARATION_ATTRIBUTE": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.DECLARATION_MODULE": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.FORWARDED_HOST_HEADER": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.IMPLICIT_STAFF": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.Members": ("engine: core.surfaces's own machinery, read by the platform"),
    "apps.core.surfaces.PUBLIC_BASE_URL_SETTING": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.SURFACE_KEY": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.SurfaceDoesNotExpose": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.SurfaceUnknownHost": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.TENANT_RULES": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.TENANT_SLOT": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.TenantRule": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.claimed_elsewhere": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.does_not_expose": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.request_host": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.resolve_surface": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.surface_base_urls": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.surface_hosts": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.tenant_from_host": (
        "engine: core.surfaces's own machinery, read by the platform"
    ),
    "apps.core.surfaces.union": ("engine: core.surfaces's own machinery, read by the platform"),
    "apps.core.types.ProbeOutcome": (
        "wire: a payload of core's own workflows, built only by the platform"
    ),
    "apps.core.types.Swept": (
        "wire: a payload of core's own workflows, built only by the platform"
    ),
    "apps.core.verbs.ANY_MARKER": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.DUPLICATE_PLATFORM_FIELDS": (
        "engine: core.verbs's own machinery, read by the platform"
    ),
    "apps.core.verbs.HISTORY_NOT_OWED_FOR": (
        "engine: core.verbs's own machinery, read by the platform"
    ),
    "apps.core.verbs.HOOK_ATTRIBUTES": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.HOOK_MODULES": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.Road": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.SUBJECT_FIELD": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.SUBJECT_SEPARATOR": (
        "engine: core.verbs's own machinery, read by the platform"
    ),
    "apps.core.verbs.TOOL_FORMS": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.UNCOUNTABLE": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.UnderivableName": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.declared_hooks": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.declared_models": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.derived_children": (
        "engine: core.verbs's own machinery, read by the platform"
    ),
    "apps.core.verbs.duplicate_fields": (
        "engine: core.verbs's own machinery, read by the platform"
    ),
    "apps.core.verbs.hook": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.landing_for": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.owned_children": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.plural": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.repointers_for": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.road_population": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.split_url_name": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.core.verbs.takes": ("engine: core.verbs's own machinery, read by the platform"),
    "apps.djb_imports.selectors.get_import_source": (
        "engine: djb_imports.selectors's own machinery, read by the platform"
    ),
    "apps.djb_imports.selectors.list_unsettled_rows": (
        "engine: djb_imports.selectors's own machinery, read by the platform"
    ),
    "apps.djb_imports.services.apply_import_row": (
        "activity: djb_imports's workflow writes this from an activity, never a product"
    ),
    "apps.djb_imports.services.finish_import": (
        "activity: djb_imports's workflow writes this from an activity, never a product"
    ),
    "apps.djb_imports.services.purge_imports": (
        "activity: djb_imports's workflow writes this from an activity, never a product"
    ),
    "apps.djb_imports.services.record_import_failure": (
        "activity: djb_imports's workflow writes this from an activity, never a product"
    ),
    "apps.djb_imports.services.record_import_preview": (
        "activity: djb_imports's workflow writes this from an activity, never a product"
    ),
    "apps.djb_imports.types.ApplyImport": (
        "wire: a payload of djb_imports's own workflows, built only by the platform"
    ),
    "apps.djb_imports.types.CheckImport": (
        "wire: a payload of djb_imports's own workflows, built only by the platform"
    ),
    "apps.djb_imports.types.ImportFailed": (
        "wire: a payload of djb_imports's own workflows, built only by the platform"
    ),
    "apps.djb_imports.types.PurgeImports": (
        "wire: a payload of djb_imports's own workflows, built only by the platform"
    ),
    "apps.djb_imports.types.PurgeOutcome": (
        "wire: a payload of djb_imports's own workflows, built only by the platform"
    ),
    "apps.djb_tags.selectors.get_subject": (
        "engine: djb_tags.selectors's own machinery, read by the platform"
    ),
    "apps.events.selectors.list_active_endpoints_everywhere": (
        "engine: events.selectors's own machinery, read by the platform"
    ),
    "apps.events.selectors.list_outbox_to_replay": (
        "engine: events.selectors's own machinery, read by the platform"
    ),
    "apps.events.selectors.list_stranded_outbox": (
        "engine: events.selectors's own machinery, read by the platform"
    ),
    "apps.events.selectors.list_undispatched_outbox": (
        "engine: events.selectors's own machinery, read by the platform"
    ),
    "apps.events.services.close_outbox": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.dead_letter_delivery": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.enqueue_dispatch": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.enqueue_replay": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.purge_deliveries": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.purge_dispatched_outbox": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.record_delivery_attempt": (
        "activity: events's workflow writes this from an activity, never a product"
    ),
    "apps.events.services.record_event": (
        "engine: events.services's own machinery, read by the platform"
    ),
    "apps.events.types.CloseOutbox": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DeadLetter": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DeliverWebhook": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DeliveryOutcome": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DeliveryTarget": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DispatchEvent": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.DispatchOutcome": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.IndexSearch": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.LoadedTargets": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.PurgeExpired": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.PurgeOutcome": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.PushRealtime": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.ReconcileOutbox": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.events.types.ReconcileOutcome": (
        "wire: a payload of events's own workflows, built only by the platform"
    ),
    "apps.exports.services.finish_export": (
        "activity: exports's workflow writes this from an activity, never a product"
    ),
    "apps.exports.services.mark_export_running": (
        "activity: exports's workflow writes this from an activity, never a product"
    ),
    "apps.exports.services.purge_exports": (
        "activity: exports's workflow writes this from an activity, never a product"
    ),
    "apps.exports.services.record_export_failure": (
        "activity: exports's workflow writes this from an activity, never a product"
    ),
    "apps.exports.types.BuildExport": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.exports.types.ExportBuilt": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.exports.types.ExportFailed": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.exports.types.PurgeExports": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.exports.types.PurgeOutcome": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.exports.types.RunFinished": (
        "wire: a payload of exports's own workflows, built only by the platform"
    ),
    "apps.files.services.archive_emptied_file": (
        "activity: files's workflow writes this from an activity, never a product"
    ),
    "apps.files.services.purge_pending_versions": (
        "activity: files's workflow writes this from an activity, never a product"
    ),
    "apps.files.services.record_stored": (
        "activity: files's workflow writes this from an activity, never a product"
    ),
    "apps.files.services.store_bytes": (
        "activity: files's workflow writes this from an activity, never a product"
    ),
    "apps.files.services.store_stream": (
        "activity: files's workflow writes this from an activity, never a product"
    ),
    "apps.files.types.FinalizeUpload": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.files.types.RunFinished": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.files.types.StoreMeasurement": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.files.types.SweepOutcome": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.files.types.SweepPendingUploads": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.files.types.VerifiedObject": (
        "wire: a payload of files's own workflows, built only by the platform"
    ),
    "apps.realtime.selectors.list_subtree_org_ids": (
        "socket: sockets are closed and narrowed by the spine itself, never by a product"
    ),
    "apps.realtime.services.issue_socket_ticket": (
        "token: the socket door's one-use ticket, minted by its own route"
    ),
    "apps.realtime.services.redeem_socket_ticket": (
        "token: the socket door's one-use ticket, taken by its own middleware"
    ),
    "apps.realtime.types.RedactSocketCredentials": (
        "door: the socket door's log filter, installed by the settings"
    ),
    "apps.search.selectors.list_visible_org_ids": (
        "engine: search.selectors's own machinery, read by the platform"
    ),
    "apps.search.services.announce_degraded": (
        "engine: search.services's own machinery, read by the platform"
    ),
    "apps.search.services.announce_recovered": (
        "engine: search.services's own machinery, read by the platform"
    ),
    "apps.search.services.delete_tenant_documents": (
        "engine: search.services's own machinery, read by the platform"
    ),
    "apps.search.types.EngineConfiguration": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.search.types.EngineHit": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.search.types.EngineHits": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.search.types.ReconcileIndexes": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.search.types.ReconcileOutcome": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.search.types.SearchEngine": (
        "wire: a payload of search's own workflows, built only by the platform"
    ),
    "apps.usage.meters.MAX_METER_LENGTH": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.NAME_SEGMENTS": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.check_meter": ("engine: usage.meters's own machinery, read by the platform"),
    "apps.usage.meters.check_reported_meters": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.declared_meters": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.every_declared_meter": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.example_meter": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.grammar_complaint": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.usage.meters.validate_declared_meters": (
        "engine: usage.meters's own machinery, read by the platform"
    ),
    "apps.workflows.services.check_org_agreement": (
        "engine: workflows.services's own machinery, read by the platform"
    ),
    "apps.workflows.services.check_workflow_id": (
        "engine: workflows.services's own machinery, read by the platform"
    ),
    "apps.workflows.services.hash_run_input": (
        "engine: workflows.services's own machinery, read by the platform"
    ),
    "apps.workflows.services.purge_finished_runs": (
        "activity: workflows's workflow writes this from an activity, never a product"
    ),
    "apps.workflows.services.record_run": (
        "activity: workflows's workflow writes this from an activity, never a product"
    ),
    "apps.workflows.services.record_run_id": (
        "activity: workflows's workflow writes this from an activity, never a product"
    ),
    "apps.workflows.services.start_replay": (
        "engine: workflows.services's own machinery, read by the platform"
    ),
    "apps.workflows.types.EchoOutput": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
    "apps.workflows.types.MarkRunFinished": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
    "apps.workflows.types.MoveOrganization": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
    "apps.workflows.types.PurgeFinishedRuns": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
    "apps.workflows.types.ReconcileRuns": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
    "apps.workflows.types.SendEmail": (
        "wire: a payload of workflows's own workflows, built only by the platform"
    ),
}
