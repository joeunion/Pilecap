# ADR connections-3

**ADR connections-3 · the connection, not the sender, chooses the signature scheme.**

**Context.** The inbound door verified `X-Signature-V2` when a sender offered it and fell back to
the v1 body-only HMAC when the header was absent (ADR connections-2). So the downgrade was the
sender's choice: a delivery replayed without the timestamped header verified for as long as the
connection's secret lived. The v1 branch carried a dated contraction comment (2027-02-24), and
no row said which connections still needed v1.

**Decision.** The scheme is per connection. `Connection.is_signature_v2_required` is a boolean
field whose default is `True`, **so v2 is required for connections created after 2.5.0**.
Existing rows read `False`: the expand migration `0005_connection_signature_scheme` adds the
column with default `False`, which backfills them, then changes the default to `True`. They keep
v1 until someone flips them. The flip is a service, `set_signature_scheme` (authorized as
`connection.update` at the tenant root). It emits an event only when the value changes, and REST
reaches it at the connection's `signature-scheme` route. The door has no MCP tool, by the
connections app's recorded exemption from rule 17. On a v2-required connection, a correct
`X-Signature` alone is refused with 401 `timestamped_signature_required`, which names
`X-Signature-V2`. That check runs after the digest check, so a wrong signature still gets the
generic invalid-signature answer, and only a holder of the secret learns which scheme is
required. On a `False` row the v1 path is unchanged. The sunset moved from the receiver's comment
to the field's contract line. Built at `908aea787` and `c54be79df`.

**Consequences.** A product sees which connections still accept v1 and turns each one off with a
single call. A new connection to a provider that cannot timestamp needs that one call before its
first delivery. Its v1 deliveries are refused until then.

**Rejected.** A global setting or a release flag, because one legacy provider would pin every
connection to v1, and a provider's capability is persistent per-row configuration, not a release
control. Removing v1 now, because that breaks declared senders without a window, a public-contract
change with no notice.

**Trigger to revisit.** No `False` row remains, or 2027-02-24, whichever comes first. Then the
`False` branch contracts and the field's default becomes the only behaviour.

*Ruled:* 2026-10-23, the per-connection shape (option A of the architect's memo), with the
default as the owner's decision list recommended. Recorded after the build. No owner signature
is required, because this is not an exception to a principle.
