# Capacity runbook — load, limits and the axis you are allowed to scale

The operator's chapter for the questions that only appear under load: *how much
can this deployment take, what runs out first, what do I read to find out, and
what am I allowed to conclude from what I read.*

**It is a chapter, not a second copy.** Three files already own numbers this
chapter needs, and it points at them rather than rendering them again:

| What | Who owns it |
|---|---|
| The connection budget's arithmetic | `config/settings/base.py` (the block above `DATABASE_POOL_APP_CEILING`), with the same arithmetic beside the values it sets in `deploy/env.staging.example`, and the knobs that make the bounds true in `deploy/compose.yaml` |
| Every alert's threshold, interval and declared detection window | `docs/runbooks/alerts.md` § "Values, and why each one" |
| The deploy sequence, the one-off door, the release acts | `docs/runbooks/deploy.md` |
| The committed load drive — mix, seed, ladder | `deploy/load/drive.py` |
| The platform's scale doctrine | `docs/product/scale-envelope.md` |

A number that appears here and there is a number that will disagree with itself.
If you find one, that disagreement is a finding, and the file in the table wins.

**Every claim below is grounded in a real deployment's operational history**,
restated here as generic operating guidance rather than as a citation trail.
The specific dispatch and finding rows behind each lesson live in
`docs/product/in-flight.md`, `docs/product/queue.md` and
`docs/product/misses.md` for anyone who wants the full incident behind a
claim; this chapter does not retell it.

**Two of these recipes are executed.** `scripts/tests/test_runbook_recipes.sh`
lifts them out of *this document* at run time and drives them — see § "What is
driven and what is only bound" at the foot.

---

## 1 · The envelope method, and the four-part line

An **envelope** is what this deployment can carry, written down so somebody else
can falsify it. It is produced by the committed drive (`deploy/load/drive.py`)
and nothing else: a fixed request mix, a fixed dataset scale, a fixed seed, a
fixed concurrency ladder, against a named sha. Two runs of different drives are
two anecdotes.

**The knee is declared before the run, never eyeballed after it.** The
operational definition: *the first ladder step at which p95 exceeds 1s sustained
across the step's window.* Writing it down first is what stops the graph from
being read to taste.

**Every envelope line carries four parts, and a line missing one is an
anecdote.** The four:

1. **metric** — what was measured, with its value, and the knee claim if it
   makes one.
2. **instrument** — the query or command **pasted**, not described. The
   same-instrument doctrine: two numbers are comparable only when the same
   instrument produced both, byte-identically. A knee measured after a
   configuration reload is not comparable to a knee measured before it for
   exactly this reason — state the incomparability in the report instead of
   quietly quoting a ratio.
3. **conditions** — size, dataset scale, concurrency, **and `err`, the step's
   error rate**.
4. **utilization** — the named component and its utilization *at the knee*. This
   is what makes "first-saturating component" a readable fact rather than an
   assertion.

**The validity rule, and why it is part of the line.** *An envelope line whose
`err` exceeds 5% is INVALID for naming a knee.* A p95 computed over a step that
was mostly fast refusals measures how quickly the deployment says no — not how
much work it did. A step at concurrency 16 reading p95 1658ms over 83% fast
500s is exactly that trap, refused as an artifact by anyone who ran it; a clean
re-run of the same ladder put the honest knee at concurrency 8. **A line above
the bound is marked INVALID and kept — never omitted**, because the omission is
what makes the next reader think a clean run was clean.

**The worked example.** One valid line, as it is written into the run's output
directory:

<!-- recipe: envelope-line-example -->

```text
metric=p95_ms=2000 knee=conc-8 | instrument=deploy/load/drive.py --size A --ladder 1,2,4,8,16 --seed 20260826 | conditions=size=t4g.large,scale=seeded-A,concurrency=8,err=0.0 | utilization=ec2_host_cpu=92.7
```

Four fields, separated by ` | `, each `key=value`; `conditions` carries `err`;
`utilization` names one component and its percentage. The checker below is what
makes the format a rule rather than a habit — it is run against the line above
by the drive, so a line that stops parsing here fails a test rather than aging
quietly in a runbook.

<!-- recipe: envelope-line-check -->

```python
"""Read one envelope line on stdin; exit 0 if it is a valid envelope line.

    printf '%s\n' "<the line>" | python3 envelope_line.py
    printf '%s\n' "<the line>" | python3 envelope_line.py --knee

`--knee` additionally enforces the validity bound: a line claiming a knee over
an error rate above 5% measures refusal speed, not work, and is refused here
rather than quoted later.
"""

import sys

REQUIRED = ("metric", "instrument", "conditions", "utilization")
ERR_BOUND_PCT = 5.0

line = sys.stdin.read().strip()
if not line:
    print("!! empty: an envelope line is four parts, and this is none", file=sys.stderr)
    raise SystemExit(2)

parts = {}
for field in line.split(" | "):
    key, sep, value = field.partition("=")
    if not sep:
        print(f"!! not a key=value field: {field!r}", file=sys.stderr)
        raise SystemExit(1)
    parts[key.strip()] = value.strip()

missing = [name for name in REQUIRED if name not in parts or not parts[name]]
if missing:
    print(f"!! anecdote, not an envelope line — missing: {', '.join(missing)}", file=sys.stderr)
    raise SystemExit(1)

conditions = dict(
    pair.split("=", 1) for pair in parts["conditions"].split(",") if "=" in pair
)
for needed in ("size", "scale", "concurrency", "err"):
    if needed not in conditions:
        print(f"!! conditions names no {needed}=", file=sys.stderr)
        raise SystemExit(1)

err = float(conditions["err"])
claims_knee = "knee=" in parts["metric"]
if "--knee" in sys.argv and claims_knee and err > ERR_BOUND_PCT:
    print(
        f"!! INVALID for naming a knee: err={err}% is above the {ERR_BOUND_PCT}% bound"
        " — this p95 measures refusal speed, not work",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"ok envelope line: {parts['metric']} at err={err}% ({parts['utilization']})")
```

---

## 2 · The connection census — what is holding what, and who

Postgres connection slots are the resource this deployment has run out of more
often than any other, and they are the resource whose exhaustion looks like
something else. A deployment can read as having **"no latency knee" at all**
when what actually happened is a connection-slot wall reached at concurrency
1 — the RDS instance's slots gone before the load ever started mattering.
Read the slots first, always, before you believe anything a latency number
tells you.

### 2a · The census, by database and by principal, in ONE read

<!-- recipe: pg-census -->

```sql
SELECT datname,
       usename,
       count(*)                                             AS held,
       count(*) FILTER (WHERE state = 'active')             AS active,
       count(*) FILTER (WHERE state = 'idle')               AS idle,
       max(EXTRACT(epoch FROM now() - state_change))
           FILTER (WHERE state = 'idle')::int               AS oldest_idle_s
  FROM pg_stat_activity
 WHERE backend_type = 'client backend'
 GROUP BY datname, usename
 ORDER BY held DESC, datname, usename;
```

**`datname` is the attribution, not `usename`.** A managed organ can connect as
a shared master user, so a census grouped by principal alone credits that
organ's slots to whoever else shares the role. Group by both and read the
database column: a background service's own database — a workflow engine's
task queue, its visibility store, an identity platform — is its own database
and cannot hide behind a shared login.

**The same-read discipline.** `held`, `active`, `idle` and the attribution come
out of *one* execution of the query above. A census that reads totals now and
attributes them from a second query taken thirty seconds later is comparing two
worlds and calling the difference a fact. Attributing an organ's excess — say,
extra backends belonging to a second, unbounded pool a shared identity
platform opens on its own — has to happen inside the same read that counted
it, by pid and query, or the number cannot be believed. **A principal the
census cannot attribute is a stop-and-report, never a judgment.** An
instrument may not convert *I could not look* into *it is fine*.

**What a healthy read looks like** is not a number this file owns: the bounds
live beside the arithmetic in `config/settings/base.py`. Read them there, then
read the census against them. **Any principal above its stated bound is the
revisit trigger** — that is the trigger's whole definition now, replacing "a
number went stale", which nothing could ever observe.

### 2b · The steady-touchers read, and when to take it

<!-- recipe: pg-census-steady -->

```sql
SELECT datname,
       usename,
       state,
       EXTRACT(epoch FROM now() - state_change)::int        AS in_state_s,
       left(regexp_replace(query, '\s+', ' ', 'g'), 60)     AS last_query
  FROM pg_stat_activity
 WHERE backend_type = 'client backend'
   AND datname IS NOT NULL
 ORDER BY datname, usename, in_state_s DESC;
```

**Take it at `t ≥ DATABASE_POOL_MAX_IDLE + 60s` after the load stops, never
sooner.** An earlier criterion here — "90 seconds after the drive, the app
holds no more than the sum of `min_size`" — was unreachable by construction:
the idle window is 300 seconds, so at t+90 the pool is *supposed* to still be
warm. A clean measurement of the decay (18 / 18 / 18 / 17 held at t+0 / 90 /
200 / 320) is what should move the criterion, not chasing the pool to match a
number picked before anyone measured it.

**And the expectation at that point is not zero.** Two populations lawfully keep
slots warm for ever: the worker's Temporal poll loop, and the readyz prober's
15-second `/readyz`. The read above names them by their last query, in the same
read, which is what turns "some connections are still there" into either an
attribution or a finding. A handful of app connections outliving the idle
window by tens of seconds is worth booking as an open observation rather than
explaining away on the spot — it may point to a reaper-cadence question if it
recurs.

---

## 3 · Resizing the box — the sequence, with the step that is easy to forget

**Review-tier: bound, never driven.** This section's commands act on AWS. Read
§ "What is driven and what is only bound" for what that costs you.

The sequence below has been proved live, end to end, and proved again in
reverse on the way back:

1. **`aws ec2 stop-instances`** — and wait for `stopped`. A modify on a running
   instance is refused.
2. **`aws ec2 modify-instance-attribute --instance-type`** — one axis. See § 7.
3. **`aws ec2 start-instances`** — and wait for `running`.
4. **The public IP has changed.** A stop/start releases the address unless the
   instance carries an Elastic IP, so the box now answers on an address DNS has
   never heard of.
5. **`./deploy/dns.sh upsert "$DJB_ENV" "$NEW_IP"`** — the same command Part 3
   of `docs/runbooks/deploy.md` uses at first boot. This is the step that gets
   forgotten, because everything up to it succeeded and nothing yet has failed.
6. **Verify it resolves** — `./deploy/dns.sh show`, then resolve the name from
   somewhere that is not the box.
7. **Health, over the real name and real TLS** — `/readyz`, all organs. Not the
   IP: the IP proves the process is up and proves nothing about the path a
   client takes.

**Two** DNS re-points — out to the larger size and back — is why step 5 is a
numbered step here rather than a footnote; it is easy to drive once and skip
the second time.

**Resize-back is verified, not assumed.** The instance type read back after the
return must equal the type recorded before the experiment started — recording
the before value and asserting the after value is what turns "we resized
back" into a checked fact rather than an assumption. A two-way resize on a
small instance costs cents, not dollars.

### Boot resilience — what was proven, and what it does not prove

Rebooting the box twice in the course of resizing, both times the stack came
back on its own: every organ up, `/readyz` green, no hand steps. Reboot
resilience — previously an open, unproven question for this deployment shape
— is proven for that case.

**What that does not prove:** that the box comes back from an *unclean* stop, or
from a host-level failure, or with a cold page cache under load. Two clean
stop/start cycles are two clean stop/start cycles.

### The before-picture is destroyed by the thing you are measuring

**Capture the census BEFORE the config change, and capture it somewhere that is
not the container.** A `docker compose up --force-recreate` is the correct way
to apply a changed environment — a restart cannot change an environment, only
a recreate does — but it **destroys the organ logs that would have been your
baseline.** A comparison drawn across a recreate without an external copy of
the before-picture has to be withdrawn after the fact: a context-deadline
count that looked like it moved is left unconvicted, because the recreate took
the "before" with it before anyone could compare.

So: run § 2's census, save the output to a file outside the stack, *then* change
the config. The organ's own logs are not a before-picture across a recreate.

---

## 4 · The neighbour budget — the arithmetic, and how to test a suspicion

**The arithmetic is not here.** It lives in `config/settings/base.py` above
`DATABASE_POOL_APP_CEILING`, with the same table beside the values it sets in
`deploy/env.staging.example`, and the knobs that make its bounds true in
`deploy/compose.yaml`. **Two homes, deliberately** — `deploy/env.prod.example`
carries value lines and a pointer only, so there is no third rendering to drift.
Read the budget there. This section is about the two ways it has been wrong.

**The per-role multiplication trap.** A shared organ's configured pool size is
not the number of connections the organ opens. Temporal's `auto-setup` image
runs four service roles in one process, and **each role builds its own SQL pool
from the same configuration** — so a configured 20 is a ceiling of 4 × 20, plus
the visibility store's own 4 × 10 on top. That is how a budget line reading
"Temporal: 17 + 3" — an *at-rest observation* written down as if it were a
constant — can coexist with a measured 41 held at rest after a reboot, a
number no single pool of 20 could produce. The revisit trigger firing once
from a stale at-rest line, and firing again from the same underlying gap, is
exactly what confounds a paid experiment run against it. The fix is to stop
observing and start bounding: every organ enforces its own ceiling in its own
process. The transferable form of the lesson — *a shared resource's budget is
what it holds under load, not at rest.*

**The Zitadel second-pool fact.** `MAXOPENCONNS` bounds Zitadel's main pool.
Its background job queue keeps a **second** pool that no environment variable in
v4.17.1 reaches — `strings` over the binary returns the four
`MAXOPENCONNS` / `MAXIDLECONNS` / lifetime names and no queue knob at all. So the
budget line is the **observed** ceiling, not the configured one, and the two
unbounded slots come out of operator headroom instead of being rounded into
invisibility. The operational consequences, both of which are yours:

- A census reading Zitadel **at** its budget line is at its bound. **Above it is
  a stop-and-report naming the principal** — never a widened budget.
- **An image bump is a re-census trigger**, because this bound is empirical and a
  new image can move it with no diff in `deploy/compose.yaml` to catch.

The bound and its two-way laptop drive are recorded in
`config/settings/base.py`.

### The A/B for a neighbour you suspect is starving the app

Go's connection pools **queue silently**: a starved neighbour shows up as
latency, never as an error. If the app's own pool is healthy and something that
rides the neighbour got slower, the test is one environment step:

1. Save the census (§ 2) and the latency evidence **to a file, before anything**
   — § 3's "before-picture is destroyed by the thing you are measuring" section
   is about exactly this moment.
2. Raise the one suspected bound in `deploy/compose.yaml` — **one knob, one
   organ**.
3. `docker compose up -d --force-recreate <organ>`. A restart cannot change an
   environment — only a recreate does.
4. Re-census (§ 2) and confirm the bound actually moved in the organ's own
   process.
5. Re-drive the same ladder, same seed, and compare the four-part lines.

If the latency comes back, the suspected neighbour is convicted and the remedy
is one env step in the other direction. If it does not, the bound was not the
constraint and you have spent nothing.

---

## 5 · The alert route while the deployment is under load

**The thresholds, intervals and declared detection windows are all in
`docs/runbooks/alerts.md` § "Values, and why each one".** They are not repeated
here; a second copy of an alerting arithmetic is how two operators come to
believe two different detection windows.

**The evaluation-lag rule: a monitor's silence during its evaluation window is
not a verdict.** Every alert here fires on N consecutive failing windows, so
there is a period after a fault begins during which *the correct behaviour of a
working monitor is silence*. Sampling inside it and concluding "the alert never
fired" is a wrong conclusion, and it is a wrong conclusion this house has
actually reached — caught only because more evidence arrived before the
report shipped, which is the sort of near-miss worth carrying forward. Before
you conclude a monitor is broken: read its declared detection window in
`alerts.md`, add it to the time the fault started, and only then decide
whether you have waited.

**The sibling misread, from the same rung:** four samples of a flapping health
check were read as an outage. A flap and an outage differ in the shape of the
series, not in any one sample.

**What firing actually looks like** — a real end-to-end `/readyz` outage:
OPENED, quieted honestly when the condition cleared, re-OPENED when it
returned, delivered to the owner's Slack, detection inside the declared
window, `send_failed=0`, and `db:false` alone as the reason. That is the whole
shape. If you see the open without the recovery, or the
recovery without an open, that is a finding.

**The deaf-sink half can be legitimately disarmed, and it says so.** An empty
`SLACK_WEBHOOK_URL` disarms the prober's own half; the prober announces that
once per start with a DISARMED banner rather than going quiet. **A disarmed
half is not a passing half.** Under load, when the sink is the thing you most
need, check the banner in the prober's log before trusting its silence —
`alerts.md` § "The one alert that cannot ride the sink" is the authority on why
this alert cannot be delivered any other way.

---

## 6 · The one-off door, and what a `PoolTimeout` on a management command means

**Every `compose run` in this house names `oneoff`.** The service, its reduced
pool, its absent `depends_on`, and the census that refuses a `run … web`
creeping back in are all documented at the point of first use in
`docs/runbooks/deploy.md` (Part 1, the paragraph above the migrate step) — and
the pool size itself is derived in `config/settings/base.py`, like every other
process's. Read them there. What belongs here is *why*, in load terms:

**A one-off that runs as `web` reserves a deployment's worth of connection
slots.** It is a third process, and it derives `web`'s pool. On a box that is
already busy, that reservation is refused — and the operation you were running
is refused with it.

**This class of failure has bitten three times in one day**, which is the part
worth carrying:

- `revoke_token` timed out on a loaded box with zero slots free.
- It bit twice more — and disproved the obvious mitigation. Minting the token
  *before* the ladder was thought to be enough; it was not, because **a loaded
  box has no slot for any third process at all, whatever the sequencing.** The
  constraint is slots, not timing. Recovery each time was a force-recreate.
- The same shape sits under any release act: a release can be refused by its
  own box's load.

The general form of the lesson: *a mitigation that survived one incident is a
hypothesis, not a control.*

**So: what does a `PoolTimeout` on a management command mean now?** Since
every invocation moved to the `oneoff` door — proven live with five
mid-ladder probes on a loaded box, including at the ladder's top step, all
admitted — a `PoolTimeout` here **no longer means "the box is busy".** It
means one of:

1. **You typed `web` or `worker`.** Check the command you actually ran.
2. **A neighbour is over its bound.** Run § 2's census. This is the same
   revisit trigger as everywhere else in this chapter.
3. **The app's own pool is saturated by real traffic** — in which case § 2's
   census shows the app at its own `max_size` with backends `active`, not
   `idle`, and you are looking at an envelope question, not an operations one.

The distinction matters because (1) is a typo, (2) is a config change, and (3)
is a purchase.

---

## 7 · Scaling by measured axis

**The method, in four rules:**

1. **The size-A run names the first-saturating component with its evidence** —
   the component whose utilization ceiling coincides with the throughput knee.
   That is what the four-part line's fourth part exists for (§ 1). It is a
   readable fact, not an assertion.
2. **Resize exactly that one axis. Never two.** A two-axis resize confounds the
   ratio into an unfalsifiable blur.
3. **The prediction is written down before the resize.** "If resource-bound on
   `<axis>`, the knee moves by ~the resource ratio." Size B then confirms it —
   resource-bound, healthy, a product scales by paying — or refutes it, and the
   refutation *names the structural ceiling* (a lock, a pool, a single-process
   server) with the observation that convicts it.
4. **Resize back, and verify the size you came home to** (§ 3).

### The confound lesson, which is the expensive one

Following all four rules can still produce **no ratio**, on purpose, and that
is a legitimate, citable outcome rather than a failed run. One worked case:
the axis was vCPU; the prediction was that the knee would roughly double. What
happened: the CPU half confirmed precisely, and the knee did not move at all —
but **not for the predicted structural reason.** RDS connection slots had
become binding first, because the neighbours' inflation had escalated across
the reboot the resize required (§ 4). The two ladders therefore differed on an
*unmeasured* axis, and the honest report is **confounded, with no quotient
sold.**

The rule that comes out of it: **an A/B whose baselines differ on an
unmeasured axis reports the confound, never the quotient.** A ratio computed
over a confound is a number, not a test — and it is worse than no number,
because it will be cited.

**The pre-spend baseline gate exists because of this.** Before a paid run: take
§ 2's census, confirm every neighbour is at or below its bound and the free-slot
floor holds. **A dirty baseline voids the run before it starts.** Discovering
the confound only after paying for the run is the expensive way to learn this;
checking the baseline first, and passing, is the cheap way.

### What is citable today, and what is not

A partial result is still worth keeping, as long as what it does and does not
prove is named. **Citable:** a CPU-axis resize that measured host CPU
utilization 92.7% → 49.2% and load average 11.70 → 4.07 at twice the vCPU.
Host CPU scales by paying, and that sentence is measured.

**Not citable, by name:** *a knee or throughput quotient at the larger size,*
when that run's knee was slot-gated rather than CPU-gated (the confound
above) and a clean run against the current baseline has not been paid for. If
somebody quotes a knee ratio out of a confounded run, they are quoting the
confound.

**And the standing caution about the class of instance:** a burstable
instance type spends CPU credits as it runs, so a run against one is
measuring a budget as well as a machine. Refute the credit theory with
evidence — a surplus reading taken on both sides of the run — rather than
assuming it away.

---

## What is driven and what is only bound

`scripts/tests/test_runbook_recipes.sh` lifts the marked blocks out of this
document **at run time** and holds no copy of them. Three careful edits to a
webhook recipe nobody ran produced three defects in a row, which is why that
drive exists at all; its header is the argument.

**Driven, against the development Postgres:**

- **§ 2's two census recipes.** What is asserted is **shape**: the query is
  legal against a real server, the columns it names exist, and the principals
  come back attributed in the same read. **No number from a laptop is a staging
  number**, and the drive asserts none.
- **§ 1's four-part-line checker, against § 1's own worked example.** The drive
  feeds the document's example line to the document's checker and expects a
  pass, then removes one field and expects a refusal. A format that stops
  parsing therefore fails a test, in this repository, on this document.

**Bound but never driven** — the same precedent the vendor-signed recipes in
`docs/runbooks/deploy.md` set, and declared here rather than discovered:

- **§ 3's resize and DNS sequence.** These commands act on AWS. A drive cannot
  stop an instance, and one that could should not.
- **§ 3's reboot resilience.** Proven twice by hand, on a real box; nothing here
  re-proves it, and § 3 states what those two proofs do not cover.
- **§ 4's A/B and § 7's ladder.** A load run is a paid performance against a
  deployed box, not a document test. Its output is an envelope, and the envelope
  is reviewed by a human reading four-part lines.
- **All of the prose.** Only the fenced blocks under markers are executed. A
  wrong sentence beside a right recipe is invisible to the drive exactly as it
  is to a reviewer — which is why every claim above cites the row that paid for
  it, so a reader can check the sentence against the ledger.
