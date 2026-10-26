# ADR search-2

**ADR search-2 (ING-2D design pair, owner-directed; supersedes
search-1's engine ruling — search-1's per-model pg shape survives intact as
the fallback engine) · context:** every product needs "find the thing", and
search is where scoping quietly dies — an external index that does not carry
the walls is a probing oracle, which is exactly why search-1 refused an
engine and why this design's center of gravity is the filter injection, not
the engine. **decision:** Meilisearch self-hosted in the compose stack (the
ClickStack/Zitadel/MinIO posture); **one shared index per searchable kind**
with `tenant_id` + `org_id` as filterable attributes and the scope filter
resolved in Postgres per request and injected by one chokepoint; a
**rule-33 fencing rule** (the rule-27 shape) walls the Meili client
into `apps/search/engine.py`; the **indexer rides the events spine**
(outbox, at-least-once, replay-safe, mirroring `push_realtime` to the
letter); **pg FTS + trigram stays behind the same engine-agnostic protocol**
as the designed degradation — Meili down means slower and plainer, never
dead. **rejected:** index-per-tenant (reasoned in `docs/product/adrs-ingredients.md` § "The document model"); Meili tenant tokens
/ browser-direct search (below); a central `SearchEntry` shadow table
(search-1's rejection stands — the *engine's* documents are not a shadow
authz copy because no authorization decision is ever made from them: the
filter is computed in Postgres every request and the fencing rule means no
other path exists); OpenSearch/Elasticsearch (ops weight + the same sync
work for relevance gains no product at this scale needs — search-1's
rejection, unchanged). **trigger to revisit:** the P6 harness measuring the
visible-org-id list as a real ceiling at seeded scale (the named risk of
list-not-path filtering), or a product needing semantic similarity (its own
ADR, adjacent ING-3 — not folded in here).
