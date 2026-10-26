# ADR example-3

- **ADR example-3 (drop the WidgetOut aliases)** *(Widget gains
  `owner_email`/`organization_slug` model properties, and the parity
  test's key-set is exact)* · context: a
  REST-vs-MCP body divergence traced to serializer aliases · decision:
  drop WidgetOut aliases (comms precedent: model properties); the parity
  test compares WIRE shapes (REST `response.json()` vs MCP
  `structuredContent`). Stated break: MCP clients on dotted keys —
  accepted; REST is the contract (E1) · rejected: keeping the aliases
  with a translation layer (a second contract language) · trigger to
  revisit: none — superseded only by a v2 contract decision.
