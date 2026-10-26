# ADR connections-1

**ADR connections-1 · RESERVED, ruled in code, never written here
(bookkeeping).** The number is cited in code and its ruling lives
in those docstrings, not in this file: `apps/events/receivers.py` (the module
docstring — "the source is a row" — and the narrowed receiver at `:66`, `:113`,
`:243`), `apps/connections/services.py` (`:82`, `:268`, `:438` — the delivery-id
headers and the narrowing that lets the probe offer the row),
`apps/connections/models.py` (`:173`, `:190`), the migration
`apps/connections/migrations/0002_inboundwebhook_delivery_id_and_more.py`, and
the tests `apps/connections/tests/test_api.py` (`:424`, `:564`),
`apps/connections/tests/test_discovery.py:221` and
`apps/events/tests/test_receivers.py:9`. Nothing is reconstructed here — read
those docstrings for the ruling. **The number is reserved**: no future ADR in
the `connections` run may take `connections-1`, which is why `connections-2` was
the next free number when D4 landed.
