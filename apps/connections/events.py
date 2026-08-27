"""The names of the things this app says happened.

`<app>.<noun>.<past-tense verb>` (house rule 16), declared once so that a
subscriber matches on a constant rather than on a literal somebody will retype.
`introspect` reports this file, so a client can read the list of events it may
subscribe to without reading the source.

Every payload carries `v`. A subscriber that has to guess which shape it is
looking at is a subscriber that breaks on the next field.
"""

from __future__ import annotations

# The payload version every event in this app carries.
V = 1

CONNECTION_CREATED = "connections.connection.created"
CONNECTION_CREDENTIALS_UPDATED = "connections.connection.credentials_updated"
CONNECTION_REVOKED = "connections.connection.revoked"

# Something arrived from the outside, was signature-verified, and was stored.
# The payload is the receipt (`InboundWebhookOut`) — never the body: an event
# fans out to every subscribed endpoint, and the body is the one part of an
# inbound webhook that might carry somebody else's customer data.
WEBHOOK_RECEIVED = "connections.webhook.received"
