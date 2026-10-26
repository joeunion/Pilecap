# Threat model and HIPAA 164.312 control map

> **The populations are DERIVED, then pinned. Do not hand-edit the lists; write the row.**
>
> ```
> .venv/bin/python scripts/threat_census.py
> ```
>
> re-derives the doors (the closed set `CLAUDE.md` names), the nouns (every model
> `manage.py introspect` reports for an app under `apps/`) and each noun's
> `personal()` fields, and **exits 2 when a door or a noun has no row, when a
> classification drops a personal field, when a HIPAA row is empty, or when a
> cited `file:line`, `file::name` or `file::test` does not resolve**. The gate runs it as the
> `threat-census` leg (static unit, full mode). It checks presence and
> citation, never truth: a row can be present, cited and wrong, and the pentest
> is the discovery.
>
> **Cell grammar.** A mechanism is a backticked `path::name` where a definition holds it,
> else a backticked `path:line` (or `path:first-last`) that lands on a line that says something;
> a pinning test is a backticked `path::test_name`; a hole is `open: <row id>` in
> the STRIDE grid and `gap: <row id>` in the HIPAA map, the id a queue row.
> **This is a product's ledger.** It ships as a skeleton with the platform's rows
> kept and one worked noun row; a product adds a row per noun it introduces.

## § Trust boundaries

| boundary | from → to | what crosses | the control at the line |
|---|---|---|---|
| the edge | browser → Caddy | TLS, HSTS, the one public listener; the client's address survives the hop — uvicorn believes `X-Forwarded-For` only from this stack's own network, a subnet the env file declares once and compose reads twice, and the entrypoint refuses to boot behind the proxy with it unset or `*` | `deploy/Caddyfile:71` · `deploy/provision.sh::edge_subnet` · `deploy/compose.yaml:1132` · `deploy/entrypoint.sh:253-255` |
| the face | Caddy → Next | page requests; the frontend holds no credential and proxies one origin | `deploy/Caddyfile:98` |
| the API | Caddy/Next → Django | session cookie or bearer, `X-Tenant`/`X-Org` addressing | `deploy/Caddyfile:87` · `apps/core/middleware.py::TenantMiddleware` |
| the store | Django → Postgres | every scoped read through `for_tenant` | `apps/core/models.py::ScopedQuerySet.for_tenant` |
| the cache and channel layer | Django → Redis | throttle counters, socket groups | `apps/core/throttling.py::Recording._spend` · `apps/realtime/bridge.py::group_for` |
| the run | Django → Temporal | tenant, user and hat as headers, revalidated per activity | `apps/workflows/context.py::TenantContextInterceptor` |
| the index | Django → Meilisearch | documents and a filter built from resolved ids only | `apps/search/engine.py::scope_expression` |
| the bytes | Django → MinIO | presigned URLs with a declared lifetime | `apps/files/storage.py::download_url_ttl` |
| the issuer | Zitadel → Django | ID tokens and access tokens: signature, issuer, audience, expiry | `apps/accounts/oauth.py::claims` |
| the sink | Django → ClickStack | OTLP logs and traces; arguments redacted by allow-list | `apps/core/service.py::redact` |
| outbound webhooks | Django → a subscriber's URL | signed event payloads with no personal field | `apps/events/activities.py::sign_v2` · `apps/events/services.py::_refuse_personal_fields` |
| inbound webhooks | a provider → Django | signed bodies on a door that takes no address | `apps/connections/api.py::_signature_verified` |

## § STRIDE per door

| door | spoofing | tampering | repudiation | information disclosure | denial of service | elevation of privilege |
|---|---|---|---|---|---|---|
| REST | session or bearer, resolved per request: `apps/accounts/auth.py::ApiTokenAuth` · `apps/accounts/auth.py::SessionCookieAuth` | strict bodies refuse an unknown field: `apps/core/schemas.py::StrictIn`; idempotent replays: `apps/core/idempotency.py::IdempotencyMiddleware` | one audit row per service call: `apps/core/service.py::write_audit` | tenant and branch scoping fail closed: `apps/core/models.py::ScopedQuerySet.for_tenant` · `apps/core/models.py::ScopedQuerySet.visible_to`; not-there and not-yours are one answer: `apps/core/authz.py::may_be_named` | per-scope throttles: `apps/core/throttling.py::default_throttles`; the 503 on an exhausted pool: `config/api.py::on_operational_error` | every write asks the registry: `apps/core/authz.py::require`; the hat is revalidated per request: `apps/core/middleware.py::resolve_org` |
| MCP | API token or Zitadel JWT at the edge: `config/mcp.py::TokenAuthMiddleware` · `apps/accounts/oauth.py::authenticate_bearer` | the same strict schemas as REST: `apps/core/schemas.py::StrictIn` | the same audit row as REST: `apps/core/service.py::write_audit` | a token's scope ceiling: `apps/core/mcp.py::ceiling_refusal`; the principal carries the tenant: `apps/core/mcp.py::principal` | the shared throttle bucket: `config/mcp.py::ThrottleMiddleware` · `apps/core/mcp.py::rate_limit_refusal` | out-of-ceiling tools refused: `apps/core/mcp.py::refuse_out_of_ceiling`; the registry: `apps/core/authz.py::require` |
| sockets | the credential wrapper on every pattern: `apps/realtime/middleware.py::TokenAuthMiddlewareASGI` | the client sends nothing that writes — a non-ping closes: `apps/realtime/consumers.py::TenantEventsConsumer.receive_json` | joins and kicks are logged: `apps/realtime/consumers.py::TenantEventsConsumer.connect` · `apps/realtime/consumers.py::TenantEventsConsumer.realtime_kick` | groups derived from resolved ids, never the client: `apps/realtime/bridge.py::tenant_group` · `apps/realtime/bridge.py::group_for` | a join past the credential's or the tenant's cap is refused before the group join: `apps/realtime/consumers.py::take_seat` | a revoked person is kicked: `apps/realtime/bridge.py::kick_user` |
| webhooks in | the signature over the bytes that arrived: `apps/connections/api.py::_signature_verified` | the same signature, with a replay tolerance: `apps/connections/api.py::signature_v2_tolerance` | the received row keeps its signature headers: `apps/connections/services.py::record_inbound_webhook` | an unknown connection answers exactly as a bad signature: `apps/connections/api.py::receive_webhook` | a provider's delivery id deduplicates: `apps/connections/services.py::_delivery_id` | the signed door takes no tenant address: `apps/connections/api.py::SignedDoorTakesNoAddress` |
| webhooks out | we sign; a subscriber verifies: `apps/events/activities.py::sign_v2` | the signature covers the body and timestamp: `apps/events/activities.py::signed_payload_v2` | every attempt is recorded: `apps/events/services.py::record_delivery_attempt` | no personal field in a payload: `apps/events/services.py::_refuse_personal_fields`; an endpoint target that is or resolves to a private, link-local, loopback or non-global address is refused at the door, the service and delivery: `apps/events/targets.py::refuse_private_target` | retry only what is worth retrying, then dead-letter: `apps/events/activities.py::is_worth_retrying` · `apps/events/activities.py::dead_letter_delivery` | registering an endpoint is an authorized service: `apps/events/services.py::register_endpoint` |
| workflows | the principal travels as headers, set by the interceptor: `apps/workflows/context.py::TenantContextInterceptor` | the run's input is a dataclass decoded from headers: `apps/workflows/context.py::_decode`; workflow code imports only the deterministic surface: `apps/core/determinism.py:1` | a run is a `WorkflowRun` row and every activity write an audit row: `apps/core/service.py::write_audit` | a run that stamped no tenant is refused: `apps/workflows/context.py::workflow_context` | retry floors and the one retry policy: `apps/core/retry.py::retry_floor_seconds` · `apps/core/determinism.py::retry_policy` | the person and the hat are revalidated at each activity: `apps/workflows/context.py::_revalidate_person` · `apps/workflows/context.py::_revalidate_hat` |

## § Nouns

The classification names every field the noun's `Out` marks `personal(...)` (house
rule 93); the doors are where the noun is answered; the authz actions are the
registry's for its kind (`manage.py introspect`'s `policies`); the audit actions
are the services that write it — an audit row's `action` is the service's name
(`apps/core/audit.py:10`).

| noun | classification | doors | authz actions | audit actions |
|---|---|---|---|---|
| `accounts.ApiToken` | no personal mark on its Out; secret: `key_hash` (a digest; the token is shown once) | REST | `api_token.create`, `api_token.delete`, `api_token.read`, `api_token.update` | `issue_token`, `revoke_token` |
| `accounts.FirstAdminVouch` | no personal mark on its Out | none (internal) | `first_admin_vouch.create`, `first_admin_vouch.delete`, `first_admin_vouch.read`, `first_admin_vouch.update` | `issue_first_admin_vouch`, `mark_first_admin_vouch_spent` |
| `accounts.IdentityBranding` | no personal mark on its Out | none (internal) | `identity_branding.create`, `identity_branding.delete`, `identity_branding.read`, `identity_branding.update` | `set_identity_branding` |
| `accounts.IdentityHome` | no personal mark on its Out | sockets, webhooks out (events) | `identity_home.create`, `identity_home.delete`, `identity_home.read`, `identity_home.update` | `start_identity_home`, `sync_identity_home` |
| `accounts.SsoConnection` | no personal mark on its Out | none (internal) | `sso_connection.create`, `sso_connection.delete`, `sso_connection.disable`, `sso_connection.read`, `sso_connection.update` | `create_sso_connection`, `disable_sso_connection`, `update_sso_connection` |
| `accounts.SsoDomain` | no personal mark on its Out | none (internal) | `sso_domain.create`, `sso_domain.delete`, `sso_domain.read`, `sso_domain.update`, `sso_domain.verify` | `verify_sso_domain` |
| `accounts.SsoIdentity` | no personal mark on its Out | none (internal) | `sso_identity.create`, `sso_identity.delete`, `sso_identity.read`, `sso_identity.update` | `provision_sso_identity` |
| `accounts.User` | personal: `email` | REST, MCP | `user.create`, `user.deactivate`, `user.delete`, `user.erase`, `user.read`, `user.unlink`, `user.update` | `create_user`, `deactivate_user`, `erase_user` |
| `comms.ChannelPreference` | no personal mark on its Out | REST, MCP | `channel_preference.create`, `channel_preference.delete`, `channel_preference.read`, `channel_preference.update` | `grant_consent`, `revoke_consent`, `set_quiet_hours` |
| `comms.DeliveryPolicy` | no personal mark on its Out | REST, MCP | `delivery_policy.create`, `delivery_policy.delete`, `delivery_policy.read`, `delivery_policy.retire`, `delivery_policy.update` | `create_policy`, `retire_policy`, `revise_policy` |
| `comms.Device` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `device.create`, `device.delete`, `device.read`, `device.retire`, `device.update` | `register_device`, `retire_device` |
| `comms.Message` | personal: `recipient_email` | REST, MCP, sockets, webhooks out (events) | `message.cancel`, `message.create`, `message.delete`, `message.read`, `message.record_status`, `message.send`, `message.update` | `cancel_message`, `mark_message_sending`, `record_message_failed`, `record_message_sent` |
| `comms.MessageEngagement` | no personal mark on its Out | REST, MCP | `message_engagement.create`, `message_engagement.delete`, `message_engagement.read`, `message_engagement.update` | `record_engagement` |
| `comms.MessageTemplate` | no personal mark on its Out | REST, MCP | `message_template.create`, `message_template.delete`, `message_template.read`, `message_template.retire`, `message_template.update` | `create_template`, `retire_template`, `revise_template` |
| `comms.Recipient` | personal: `chat_handle`, `display_name`, `email`, `phone` | REST, MCP, sockets, webhooks out (events) | `recipient.archive`, `recipient.create`, `recipient.delete`, `recipient.read`, `recipient.restore`, `recipient.update` | `archive_recipient`, `create_recipient`, `restore_recipient`, `suppress_recipient`, `unsuppress_recipient`, `update_recipient` |
| `comms.SuppressionSurge` | no personal mark on its Out | none (internal) | `suppression_surge.create`, `suppression_surge.delete`, `suppression_surge.read`, `suppression_surge.update` | `close_suppression_surge`, `start_suppression_surge` |
| `connections.Connection` | no personal mark on its Out; secret: `credentials` (encrypted at rest) | REST, sockets, webhooks out (events) | `connection.create`, `connection.delete`, `connection.read`, `connection.receive_webhook`, `connection.revoke`, `connection.update` | `create_connection`, `revoke_connection` |
| `connections.InboundWebhook` | no personal mark on its Out | none (internal) | `inbound_webhook.create`, `inbound_webhook.delete`, `inbound_webhook.read`, `inbound_webhook.update` | `apply_inbound_webhook`, `purge_inbound_webhooks`, `record_inbound_webhook` |
| `core.AuditEntry` | no personal mark on its Out; carries `actor` and redacted arguments (an allow-list, `apps/core/service.py::redact`) | REST, MCP (each noun's `<noun>_history-list`, read only) | `audit_entry.create`, `audit_entry.delete`, `audit_entry.read`, `audit_entry.update` (no door offers a write) | none — every `@service` call writes one row through `write_audit` (`apps/core/service.py::write_audit`); append-only, `apps/core/audit.py::AuditEntry.save` |
| `core.Grant` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `grant.create`, `grant.delete`, `grant.read`, `grant.update` | `create_grant`, `delete_grant` |
| `core.IdempotencyRecord` | no personal mark on its Out | none (internal) | `idempotency_record.create`, `idempotency_record.delete`, `idempotency_record.read`, `idempotency_record.update` | none — no service of its own writes it |
| `core.Invitation` | personal: `email`; secret: `token_hash` (a digest) | REST, MCP | `invitation.create`, `invitation.delete`, `invitation.read`, `invitation.revoke`, `invitation.update` | `accept_invitation`, `redact_invitations`, `revoke_invitation` |
| `core.Membership` | personal: `user_email` | REST, MCP, sockets, webhooks out (events) | `membership.create`, `membership.delete`, `membership.read`, `membership.update` | `add_membership`, `revoke_membership` |
| `core.Organization` | no personal mark on its Out | REST, MCP | `organization.create`, `organization.delete`, `organization.move`, `organization.read`, `organization.update` | `apply_organization_move`, `create_organization`, `move_organization`, `rename_organization` |
| `core.Role` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `role.create`, `role.delete`, `role.read`, `role.update` | `create_role`, `delete_role`, `set_role`, `set_role_collection`, `update_role` |
| `core.RolePermission` | no personal mark on its Out | REST, MCP | none — a delta on a role's collection, authorized under `role.update` and never on its own. No door reaches one of these rows except through the role it belongs | none — no service of its own writes it |
| `core.Tenant` | no personal mark on its Out | REST, MCP | `tenant.create`, `tenant.delete`, `tenant.own`, `tenant.read`, `tenant.update` | `close_tenant`, `create_first_tenant`, `create_tenant`, `resume_tenant`, `suspend_tenant`, `update_tenant_settings` |
| `djb_imports.Import` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `djb_import.apply`, `djb_import.cancel`, `djb_import.create`, `djb_import.delete`, `djb_import.read`, `djb_import.update` | `apply_import`, `apply_import_row`, `cancel_import`, `create_import`, `finish_import`, `purge_imports`, `record_import_failure`, `record_import_preview` |
| `djb_imports.ImportRow` | no personal mark on its Out | REST, MCP | `djb_import.apply`, `djb_import.cancel`, `djb_import.create`, `djb_import.delete`, `djb_import.read`, `djb_import.update` | `apply_import_row` |
| `djb_notes.Note` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `djb_note.archive`, `djb_note.create`, `djb_note.delete`, `djb_note.read`, `djb_note.restore`, `djb_note.update` | `archive_note`, `create_note`, `move_notes`, `restore_note`, `update_note` |
| `djb_tags.Tag` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `djb_tag.archive`, `djb_tag.create`, `djb_tag.delete`, `djb_tag.read`, `djb_tag.restore`, `djb_tag.update` | `archive_tag`, `create_tag`, `create_tag_link`, `delete_tag_link`, `move_tag_links`, `rename_tag`, `restore_tag` |
| `djb_tags.TagLink` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `djb_tag_link.create`, `djb_tag_link.delete`, `djb_tag_link.read`, `djb_tag_link.update` | `create_tag_link`, `delete_tag_link`, `move_tag_links` |
| `events.Delivery` | no personal mark on its Out | REST, MCP | `delivery.create`, `delivery.delete`, `delivery.read`, `delivery.replay`, `delivery.update` | `dead_letter_delivery`, `purge_deliveries`, `record_delivery_attempt` |
| `events.Event` | no personal mark on its Out | REST, MCP | `event.create`, `event.delete`, `event.read`, `event.update` | `record_event` |
| `events.Outbox` | no personal mark on its Out | none (internal) | `outbox.create`, `outbox.delete`, `outbox.read`, `outbox.update` | `close_outbox`, `purge_dispatched_outbox` |
| `events.WebhookEndpoint` | no personal mark on its Out; secret: `secret` (encrypted at rest; no door answers it) | REST, MCP, sockets, webhooks out (events) | `endpoint.create`, `endpoint.deactivate`, `endpoint.delete`, `endpoint.issue_secret`, `endpoint.read`, `endpoint.resume`, `endpoint.update` | `deactivate_endpoint`, `issue_endpoint_secret`, `register_endpoint`, `resume_endpoint`, `update_endpoint` |
| `example.Widget` | personal: `owner_email`, `owner_name` | REST, MCP, sockets, webhooks out (events) | `widget.approve`, `widget.archive`, `widget.create`, `widget.delete`, `widget.merge`, `widget.move`, `widget.onboard`, `widget.read`, `widget.remind`, `widget.restore`, `widget.update` | `announce_widget_onboarded`, `approve_widget`, `archive_widget`, `archive_widget_policy`, `confirm_widget_onboarding`, `create_widget`, `create_widget_policy`, `delete_widget`, `duplicate_widget`, `mark_widget_onboarded`, `mark_widget_reminded`, `merge_widget`, `move_widget`, `record_widget_entry`, `restore_widget`, `restore_widget_policy`, `touch_widget`, `transition_widget`, `update_widget` | <!-- worked example: replace with your noun -->
| `example.WidgetEntry` | no personal mark on its Out | REST, MCP | `widget_entry.create`, `widget_entry.delete`, `widget_entry.read`, `widget_entry.record`, `widget_entry.update` | `record_widget_entry` |
| `example.WidgetPolicy` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `widget_policy.archive`, `widget_policy.create`, `widget_policy.delete`, `widget_policy.read`, `widget_policy.restore`, `widget_policy.update` | `archive_widget_policy`, `create_widget_policy`, `restore_widget_policy` |
| `example_portal.PortalRequest` | personal: `requester_email` | REST, MCP, sockets, webhooks out (events) | `portal_request.create`, `portal_request.delete`, `portal_request.read`, `portal_request.submit`, `portal_request.update` | `move_portal_requests`, `submit_portal_request` |
| `exports.Export` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `export.build`, `export.create`, `export.delete`, `export.read`, `export.update` | `create_export`, `finish_export`, `mark_export_running`, `purge_exports`, `record_export_failure` |
| `files.FileVersion` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `file.archive`, `file.create`, `file.delete`, `file.read`, `file.replace`, `file.restore`, `file.update` | `add_version`, `archive_emptied_file`, `archive_file`, `create_file`, `move_attached_files`, `purge_pending_versions`, `restore_file` |
| `files.StoredFile` | no personal mark on its Out | REST, MCP, sockets, webhooks out (events) | `file.archive`, `file.create`, `file.delete`, `file.read`, `file.replace`, `file.restore`, `file.update` | `add_version`, `archive_emptied_file`, `archive_file`, `confirm_upload`, `create_file`, `issue_download_url`, `move_attached_files`, `purge_pending_versions`, `restore_file` |
| `usage.UsageEntry` | no personal mark on its Out | REST, MCP | `usage_entry.create`, `usage_entry.delete`, `usage_entry.read`, `usage_entry.update` | `record_usage` |
| `workflows.WorkflowRun` | personal: `started_by_email` | REST, MCP | `workflow_run.cancel`, `workflow_run.create`, `workflow_run.delete`, `workflow_run.read`, `workflow_run.replay`, `workflow_run.signal`, `workflow_run.update` | `cancel_run`, `finish_run`, `purge_finished_runs`, `record_run`, `record_run_id` |

## § HIPAA 164.312

| standard | control | mechanism | test that pins it |
|---|---|---|---|
| (a)(1) access control | unique user identification (one `User` per person, one subject per realm); tenant and branch scoping on every read; every write asks the authorization registry; emergency access is the owner role, never a superuser exemption; automatic logoff: a session untouched for the idle window ends and the socket closes on its next ping: `apps/accounts/middleware.py::IdleSessionMiddleware` | `apps/core/models.py::ScopedQuerySet.for_tenant` · `apps/core/models.py::ScopedQuerySet.visible_to` · `apps/core/authz.py::require` | `apps/core/tests/test_permissions_doors.py::test_the_machine_door_answers_not_found_for_another_tenants_row` |
| (b) audit controls | one append-only audit row per service call: who, what, under which hat, through which door, with what outcome | `apps/core/service.py::write_audit` · `apps/core/audit.py::AuditEntry` | `apps/core/tests/test_service.py::test_a_service_call_writes_exactly_one_audit_row` |
| (c)(1) integrity | the audit trail refuses an update or a delete; a versioned row refuses a stale write; strict bodies refuse an unknown field; webhooks are signed both ways | `apps/core/audit.py::AuditEntry.save` · `apps/core/concurrency.py::require_version` · `apps/core/schemas.py::StrictIn` · `apps/events/activities.py::sign_v2` | `apps/core/tests/test_service.py::test_an_audit_row_cannot_be_deleted` · `apps/events/tests/test_signed_delivery.py::test_the_signature_is_over_the_bytes_that_arrived` |
| (d) person or entity authentication | Zitadel hosts every interactive sign-in (PKCE, state); the MCP door validates the JWT's signature, issuer, audience and expiry; machine tokens are stored as digests | `apps/accounts/oauth.py::claims` · `apps/accounts/auth.py::ApiTokenAuth` | `apps/accounts/tests/test_rp_login.py::test_the_authorize_redirect_carries_pkce_and_state` · `apps/accounts/tests/test_mcp_oauth.py::test_a_jwt_is_never_looked_up_as_an_api_token` |
| (e)(1) transmission security | TLS ends at Caddy with HSTS; Django redirects to HTTPS and marks its cookies secure; outbound webhooks are signed over TLS | `deploy/Caddyfile:71` · `config/settings/base.py::SECURE_SSL_REDIRECT` · `config/settings/base.py::SESSION_COOKIE_SECURE` · `apps/events/activities.py::sign_v2` | `quality/tests/deploy/test_transmission.py::test_every_site_block_carries_hsts` · `quality/tests/deploy/test_transmission.py::test_production_redirects_to_https_and_pins_hsts` · `apps/events/tests/test_activities.py::test_the_signature_is_over_the_bytes_that_were_sent` |

## § Pentest brief

One deployed template instance on a throwaway box (the example app, two tenants, three roles), all five doors and Zitadel, grey-box for one week; out of scope are the owner's AWS account, ClickStack and Temporal Cloud. The tester receives this file, the OpenAPI document, the MCP tool list, one admin and one member credential in each tenant, an MCP bearer, the SBOMs and the capacity runbook's envelope line so they know the knee before they load it. We expect back findings mapped to this file's rows — a finding with no row is a finding about the model — each with a severity and a reproduction, and a retest within 30 days of our fixes. When: the week after the 2.5.0 tag, before the next product clones it.
