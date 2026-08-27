"""The names of the things this app says happened. **Two, and they are a pair.**

Names only, and that is the whole file (house rule 16). Search publishes no
event about a query — a search is a read, and ADR search-2 rejected per-query
audit as volume with no consumer. What it publishes is the one thing a read
cannot tell anybody on its own: **that the product stopped being able to search
the way it normally does, and that it started again.**

## Why a degradation is an event and not a log line

Previously the sole prior signal for a failover was a log
line, and a user's complaint beat the operator to it. ADR search-2 answers it in
one sentence — **a degradation the system survives is a state it announces,
never just tolerates** — and an announcement on the spine is what turns that
sentence into plumbing: ClickStack alerts on the event stream (ADR obs-2), and
`comms` can route it to a human with nothing new built.

The pair is also **derived, never registered**: `deploy/observability/alerts/
census.py` reads every app's `events.py` by AST and makes one alert per
transition pair — two names in one app sharing `<app>.<noun>`, exactly one of
them ending in a verb from its `RECOVERY_VERBS`. Declaring the two names below
is the whole of joining the alert surface; `docs/runbooks/alerts.md` says so and
names this pair as the next member by these exact strings.

## Transitions only, never per request

Both are emitted by `services.announce_degraded` / `services.announce_recovered`,
and each is reached only by the process that **won the transition claim** in the
cache (`selectors`' circuit). A second failing request while the circuit is
already open emits nothing, and a re-probe that fails again emits nothing —
otherwise a cooldown that expires every thirty seconds would spam the spine with
one event per re-probe and the alert would be the thing somebody silences.

## The one honest wrinkle, stated

`emit` takes a tenant, and a dead index is **not** a per-tenant fact: it is
deployment-wide. The announcement therefore carries **the tenant whose request
observed the transition** — the only tenant the observation can honestly name —
and every other tenant's search degrades with no event of its own. That is
right for the consumer this exists for (the operator, through the sink, where
one event is one alert) and incomplete for the consumer it does not exist for
(a tenant's own webhook endpoint, which will hear about the outage only if one
of its own requests happened to be the one that noticed). It is recorded as this
app's declared blind spot rather than papered over with a broadcast: an emit per
tenant per outage is a storm, and a platform-scoped emit is a seam
`apps/events` does not have.
"""

from __future__ import annotations

#: The payload version these two announcements stamp. They publish no schema —
#: there is no `SearchEngineStateOut` and there should not be, because nothing
#: fetches one — so the payload is built by hand and versioned with a number
#: here, exactly as `apps/comms/events.py` versions its two surge announcements.
V = 1

#: The primary engine stopped answering and the product is serving search from
#: Postgres instead. Emitted **once per transition**, by the request that
#: discovered it — never per failing request, and never by a re-probe that finds
#: the index still down.
SEARCH_ENGINE_DEGRADED = "search.engine.degraded"

#: The primary engine answered again and the product is back on it. Emitted once
#: per transition, by the request whose re-probe succeeded.
#:
#: The verb is `recovered` and it may not be anything else: the alert census's
#: `RECOVERY_VERBS` is a closed one-element tuple, so a pair spelling this
#: `restored` or `closed` would declare a degradation the alert surface cannot
#: see — an alarm that can be raised and never lowered.
SEARCH_ENGINE_RECOVERED = "search.engine.recovered"
