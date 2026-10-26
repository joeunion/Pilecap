# ADR platform-lifecycle-1

**ADR platform-lifecycle-1 · 2026-08-24 · machinery durability follows the
identity's declared lifetime class.** *Context*: the owner's escalation of
2026-08-24 — a second strike on the same leak, asking for "an elegant,
comprehensive solution instead of band aids". The diagnosis is not a missing
reaper: it is a **lifetime-class mismatch minted at creation**. A Temporal
Schedule is infinitely durable by construction, and every worker keys one to an
identity that is ephemeral by construction — the checkout-path hash inside the
task queue name (`scripts/db.sh`). Durable object, mortal identity, and the
census on the owner's machine measured what that produces: **36 orphaned
schedules and 134 stranded executions** pointed at queues no worker has polled
for weeks. The decisive observation is that each of those schedules only ever
delivered work while its checkout's worker was alive anyway — so in a
checkout-derived environment the durability buys nothing except the leak, while
in a real deployment it buys catch-up across a deploy gap and a missed run that
is a fact rather than a silence. *Decision*, in four parts. **(1) The class is
declared, never derived.** One setting,
`TEMPORAL_MACHINERY_LIFETIME: "deployment" | "process"`: `deployment` is the
current code path bit-for-bit (durable Schedules the server owns) and is what
`config/settings/production.py` declares; `process` creates **no Schedule object
ever**, and is what `local` and `test` declare. In `process` mode the live
worker starts the same sweeps itself — once at startup, which is the catch-up
run, and then on each declaration's existing cadence for as long as it lives —
under the existing deterministic ids, with `TERMINATE_EXISTING` superseding a
stale open run rather than failing or skipping; and worker startup **deletes
this checkout's own** previously-created durable schedules, only `NOT_FOUND`
swallowed and every real deletion logged (`drop_legacy_purge_schedule`'s
reasoning, generalised). Environment is distinguished by declaration and never
by name: there is no branch test, no checkout-name test, no worktree heuristic,
and the seam is scanned for one. **(2) The declaration is data.** An app's
`SCHEDULES` entry is a `core.schedules.ScheduleDeclaration` — an id builder and
a `Schedule` value — and one generic engine (`apps/workflows/client.py`)
consumes it: apps declare *what*, the engine decides *how*, and both classes
read the workflow, its argument, its id and its cadence off the one declared
value so they cannot drift. **(3) The destroy half is a registry** (house rule
20's declared-population logic applied to machinery): every class declares name,
identity grammar, enumerate, liveness evidence, destroy and a warm-cache flag,
behind one entry point with the four-verdict grammar promoted frame-wide from
`db_sweep.sh` — live / IN USE / FOREIGN / REFUSED — and one shared live-checkout
enumerator. An enumerated instance matching the identity grammar that no
declared class claims is **exit 2**: could-not-judge outranks a pass, so
machinery class N+1 fails the day it first exists. **(4) The gate leg is
own-tree only.** The full gate gains a post-suite census over the instances *this
checkout* created; the machine-wide census stays out of the gate and in the PM's
standing pre-wave reap. *Rejected*: **worker-shutdown deletion** (SIGKILL, OOM
and a laptop lid leak it entirely — and in production it would delete a peer
instance's schedules, which is a worse failure than the one it fixes);
**TTLs on schedules** (age is not liveness — a reaper wearing create's clothing,
and it would reap a healthy deployment's quiet sweep); **one shared dev queue**
(the cross-checkout hijack class, re-armed: the last worker to start silently
owns everybody's sweeps); **reap-harder-with-durable-everywhere** (the band-aid
at strike three — a third reaper for a class of object that should not have been
created); **machine-wide red gates** (my verdict coupled to your corpse; FOREIGN
requires an operator by design, and a gate reddened by somebody else's garbage
trains people to override the gate). trigger to revisit: the first
`deployment`-class environment whose queue identities become **per-instance**
(a per-pod suffix, a blue/green pair) — that deployment's identities are
ephemeral and its declaration should change with them; or the
unrecognised-shape exit 2 firing, which means a machinery class exists that
nobody declared.
