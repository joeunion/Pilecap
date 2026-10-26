# ADR completions-1

**ADR completions-1 · context:** products will call models
(a first consuming product: `draft_reintro` — draft a re-introduction for a dormant contact);
un-platformed, every product grows its own key handling, retry logic,
unaudited prompts and unmetered spend. **decision:** a new platform app,
`completions`. Aggregate: `Completion` — one model call as a row
(status `QUEUED → RUNNING → SUCCEEDED | FAILED`, D4), org-scoped, carrying
the rendered prompt, the output, the model id, and the usage figures.
**Every provider call is a Temporal activity** (rule 9 — the constraint is
constitutional, not optional): the `run_completion` service writes the row
and starts `RunCompletion` on commit (C2); no service or door ever holds a
provider socket open inside a transaction. Prompts are **versioned config**
per D9/D10: `Prompt(TenantScopedModel)` — immutable `key`, `version`,
body, variables schema — `create/revise/retire`, mirroring
`comms.MessageTemplate` (the named precedent); a `Completion` records
`prompt_key` + `prompt_version` denormalized (the durable answer to "what
was this drafted under", D10). **rejected:** synchronous provider calls in
services (C2 — a provider hiccup rolls back a legitimate row; rule 9 the
other side); LiteLLM/LangChain as the abstraction (a large dependency whose
retry/fallback logic fights Temporal's — retries are the workflow's job;
the registry protocol is ~50 lines of ours, comms `providers.py` is the
worked shape); prompts as code constants (unversioned config a tenant
cannot see or audit — D9's exact target). **trigger to revisit:** streaming
token-by-token to sockets → a `realtime` bridge from the activity, designed
then (the row-based contract survives underneath).
