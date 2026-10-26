# ADR mounts-1

**ADR mounts-1 · the platform's REST mounts, router tags and scope families
carry the `djb_` namespace, and no path or tag key is served by two apps (rule
83).** *Accepted 2026-09-29.* The three platform apps mount at
`/api/v1/djb_notes/`, `/api/v1/djb_tags/` and `/api/v1/djb_tag_links/`,
`/api/v1/djb_imports/`, under the router tags (the scope families)
`djb_notes`, `djb_tags`, `djb_imports`; the attachment kinds stay `notes`,
`tags`, `files`. *Rejected*: keeping the resource words on the platform's
mounts (a product's own noun mounts there first and answers first, silently —
measured on django-ninja 1.6.3); a hyphenated namespace (a second spelling of
the word every label, kind, table and family spells with an underscore).
trigger to revisit: a product that must reach the platform's notes at
`/notes/` — that is a proxy in its own tree, never a template change.
