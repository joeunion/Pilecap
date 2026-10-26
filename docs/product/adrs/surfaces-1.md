# ADR surfaces-1

- **ADR surfaces-1 (one product, several audiences) · 2026-09-30** ·
  **context:** a product needed staff and customer faces on one set of
  records; the template answered at one host with one router, one tenant rule
  and one audience — an assumption never decided · **decision:** a SURFACE is
  a host bound by environment (`SURFACE_HOSTS`) to a product-declared exposure
  — `apps/<label>/surfaces.py` exporting `SURFACES`, found by the one
  discovery walk: scope families (tools and sockets derived), acts, admitted
  role keys (a role belongs to one declared surface), a tenant rule
  (`addressed | host | membership` — a required field with no default; the
  worked customer surface declares `membership`) and the screens the one face draws from a folder of its own —
  resolved once per request by the doors before the tenant
  (`roads resolve_surface`; the socket and MCP doors read the host through
  `roads request_host`, which honours `X-Forwarded-Host` only where
  `USE_X_FORWARDED_HOST` is on), carried on the actor and the audit row like
  the hat, refused as `surface_does_not_expose` (404) on a door it does not
  expose and `surface_unknown_host` (404) on a host no binding names; every
  URL the system builds for a person goes through one builder with the surface
  of the role the link is for (`roads absolute_url`, `roads surface_for_role`);
  sessions are per host; the platform's `staff` surface is implicit and total,
  so an undeclared product is byte-identical to before; one stack, one Caddy
  site block, one face build · **rejected:** a settings-block declaration
  (`config/**` is the template's); routes or tools listed by name (an open
  set); 403 (it tells a customer the door exists); two face builds (one
  document, one generated client and one byte-pin — a second build is a
  second client to keep in step, where one build asks its surface at boot)
  [derived by the docs rung from S.1 item 10 and fe-conventions § 9; confirmed
  by the lead 2026-10-01]; a `Surface` model (a host map is read before any row exists); a shared cookie
  domain (a staff session on a customer host); a platform for unrelated
  products (two products are two clones — one database is one schema, one
  migration owner and one worker); separate deployments over one database (two owners of migrations
  and the worker) · **consequences:** (a) **the wall is the role, the offer is
  the surface.** `Surface.acts` narrows what a face is OFFERED
  (`allowed_acts`); whether a press succeeds is the role's permission set. A
  role a declared surface admits holds exactly what its declaration says; the
  platform's own roles keep the un-swept predicate residue until the
  consolidation's sweep, and the flat census's `residue` section
  (`apps/core/tests/permissions_world.py::residue`) is that count
  (`core.authz._attach_default_roles`, clause (5)). Declared edge: a product
  that DECLARES `staff` naming some roles leaves a role no surface names
  holding the residue, though no surface admits it. (b) **The base URLs derive
  once**, in `apps/core/surfaces.py::surface_base_urls()`, built by
  `absolute_url`; the seed registers them and the audit declares them. The
  settings-side `_surface_origins` (`config/settings/base.py`) is the declared
  exception — settings are read before the app registry exists, so they may
  not import `apps` — and repeats `absolute_url`'s scheme-and-port reading;
  each side is pinned by its own tests
  (`apps/accounts/tests/test_identity_home.py::test_the_audit_declares_the_seeds_own_redirect_uris_and_the_reconciler_asks_nothing`
  for the seed against the audit,
  `apps/core/tests/test_settings.py::test_every_bound_surface_origin_is_a_trusted_origin`
  and `::test_the_csp_form_action_admits_every_surfaces_redirect_origin` for
  the settings), and no one test compares the two derivations. (c) **The
  forwarded host is a development fact.** Only `config/settings/local.py`
  turns `USE_X_FORWARDED_HOST` on, for the face's dev proxy; under it a client
  that calls Django directly can choose its audience with a forged header, and
  authentication still applies after the surface. **The doors disagree on a
  repeated `Host`**: the HTTP door refuses it (Django joins the values with
  `,`, which no host validates), while the socket and MCP doors take the first
  (`request_host`) — a disagreement between doors, named here as one. The
  host has one road (`roads request_host`); the other headers the ASGI doors
  read by name (the tenant, the hat, the credential, the correlation ids) have
  none — `core.asgi_middleware`'s
  `_requested_slug`, `apps/realtime/middleware.py`'s `_header`,
  `config/mcp.py`'s `_header` and `apps/usage/mcp.py` each walk the raw
  headers themselves. No layering forbids one reader in `core` (every one of
  those modules may import it); lifting it is the consolidation's, as is
  `config.api.surface_view` building its own refusal response where
  `on_domain_error` was at hand. `core.middleware._refused_here` is the one
  copy the layering forces: `core` may not import `config.api`'s status
  mapper, so it reads the status the code declared in the registry. (d) **Sessions are per
  host**, so a person staff on one host and a customer on another signs in
  twice, and a sign-in round trip started on the staff host lands its session
  on the staff host. (e) **The face's declaration is its route table**; the
  surface's `screens` is the server's answer for machines, held to the table
  by rule 85's screens clause and by
  `apps/example_portal/tests/test_surface_screens.py`. (f) **Declared blind
  spots:** the published OpenAPI document and `/llms.txt` are the
  deployment's, the same at every host — not narrowed per surface; a
  `{tenant}` host directly under a public suffix admits the whole domain
  (refused at the edge by `deploy/provision.sh`, unrefused in settings) ·
  trigger to revisit: a surface that needs a narrower `Out` of the same
  noun (a surface narrows families and acts, never fields); a product that
  must share a session across hosts; a third tenant rule.
