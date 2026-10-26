# ADR core-10

- **ADR core-10 (the org tree's one human door)** *(the recommendation
  was PM-ratified at plan review)* · context: no door reaches `move_organization` — the
  three-move grammar is service-only by deliberate omission
  (`OrganizationAdmin` pins `parent` read-only *against form edits*,
  correctly, since a form write would bypass the wall and the durable
  run); moving one required hand-driving it through a shell, proven twice ·
  decision (RECOMMENDED — PM ratifies at plan review): **an admin
  action** — `move_to_new_parent` on `OrganizationAdmin`, an intermediate
  form whose target-parent choices are `.for_tenant`-scoped, calling
  `move_organization` and rendering refusals through the same
  `wire_refusal`/`messages.error` composer already in place; the read-only
  `parent` field stays read-only (the action is the door; the form field
  is not); the admin door carries no rule-17 parity obligation, so no
  REST/MCP surface is built for a product that does not exist · rejected:
  **ratify service-only** (leaves the one tree-reshaping primitive
  shell-only for every future support human; refusal grammar built for exactly this door goes unexercised by any
  user-initiated write), **a REST endpoint** (rule 17 drags an MCP twin; tenant-facing
  tree management is a product decision — the standing not-yet-real list
  says shop it) · trigger to revisit: the first product whose tenant
  admins reshape their own tree → the REST door then, with its parity
  twin, as that product's rung.
