# Capacity runbook — load, limits and the axis you are allowed to scale

The operator's chapter for the questions that only appear under load: *how much
can this deployment take, what runs out first, what do I read to find out, and
what am I allowed to conclude from what I read.*

**It is a chapter, not a second copy.** Three files already own numbers this
chapter needs, and it points at them rather than rendering them again:

| What | Who owns it |
|---|---|
| The connection budget's arithmetic | `deploy/env.staging.example` § "The connection pool, and the budget it fits inside", beside the values it sets; the per-process sizes are `config/settings/base.py::_POOL_MAX_SIZE_BY_SERVICE`, the argument ADR config-1, and the knobs that make the bounds true are in `deploy/compose.yaml` |
| Every alert's threshold, interval and declared detection window | `docs/runbooks/alerts.md` § "Values, and why each one" |
| The deploy sequence, the one-off door, the release acts | `docs/runbooks/deploy.md` |
| The committed load drive — mix, seed, ladder | `deploy/load/drive.py` |
| The platform's scale doctrine | `docs/product/scale-envelope.md` |

A number that appears here and there is a number that will disagree with itself.
If you find one, that disagreement is a finding, and the file in the table wins.

**Every claim below is grounded in a real deployment's operational history**,
restated here as generic operating guidance rather than as a citation trail:
a measured claim cites its § 9 line by sha, and the incident behind a lesson is
not retold here.

**Two of these recipes are executed.** `quality/tests/test_runbook.py`
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
`utilization` names one component and its percentage. The committed drive's lines
carry more than the four, never fewer: `metric` adds the step's `p95_read_ms` and
`p95_write_ms`; `conditions` adds `throttled`, `topology`, `client` (the drive
box's class), `tenants` and `credentials` (how many tokens the clients carried
across how many tenants — sixteen clients under one token are a loop the `auth`
throttle names, never a knee); `utilization` carries `host_cpu` (the web box),
`organs_cpu`, `client_cpu` (the drive box; `not_sampled` when the drive ran on the
box it measured) and the pool counts. `instrument` names its pacer
(`pacer=<rate>/s`, or `pacer=off`) on every line the drive prints, and `conditions`
repeats it, so two pacings never share one instrument string. A fifth part reads the
bar the drive declares in source (`BAR_CLIENTS`, `BAR_P95_MS`, `BAR_ERR_PCT`) as an
observation, never an exit status: `bar=met`, `bar=unmet(<which bar, at which step>)`,
or `bar=unjudged(<why>)` when the line's shape is not the one the bar was declared for
(`BAR_TOPOLOGY`, `BAR_MIN_CREDENTIALS` in `deploy/load/drive.py`). A sixth part,
`validity=`, marks a line that must not be read as a knee:
`validity=INVALID(err above <the bound>%)` for the validity rule above, and
`validity=INVALID: one credential above one client` for a ladder above one client under
one token. The worked example is the first era's four parts, with no `pacer=`. A soak line carries no
`credentials=` of its own: it is read with the envelope line above it, and a
one-credential mark sits on that line only. The checker below is what
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

### Boot resilience — what the resize saw, and who owns the question

The resize above stopped and started the box twice, and both times the stack
came back on its own: every organ up, `/readyz` green, no hand steps. That is
an observation about two clean stop/start cycles, not a reboot drill:
`docs/runbooks/deploy.md`'s opening blind spot ("a re-deploy is proven, a
reboot is not") owns whether a deployed box survives a restart, and it says the
reboot is unproven. This chapter defers to it.

**What two clean cycles do not prove:** that the box comes back from an
*unclean* stop, or from a host-level failure, or with a cold page cache under
load.

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

**The arithmetic is not here.** It lives in `deploy/env.staging.example`
§ "The connection pool, and the budget it fits inside", beside the values it
sets; the per-process sizes are `config/settings/base.py::_POOL_MAX_SIZE_BY_SERVICE`
(its comment cites ADR config-1 rather than restating the table), and the knobs
that make its bounds true are in `deploy/compose.yaml`. `deploy/env.prod.example`
carries value lines and a pointer only, so there is no second rendering to drift.
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
returned, posted to the Slack webhook, detection inside the declared window,
`send_failed=0`, and `db:false` alone as the reason. That is the whole shape of
a firing. Whether a post reached a person is a separate proof that
`docs/runbooks/alerts.md` § "The end-to-end evidence a real destination owes"
owns, and its five timestamps are pending there. If you see the open without the recovery, or the
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

**Every production-shape line in § 9 without a `host=` field carried the box
image's own stack in its CPU:** the verifier image's laptop stack ran on the web
and organs boxes beside the measured app, inside `host_cpu` and `organs_cpu`.
From the first line that says `host=`, `scripts/envelope.sh` stops that stack
before the app comes up and each sampler writes a `docker ps` census beside its
samples (`98c4b17db`).

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

**Which box ran out is a column, not a guess:** the soak's per-window table
names both boxes' CPU — `host_cpu` (web) and `organs_cpu` (organs), each as
median/max — and the SOAK line carries `max_host_cpu` and `max_organs_cpu`, so
a resize names the box its own run saw saturate. The process count is read too,
never typed: the web half prints `pool processes web=1,worker=<n>` off its own
`docker compose config`, and the SOAK line's `pool_budget=` is web + n × worker.

## 8 · Soak — whether the half-knee load holds

A knee says how much the deployment carries for a minute; a soak says whether it
keeps carrying it. `deploy/load/drive.py soak --concurrency N --minutes M` holds
N closed-loop clients for M minutes and judges each 5-minute window on four
numbers: the door error rate, the door p95, `pg_clients` — the most client
backends (`backend_type = 'client backend'`, § 2a's population, any role) the
app's own database held in that window — and `outbox_pending` — the most
`events_outbox` rows in `pending` in that window. Both counts are read off the
box that runs Postgres by `deploy/load/utilization.sh`, never inferred, and the
same sampler records `worker_backlog`, Temporal's approximate backlog over the
app's task queue (`temporal task-queue describe`), beside them. When that box is
not the drive's (`scripts/envelope.sh --shape prod`), the soak writes its samples
and `drive.py judge` joins them to the organs box's file afterwards; the verdict
is the same function either way. The verdicts:

- **`steady`** — every bound holds: each window's `err` is at or below the
  acceptable tier's **0.5%** (`BAR_ERR_PCT`; `--err-bound` names another); each
  window's `pg_clients` is at or below the **declared pool budget**
  (`_POOL_MAX_SIZE_BY_SERVICE` in `config/settings/base.py` summed over `web`
  and `worker`); and the last window's `outbox_pending` is at most the first
  window's plus **one relay pass** — `RECONCILE_BATCH` in
  `apps/events/activities.py`, the stranded rows the relay resumes every
  `RECONCILE_EVERY`. The drive reads both declarations out of their files at run
  time. A `pg_clients` above the budget is the pinned-connection shape (§ 2)
  coming back; an outbox that grows past one pass is a relay that is not keeping
  up.
- **`drifting`** — the bounds hold, but the last window's p95 is above **1.5×**
  the first's: latency grows under constant load, which a one-minute step
  cannot see.
- **`unsteady`** — some window broke a bound; the line ends `broken=` naming
  which, and the reasons beneath it say by how much.
- **`undetermined`** (exit 2) — a window held fewer door samples than the
  drive's `MIN_WINDOW_SAMPLES`, or no `pg_clients` or no `outbox_pending` sample.
  Could-not-look is never read as `steady`.

The line: `soak=<verdict> concurrency=<n> minutes=<m> pool_budget=<n>
max_pg_clients=<n> max_pg_total=<n> [pg_other=<backend_type>:<n>[,…]]
max_idle_in_tx=<n> outbox_pending=<first>/<last> err_max=<pct>
err_bound=<pct> max_worker_backlog=<n> … [broken=… [pg_by_app=<name>:<n>[,…]]]`.
`pg_total` counts every backend on the database, an autovacuum or parallel
worker among them; the budget is judged on `pg_clients`, and whenever a window's
two differ the line carries `pg_other`, the non-client backends of the sample at
that window's maximum, so a difference is named, never silent. On a
`broken=pg_clients` line `pg_by_app` names the client backends by
`application_name` from the same statement: `config/settings/base.py` sets it to
`<DJB_SERVICE_NAME>@<host>` on every connection, so the holder's process class
is in the read that counted it. `worker_backlog` is recorded, not
judged: it says whether the worker kept up, and a product reading a growing one
has its answer for § 7's worker axis. `idle_in_tx` is recorded the same way —
the most of `pg_total`'s connections whose state was `idle in transaction`, the
number a request holding its transaction open (`ATOMIC_REQUESTS`) inflates; the
envelope line's utilization part carries it at the knee step.

A sampler file written before the sampler read `outbox_pending` answers
`undetermined` when today's `drive.py judge` reads it (`window(s) [..] hold no
outbox_pending sample`), and one written before it read `pg_clients` answers the
same way (`hold no pg_clients sample`): that is could-not-look on an old file,
not a regression, and older runs are not re-judged.

The 0.5%, the 1.5× and the one relay pass are observation thresholds declared
beside the knee's in the drive's source, not gates: no pull-request path runs
the drive (ADR perf-1). The soak runs at half the knee because that is the load
a deployment is meant to carry all day; at the knee itself, drift is the
expected answer. A two-hour soak outlives the verifier box's idle wall, so
`scripts/envelope.sh` touches every box it is not polling every `FRESH_EVERY`
seconds; the run is one envelope however long the soak.

Declared blind spots: a flat `outbox_pending` says the relay keeps up, not that
deliveries succeeded (`events_delivery` is a different question); the backlog is
Temporal's approximation, which the CLI says may count expired tasks.

## 9 · Recorded knees

`scripts/envelope.sh <sha>` measures one envelope on throwaway verifier boxes
(namespace and region as the verifier-box road sets them; never a product's
stage) and writes the two lines below, newest last. Its default is the
production shape (`topology=web-box-organs-box-drive-off-box`): the organs on one
box, web, worker, frontend and Caddy on a non-burstable web box, and the drive
on a third box in the same security group with eight clients over four tenants,
each under its own token — so a knee here is the web box's, and a client that
saturated first shows as `client_cpu`. Before the ladder it takes § 2a's census
and refuses a dirty baseline (§ 7). The shape needs the group to admit its own
boxes on the organs' ports and 443; the script probes that first and, when the
group drops it, prints the owner's one ingress command and stops. `--shape
one-box` is the first shape, compose on one host with the drive on the same box
(`topology=compose-one-host-drive-on-box`), kept for comparison; the RDS shape
`provision.sh infra` deploys is measured by `--shape infra` — the bullet below that names
`topology=web-box-rds-drive-off-box`.

Each run also writes two REALTIME lines from `deploy/load/realtime_lag.py`:
fifty bearer sockets in one tenant, every one of them owed every frame of twenty
widget touches pressed over REST, once inside the soak's last window and once
idle after it — `realtime=p95_commit_ms=<n> p95_ms=<n> p95_door_ms=<n> …
sockets=50 events=20 load=conc-<half the knee>|idle client=<where it ran> …
clock=<as declared>`. The ship number is the one under load; the
idle line is its control. On the production shape the probe runs on the drive
box (`client=drive-box`): the socket door takes a bearer
(`apps/realtime/middleware.py`), so the probe needs no ORM. `p95_commit_ms` is
frame-received less the frame's own `occurred_at` (stamped at emit, inside the
transaction), the bar's commit-to-push number and still an upper bound by the
service's work before `COMMIT`; `p95_ms` is press-sent to frame-received, the
older and looser bound, which includes `p95_door_ms`, the touch's own round
trip. Two clocks are in `p95_commit_ms`: each box half prints its chrony
offset (`envelope: clock System time …`), and the probe's `clock=` says what
it was handed, `undeclared` when nothing was.

- 2026-10-21 · sha `3590d6822433` · `t4g.large` · wall 55 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=2269 knee=conc-4 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32,64 --step-seconds 60 --seed 20260825 | conditions=size=t4g.large,scale=prepared,concurrency=4,err=0.0,throttled=0,topology=compose-one-host-drive-on-box | utilization=host_cpu=99.8,pg_total=15,pg_active=9`
  - `soak=unsteady concurrency=2 minutes=30 pool_budget=18 max_pg_total=19` — measured before `3ee59ec5f`, when the sampler counted its own psql backend: the 19 is 18 + 1 by mechanism, unmeasured
- 2026-10-21 · sha `ada1efce9192` · `t4g.large` · wall 43 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=2144 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32,64 --step-seconds 60 --seed 20260825 | conditions=size=t4g.large,scale=prepared,concurrency=16,err=0.0,throttled=556,topology=compose-one-host-drive-on-box | utilization=host_cpu=91.1,pg_total=18,pg_active=1`
  - `soak=steady concurrency=8 minutes=30 pool_budget=18 max_pg_total=18`
- 2026-10-21 · sha `332e06aaa3b6` · `t4g.large` · wall 41 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1613 knee=conc-4 | instrument=deploy/load/drive.py run --ladder 1,2,4 --step-seconds 60 --seed 20260825 | conditions=size=t4g.large,scale=prepared,concurrency=4,err=0.0,throttled=0,topology=compose-one-host-drive-on-box | utilization=host_cpu=99.9,pg_total=14,pg_active=5`
  - `soak=steady concurrency=2 minutes=30 pool_budget=18 max_pg_total=14`
- 2026-10-21 · sha `4a9b46fef2a6` · `t4g.large` · wall 41 min (box up to the line) · `scripts/envelope.sh` · `cpus=0.5` on web and worker during the soak (the CPU squeeze the pool-lockup fix was verified under)
  - `metric=p95_ms=1592 knee=conc-4 | instrument=deploy/load/drive.py run --ladder 1,2,4 --step-seconds 60 --seed 20260825 | conditions=size=t4g.large,scale=prepared,concurrency=4,err=0.0,throttled=0,topology=compose-one-host-drive-on-box | utilization=host_cpu=99.7,pg_total=14,pg_active=2`
  - `soak=steady concurrency=2 minutes=30 pool_budget=18 max_pg_total=14`
- 2026-10-22 · sha `5beeb7435171` · `t4g.large` · wall 40 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1285 knee=not_reached | instrument=deploy/load/drive.py run --ladder 1,2,4 --step-seconds 60 --seed 20260825 | conditions=size=t4g.large,scale=prepared,concurrency=4,err=0.0,throttled=0,topology=compose-one-host-drive-on-box | utilization=host_cpu=100.0,pg_total=14,pg_active=1`
  - `soak=steady concurrency=2 minutes=30 pool_budget=18 max_pg_total=15`
- 2026-10-22 · sha `8a7d3dc352d1` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 50 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=10102 p95_read_ms=10025 p95_write_ms=12394 knee=conc-32 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=32,err=3.79,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=94.7,organs_cpu=85.4,client_cpu=25.1,pg_total=18,pg_active=2 | bar=met`
  - `soak=unsteady concurrency=16 minutes=30 pool_budget=18 max_pg_total=19` — measured before the pool-lockup fix (`482f85789`) reached this branch
- 2026-10-22 · sha `f01d708fe650` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 49 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1243 p95_read_ms=642 p95_write_ms=1620 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=96.7,organs_cpu=84.1,client_cpu=21.9,pg_total=18,pg_active=1 | bar=met`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19` — the half-knee rerun before any instrument change (`911e6294b`), at a tip carrying the pool-lockup fix (`482f85789`): no wedge (err 0.00, p95 517–658 ms flat), the knee read conc-16 so half is 8, and the only broken bound is a real 19th connection on the app's database
- 2026-10-22 · sha `d7a5469acaf4` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 82 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1381 p95_read_ms=681 p95_write_ms=1800 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.07,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=96.8,organs_cpu=78.6,client_cpu=20.5,pg_total=18,pg_active=2 | bar=met`
  - `soak=unsteady concurrency=8 minutes=65 pool_budget=18 max_pg_total=18 outbox_pending=1260/11480 err_max=0.00 err_bound=0.5 max_worker_backlog=33851 broken=outbox` — the soak reading the outbox and the worker backlog (`d7a5469ac`), live: the 65-min soak outlived the boxes' 60-min idle wall; err 0.00 and p95 flat (487–558 ms), but the outbox grew ~850 rows a window and the worker's backlog ~2,550, linear from window 0
- 2026-10-22 · sha `d64dbe38de38` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 50 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1118 p95_read_ms=628 p95_write_ms=1611 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=96.3,organs_cpu=82.2,client_cpu=24.6,pg_total=18,pg_active=1 | bar=met`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19`
- 2026-10-22 · sha `2b76537a7eb4` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 25 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1120 p95_read_ms=590 p95_write_ms=1561 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=94.4,organs_cpu=86.9,client_cpu=22.9,pg_total=18,pg_active=1 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=18 outbox_pending=1406/2394 err_max=0.00 err_bound=0.5 max_worker_backlog=5327 broken=outbox`
- 2026-10-22 · sha `41144761cf1f` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 50 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1276 p95_read_ms=646 p95_write_ms=1703 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=95.8,organs_cpu=90.4,client_cpu=23.7,pg_total=18,pg_active=1 | bar=met`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19 outbox_pending=1004/4782 err_max=0.00 err_bound=0.5 max_worker_backlog=9147 broken=outbox,pg_total`
- 2026-10-22 · sha `650867d323a8` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 30 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1035 p95_read_ms=581 p95_write_ms=1379 knee=not_reached | instrument=deploy/load/drive.py run --ladder 2,4,8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=94.7,organs_cpu=85.7,client_cpu=21.5,pg_total=18,pg_active=0,idle_in_tx=7 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=19 max_idle_in_tx=11 outbox_pending=1404/2363 err_max=0.00 err_bound=0.5 max_worker_backlog=5324 broken=outbox,pg_total`
  - `realtime=p95_ms=333.4 p50_ms=201.7 max_ms=432.2 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=could-not-look sockets=50 events=20 load=conc-8 client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
- 2026-10-22 · sha `f11da07cbe3b` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 28 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1464 p95_read_ms=752 p95_write_ms=1816 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 2,4,8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=95.5,organs_cpu=85.8,client_cpu=22.1,pg_total=18,pg_active=2,idle_in_tx=10 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=18 max_idle_in_tx=10 outbox_pending=896/1407 err_max=0.00 err_bound=0.5 max_worker_backlog=2854 broken=outbox`
  - `realtime=p95_ms=304.8 p50_ms=225.6 max_ms=341.3 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=could-not-look sockets=50 events=20 load=conc-8 client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
- 2026-10-22 · sha `ffc25fea8ce6` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 26 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1322 p95_read_ms=647 p95_write_ms=1614 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=92.4,organs_cpu=89.0,client_cpu=24.2,pg_total=18,pg_active=3 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=19 outbox_pending=929/1459 err_max=0.00 err_bound=0.5 max_worker_backlog=2627 broken=outbox,pg_total`
- 2026-10-22 · sha `95ba77fe5fbe` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 24 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1387 p95_read_ms=672 p95_write_ms=1701 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=95.1,organs_cpu=80.6,client_cpu=25.6,pg_total=18,pg_active=2 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=18 outbox_pending=862/1452 err_max=0.00 err_bound=0.5 max_worker_backlog=2828 broken=outbox`
- 2026-10-22 · sha `5971f0f7c57d` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 26 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1370 p95_read_ms=597 p95_write_ms=10623 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 8,16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.44,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=92.8,organs_cpu=93.3,client_cpu=24.7,pg_total=19,pg_active=2 | bar=met`
  - `soak=unsteady concurrency=8 minutes=10 pool_budget=18 max_pg_total=18 outbox_pending=992/1523 err_max=0.00 err_bound=0.5 max_worker_backlog=2954 broken=outbox`
- 2026-10-22 · sha `6cad1e9cc6f9` · `c7g.large + m7g.large organs + t4g.medium drive` · wall 48 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1442 p95_read_ms=754 p95_write_ms=1858 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=93.4,organs_cpu=91.9,client_cpu=24.2,pg_total=18,pg_active=1 | bar=met`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19 outbox_pending=997/3568 err_max=0.00 err_bound=0.5 max_worker_backlog=6920 broken=outbox,pg_total`
- 2026-10-22 · sha `294308e44c93` · `c7g.large + m7g.large organs + t4g.large drive` · wall 46 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1522 p95_read_ms=768 p95_write_ms=1933 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.large,tenants=4,credentials=8 | utilization=host_cpu=92.2,organs_cpu=91.8,client_cpu=26.5,pg_total=18,pg_active=1,idle_in_tx=7 | bar=unmet(conc-8 never ran; the ladder stopped at conc-16)`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19 max_idle_in_tx=12 outbox_pending=582/2970 err_max=0.00 err_bound=0.5 max_worker_backlog=5903 max_host_cpu=97.6 max_organs_cpu=97.9 broken=outbox,pg_total`
  - `realtime=p95_ms=392.9 p50_ms=226.0 max_ms=417.7 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=could-not-look sockets=50 events=20 load=conc-8 client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
- 2026-10-22 · sha `98c4b17db46f` · `c7g.large + m7g.large organs + t4g.large drive` · host=bare · wall 45 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1343 p95_read_ms=653 p95_write_ms=1653 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 16 --step-seconds 60 --seed 20260825 | conditions=size=c7g.large,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.large,tenants=4,credentials=8 | utilization=host_cpu=90.1,organs_cpu=86.2,client_cpu=23.5,pg_total=18,pg_active=0,idle_in_tx=9 | bar=unmet(conc-8 never ran; the ladder stopped at conc-16)`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=18 max_pg_total=19 max_idle_in_tx=11 outbox_pending=506/3367 err_max=0.00 err_bound=0.5 max_worker_backlog=6143 max_host_cpu=94.6 max_organs_cpu=95.0 broken=outbox,pg_total`
  - `realtime=p95_ms=270.7 p50_ms=185.4 max_ms=304.2 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=could-not-look sockets=50 events=20 load=conc-8 client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
- 2026-10-22 · sha `cfabd61ef8ca` · `c7g.xlarge + m7g.large organs + t4g.medium drive` · host=bare · wall 49 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1125 p95_read_ms=568 p95_write_ms=1468 knee=conc-16 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.xlarge,scale=prepared,concurrency=16,err=0.0,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=57.6,organs_cpu=98.7,client_cpu=23.1,pg_total=25,pg_active=1,idle_in_tx=11 | bar=met`
  - `soak=unsteady concurrency=8 minutes=30 pool_budget=26 max_pg_total=27 max_idle_in_tx=11 outbox_pending=1127/5727 err_max=0.00 err_bound=0.5 max_worker_backlog=8911 max_host_cpu=76.7 max_organs_cpu=99.1 broken=outbox,pg_total`
  - `realtime=p95_ms=219.7 p50_ms=179.5 max_ms=284.1 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=could-not-look sockets=50 events=20 load=conc-8 client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=drive-box exit=2 why=50-of-50-sockets-missed-press-1-within-60.0s;-0-of-1000-frames-arrived-(is-the-worker-up-on-this-checkout's-task-queue?)`
- 2026-10-22 · sha `269e37909962` · `c7g.xlarge + m7g.xlarge organs + t4g.medium drive` · host=bare · wall 52 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=10032 p95_read_ms=1272 p95_write_ms=11553 knee=conc-32 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 | conditions=size=c7g.xlarge,scale=prepared,concurrency=32,err=1.99,throttled=0,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=59.8,organs_cpu=51.9,client_cpu=22.0,pg_total=25,pg_active=2,idle_in_tx=11 | bar=met`
  - `soak=unsteady concurrency=16 minutes=30 pool_budget=26 max_pg_total=27 max_idle_in_tx=13 outbox_pending=9/8 err_max=0.06 err_bound=0.5 max_worker_backlog=2 max_host_cpu=70.0 max_organs_cpu=64.0 broken=pg_total`
  - `realtime=p95_ms=285.8 p50_ms=178.8 max_ms=295.7 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=p95_ms=1235.1 p50_ms=959.5 max_ms=1242.1 sockets=50 events=20 load=conc-16 client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`
  - `realtime=p95_ms=271.3 p50_ms=180.6 max_ms=287.0 sockets=50 events=20 load=idle client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses`

**The instrument's second era starts here**: from here down `instrument=` names its pacer (`drive.py judge --restamp` wrote it into the lines recorded before the drive printed it), and every line above was recorded by the instrument whose string names none, so no line above is compared with one below (§ 1's same-instrument rule).

- 2026-10-23 · sha `60b4bc6c820c` · `t4g.large` · host=bare · wall 23 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1033 p95_read_ms=870 p95_write_ms=1788 knee=not_reached | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 pacer=9.5/s | conditions=size=t4g.large,scale=prepared,concurrency=32,err=0.0,throttled=0,pacer=9.5/s,topology=compose-one-host-drive-on-box,client=unstated,tenants=1,credentials=1 | utilization=host_cpu=99.9,client_cpu=not_sampled,pg_total=21,pg_active=1,idle_in_tx=3 | bar=unjudged(topology=compose-one-host-drive-on-box is not web-box-organs-box-drive-off-box; credentials=1 is below 4) | validity=INVALID: one credential above one client`
  - `soak=steady concurrency=16 minutes=10 pool_budget=26 max_pg_clients=24 max_pg_total=24 max_idle_in_tx=7 outbox_pending=16/14 err_max=0.00 err_bound=0.5 max_worker_backlog=12 max_host_cpu=100.0 max_organs_cpu=-`
  - `realtime=could-not-look sockets=50 events=20 load=conc-16 client=one-box exit=2 why=could-not-read-the-credentials-in-/work/probe-credentials.json:-PermissionError`
  - `realtime=could-not-look sockets=50 events=20 load=idle client=one-box exit=2 why=could-not-read-the-credentials-in-/work/probe-credentials.json:-PermissionError`
- 2026-10-23 · sha `60b4bc6c820c` · `c7g.xlarge + m7g.xlarge organs + t4g.medium drive` · host=bare · wall 142 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=10110 p95_read_ms=10021 p95_write_ms=11602 knee=conc-32 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32 --step-seconds 60 --seed 20260825 pacer=9.5/s | conditions=size=c7g.xlarge,scale=prepared,concurrency=32,err=2.83,throttled=0,pacer=9.5/s,topology=web-box-organs-box-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=56.8,organs_cpu=43.4,client_cpu=22.8,pg_total=25,pg_active=1,idle_in_tx=4 | bar=met`
  - `soak=steady concurrency=16 minutes=120 pool_budget=26 max_pg_clients=26 max_pg_total=27 pg_other=autovacuum_worker:1 max_idle_in_tx=7 outbox_pending=10/9 err_max=0.17 err_bound=0.5 max_worker_backlog=4 max_host_cpu=74.4 max_organs_cpu=70.3`
  - `realtime=p95_commit_ms=166.5 p95_ms=206.6 p95_door_ms=118.1 p50_ms=183.1 max_ms=295.8 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=-0.000000878s,drive=-0.000000342s`
  - `realtime=p95_commit_ms=825.7 p95_ms=1208.2 p95_door_ms=1200.5 p50_ms=1022.5 max_ms=1416.1 sockets=50 events=20 load=conc-16 client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=-0.000000878s,drive=-0.000000342s`
  - `realtime=p95_commit_ms=231.7 p95_ms=269.1 p95_door_ms=116.1 p50_ms=181.4 max_ms=313.4 sockets=50 events=20 load=idle client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=-0.000000878s,drive=-0.000000342s`
- 2026-10-24 · sha `06dfeb6484f8` · `t4g.large + db.t4g.micro RDS + t4g.medium drive` · host=bare · wall 44 min (box up to the line) · `scripts/envelope.sh`
  - `metric=p95_ms=1062 p95_read_ms=489 p95_write_ms=1602 knee=conc-4 | instrument=deploy/load/drive.py run --ladder 1,2,4,8,16,32,64 --step-seconds 60 --seed 20260825 pacer=9.5/s | conditions=size=t4g.large,scale=prepared,concurrency=4,err=0.0,throttled=0,pacer=9.5/s,topology=web-box-rds-drive-off-box,client=t4g.medium,tenants=4,credentials=8 | utilization=host_cpu=99.7,client_cpu=22.3,pg_total=14,pg_active=1,idle_in_tx=2 | bar=unjudged(topology=web-box-rds-drive-off-box is not web-box-organs-box-drive-off-box)`
  - `soak=steady concurrency=2 minutes=30 pool_budget=18 max_pg_clients=14 max_pg_total=14 pg_other=autovacuum_worker:1 max_idle_in_tx=5 outbox_pending=17/22 err_max=0.00 err_bound=0.5 max_worker_backlog=36 max_host_cpu=99.9 max_organs_cpu=-`
  - `realtime=p95_commit_ms=465.7 p95_ms=511.7 p95_door_ms=211.4 p50_ms=364.7 max_ms=555.1 sockets=50 events=20 load=idle-before client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=+0.000000257s,drive=+0.000001656s`
  - `realtime=p95_commit_ms=3118.7 p95_ms=3367.5 p95_door_ms=1209.0 p50_ms=2285.3 max_ms=4931.1 sockets=50 events=20 load=conc-2 client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=+0.000000257s,drive=+0.000001656s`
  - `realtime=p95_commit_ms=649.1 p95_ms=803.8 p95_door_ms=411.1 p50_ms=424.1 max_ms=2446.2 sockets=50 events=20 load=idle client=drive-box path=dispatch relay_poll_seconds=300 basis=1000-frames-over-50-sockets-x-20-presses clock=web=+0.000000257s,drive=+0.000001656s`
<!-- recorded-knees end -->

---

## 10 · Shapes — what each deployment shape carries, what says it ran out, and the move

Of the shapes this tree ships, `provision.sh infra`'s day-zero shape is measured — one `t4g.large` box holding every service but Postgres, `db.t4g.micro` RDS beside it, the worker count `env-file` derives for that class (`topology=web-box-rds-drive-off-box`, the § 9 bullet `06dfeb6484f8`), its `latency` alert's receiver quiet through the ladder and the soak — consistent with the rule as far as the record reads (the bullet's own read latency at the knee sits under the read budget), and not yet proof the route can open (the alert-state column the wrapper does not yet record) — as are S1 and S2 below, while a deployed S2 and S3 are not. A shape is a topology the envelope measures — § 9's `topology=`. The table is the
template's; a product's own shape beyond `infra` (a managed Redis, a second box) is a row the
product adds from its own run on its own stage; `infra`'s own row is the template's,
measured above. **Every measured line is a § 9 bullet cited by its sha, and no number from
it is retyped here** — the bullet is the one place it lives, and this chapter's own rule
is that a number spelled twice disagrees with itself. The triggers are alert KEYS and
sampler keys, never thresholds: `docs/runbooks/alerts.md` § "Values, and why each one"
owns every threshold and window. `quality/tests/test_runbook.py` reads the table: a
cited sha that is not a § 9 bullet, a trigger key the alert census or the sampler does
not declare, or a move that is neither a `--shape` `scripts/envelope.sh` takes nor
a move the tree lacks with the release it is due in, is a red test.

| shape | what runs where | classes (no prices — the price list moves) | measured line | trigger | move, and its rollback |
|---|---|---|---|---|---|
| S1 | one box, dev and demo: compose on one host with the drive on the same box (`topology=compose-one-host-drive-on-box`) | `t4g.large` — burstable, so a run spends credits as well as a machine (§ 7's caution) | `3590d6822433` (the first line; its soak predates the sampler's fix and the pool-lockup fix); `5beeb7435171` (the pool-lockup fix: the soak `steady`) | `latency` or `error_rate` OPEN for consecutive windows; or the sampler's `host_cpu` held above the share the product declares across soak windows | to S2: measured by `scripts/envelope.sh <sha> --shape prod`, whose rollback is its own exit — every box down either way; the deployed move is not in the tree (`provision.sh` has no organs-box target; due in 2.5.1) |
| S2 | the production shape: web, worker, frontend and Caddy on the web box; every organ (Postgres, Redis, Temporal, Zitadel, ClickStack, the object store) on the organs box; the drive off both (`topology=web-box-organs-box-drive-off-box`) | `c7g.xlarge` web, non-burstable, running two worker processes; `m7g.xlarge` organs; `t4g.medium` drive, for measuring only | `60b4bc6c820c` (the ship line: one ladder, the soak at half its knee `steady`, and the socket run under that load and idle; the earlier S2 lines are § 9's bullets above it) | `latency` or `error_rate` OPEN for consecutive windows; the web box's `host_cpu` high while `organs_cpu` is not says the web box is the axis (§ 7, the method's first rule) | to S3: not in the tree (a second web box, with its ADR, is due in 2.5.1); one box back down to S1 is `scripts/envelope.sh <sha> --shape one-box`, kept for comparison |
| S3 | two web boxes behind Caddy; Postgres on RDS; the other organs on the organs box | `c7g.large` × two web; RDS `db.t4g.small` — the smallest class the app's slots fit (`db.t4g.micro` does not) | `unmeasured` | `latency` or `error_rate` OPEN for consecutive windows, read per web box | not in the tree (due in 2.5.1, with the replica ADR; replicas need the media census, the pool budget summed over replicas and Caddy's upstreams first) |

### Sizing — from expected users to a shape

A team sizes from users first, and every step below is a citation, not a new number.

- **Users to closed-loop clients — a model, labelled so.** The envelope's load is a drive
  concurrency: a closed-loop client with no think time, which is many people's worth of
  traffic, not one person. The users-per-client ratio — the door requests a client
  makes, against what a person makes — is a model this chapter does not carry: a product
  measures its own think time on its own stage before it sizes by users.
- **Clients to a shape — the margin is the soak's.** A shape covers a load when that load
  is at most half its measured knee, because half the knee is what § 8 holds for the soak:
  the load a deployment carries all day. The knee is the `knee=` of the shape's cited
  bullet; the half is that bullet's soak line, `concurrency=`.
- **Clients to connections.** One pooled connection per client for the request's whole
  wall, plus the worker's; the sum is ADR config-1's pool budget and the soak line's
  `pool_budget=` is the budget the run judged against.

**Worked example — one small customer.** The release's bar is "a small customer's busiest
hour with margin": the client count of the `concurrency=` in the production bullet of
`60b4bc6c820c`, the S2 row's ship line — half the knee its `knee=` names. On S2 the doors
and the worker both carry it: that soak is `steady`, its `err_max=` under its `err_bound=`
and its `max_worker_backlog=` flat, so the answer is **S2**. A customer whose client
count — from its own measured think time — is above that half is past S2's margin, and the
next shape is S3, `unmeasured`.

### The move from S1 to S2, as the envelope runs it

`scripts/envelope.sh <sha> --shape prod` is the only S1 → S2 move in the tree, and it is
a measurement on throwaway verifier boxes, not a deploy. Its printed steps, in order:

Before the numbered steps, three boxes come up — the organs and web boxes on-demand (a
spot reclaim of either loses the run), the drive box spot. Then the seven printed steps, in
order:

- the group admits the envelope's own traffic: the drive probes the web box's TLS
  port and the organs' object store, the web box probes every port in `ORGAN_PORTS`; a port
  the group drops prints the owner's one ingress command and stops the run;
- the organs box: every organ of `deploy/compose.yaml --profile laptop`, each
  published on its private address (`deploy/load/compose.organs.yaml`), its environment
  handed to the web box;
- the web box: builds the images, migrates, then runs web, worker, frontend and
  Caddy against the organs (`deploy/load/compose.web.yaml`), grants, seeds the tenants and
  mints one token per client;
- the pre-spend baseline (§ 7) over § 2a's census on the organs box — a dirty one
  voids the run;
- the drive box, handed its credentials and the web box's CA, runs the ladder and
  the soak;
- every box's samples join the run's own files;
- the lines, recorded: `drive.py judge` writes them and they land in § 9.

**Rollback** is the script's exit: every box it brought up goes down either way, and a box
it could not take down is named with the command that does. **What is not built:**
`deploy/provision.sh` offers no organs-box target — `infra` makes the one box with RDS
beside it — so a deployed S2 is not in the tree (due in 2.5.1), and a
team that wants it today runs the two compose files above by hand.

Declared blind spots: a product's shape is the product's row; the triggers are keys, not
tuned thresholds; the sizing is one measured shape and a model, and says so; the census
reads the move's step names, never runs them.

---

## What is driven and what is only bound

`quality/tests/test_runbook.py` lifts the marked blocks out of this
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
- **§ 3's reboot resilience.** Two clean stop/start cycles were observed during the
  resize; a reboot is unproven, `docs/runbooks/deploy.md`'s opening blind spot owns the
  question, and nothing here re-proves it.
- **§ 4's A/B and § 7's ladder.** A load run is a paid performance against a
  deployed box, not a document test. Its output is an envelope, and the envelope
  is reviewed by a human reading four-part lines.
- **All of the prose.** Only the fenced blocks under markers are executed. A
  wrong sentence beside a right recipe is invisible to the drive exactly as it
  is to a reviewer — which is why every claim above cites the row that paid for
  it, so a reader can check the sentence against the ledger.
