# ADR example_portal-1

- **ADR example_portal-1 (the customer face reads the staff noun) ·
  2026-09-30** · **context:** the customer surface's worked example needs a
  noun of its own beside a read of the staff noun · **decision:**
  `example_portal` declares `depends_on` on `example` and reads `Widget`
  through `apps.example.selectors.get_widget`, never its model; a
  `PortalRequest` lands at the customer's acting hat and names its widget by
  `PROTECT`; a widget merge carries the requests to the survivor through the
  portal's own repointer (`example_portal.portal_request.moved`) · **rejected:**
  `PortalRequest` inside `apps/example` (two teams in one app — the collision
  A1 is shaped around); an event from `example` the portal consumes (a read,
  not a reaction) · trigger to revisit: `example` needs to read
  `example_portal` back.
