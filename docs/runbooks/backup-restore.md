# Backup and restore — the drill, performable on a laptop

**An untested backup is a hypothesis.** This runbook is how the hypothesis
becomes a fact: a dump is taken off a running deployment, it leaves that
deployment, and it is restored into a *different* running deployment, which is
then asked — through its own front door, over TLS — for a row that only the
first one ever had.

Everything in Part 1 runs on one laptop with no AWS account and no cost, which
is the point: a drill that needs a cloud is a drill nobody performs. Part 2 is
the managed layer, and it is **deferred** — see it before you believe this
document covers your data.

| Part | What it proves | Where it runs | Status |
|---|---|---|---|
| 1 · The laptop drill | the logical layer: `pg_dump -Fc` restores into a *deployment*, and today's code can run the schema it produced | one laptop, two compose stacks | **performable now** |
| 2 · The managed layer | RDS automated snapshots restore to a scratch instance the app can boot against | AWS, after the box exists | **deferred to V1's tail** |

---

## The two layers, and why one of them is not here yet

**The logical layer** is `scripts/backup.sh` and `scripts/restore_drill.sh`: a
portable `pg_dump -Fc` object and a drill that restores it. Portable is the
whole value — it is the layer a non-AWS restore needs, the layer a second
environment is seeded from, and the layer that survives the platform account
being the thing that is broken.

**The managed layer** is the platform's: RDS automated snapshots, a retention
window, point-in-time recovery. ADR deploy-1 chose it deliberately — managed
snapshots ARE half the backup posture, and none of a retention policy belongs
in a script in an application repository.

The managed layer is **deferred to V1's tail** and is performed, when the box
exists, as follows: an RDS snapshot restored to a scratch instance,
the app booted against it, a row written before the snapshot read back after,
the scratch instance torn down with a census showing zero orphan instances.
Nothing in this document proves it, and no reading of Part 1 should be mistaken
for it. Part 1 proves the *portable* layer, on the *laptop*.

**RPO is not stated here** and will not be until the snapshot cadence is an
observed value on a real instance rather than an aspiration — that belongs with
Part 2.

**The drill cadence is deferred too**: this document proves the mechanism once.
*How often* the drill is re-performed is the consuming product's schedule to
set — typically `asserted:owner — before pilot users`, with a standing path
re-trigger `paths:apps/events/**,apps/workflows/**` (any outbox, ledger or
reconciler change re-opens the question).

**Object storage: `--to-s3` has no local twin yet.** `backup.sh --to-s3` and
`--to-dir` are one code path with two targets, so the copy is exercised on a
laptop — but the *S3 API* is not. The trigger for closing that is bringing
MinIO into the compose stack as the S3-compatible local endpoint (see
`docs/product/adrs-ingredients.md` for the recommended default and its stated
price: one more compose service, and an S3-compatibility assumption). When MinIO
lands, `--to-s3` is drillable locally and step 6 below stops being a stand-in.
Until then the S3 leg is proven only against real S3, in Part 2's environment.

---

## Part 1 · The laptop drill

Two deployment stacks on one machine. **Stack A** is the deployment being backed
up; **stack B** is the one the backup is restored into. B is destroyed and
rebuilt by this drill; A is never touched, and step 8 proves it.

You need `deploy/compose.second.yaml` (the ports override) — without it the two
stacks fight over host 80/443. It is described in `docs/runbooks/deploy.md`
after step 8 and it changes nothing but where Caddy's ports land.

**1. Check what is already holding the ports.** Never `down` a project you did
not bring up, and never kill a container by name.

```bash
docker compose ls
docker ps --format '{{.Names}}\t{{.Ports}}'
```

Pick two free port pairs. This runbook uses `8080/8443` for A and `9080/9443`
for B; if a stack already holds those, pick others — `DJB_HTTP_PORT` and
`DJB_HTTPS_PORT` are parametric precisely so an Nth stack is possible.

**2. Generate an environment per stack.** One file each, mode 600, nothing
copied and nothing typed. Each stack's containers read *their own* file, so the
`DJB_SECRETS_SOURCE` line has to be re-pointed at it — the generator writes
`file:/deploy/.env`, which is right for a single stack and wrong for two.

```bash
./deploy/provision.sh env-file deploy/.env.b1a laptop
./deploy/provision.sh env-file deploy/.env.b1b laptop

# The generator writes `file:/deploy/.env` into every file it makes, which is
# right for one stack and wrong for two. Re-point each file at itself:
for s in b1a b1b; do
  sed -i '' "s|file:/deploy/\.env'|file:/deploy/.env.${s}'|" "deploy/.env.${s}"
done

# and each knows its own edge, so CSRF and absolute links carry the right port
sed -i '' "s|^CSRF_TRUSTED_ORIGINS='https://localhost'|CSRF_TRUSTED_ORIGINS='https://localhost:8443'|" deploy/.env.b1a
sed -i '' "s|^PUBLIC_BASE_URL='https://localhost'|PUBLIC_BASE_URL='https://localhost:8443'|" deploy/.env.b1a
sed -i '' "s|^CSRF_TRUSTED_ORIGINS='https://localhost'|CSRF_TRUSTED_ORIGINS='https://localhost:9443'|" deploy/.env.b1b
sed -i '' "s|^PUBLIC_BASE_URL='https://localhost'|PUBLIC_BASE_URL='https://localhost:9443'|" deploy/.env.b1b
```

(On Linux, `sed -i` without the `''`.) Both files are already covered by
`.gitignore`'s `.env.*`; check with `git check-ignore -v deploy/.env.b1a` before
you believe it.

**3. Bring both stacks up**, each with its own project name and its own ports.
Two minutes each on a first start: Temporal migrates two schemas and Zitadel
bootstraps its first instance.

```bash
# The images first, ONCE, and shared by both stacks — deploy/compose.yaml has no
# `build:` any more (ADR deploy-4: one image per tree, built in CI, pulled
# everywhere). On a laptop the two names are local and no registry is consulted;
# `--build` on the `up` below would now be an unknown-service error, not a build.
export DJB_IMAGE_TAG="$(./deploy/provision.sh image-tag)"
docker build --target web    -t "$(./deploy/provision.sh image-ref web)" .
docker build --target worker -t "$(./deploy/provision.sh image-ref worker)" .

DJB_HTTP_PORT=8080 DJB_HTTPS_PORT=8443 \
  docker compose -p djb-b1a --env-file deploy/.env.b1a \
  -f deploy/compose.yaml -f deploy/compose.second.yaml --profile laptop up -d

DJB_HTTP_PORT=9080 DJB_HTTPS_PORT=9443 \
  docker compose -p djb-b1b --env-file deploy/.env.b1b \
  -f deploy/compose.yaml -f deploy/compose.second.yaml --profile laptop up -d
```

**Both `.env.b1a`/`.b1b` carry `DJB_IMAGE_REGISTRY='local'`** (the generator
writes it for the `laptop` environment), so both stacks resolve the *same* two
local image names — which is the point of a restore drill: two stacks, one
tree, and any difference between them is the drill's and not the image's.

Confirm they are two stacks and not one:

```bash
docker ps --filter name=djb-b1 --format '{{.Names}}\t{{.Ports}}'
docker volume ls --filter name=djb-b1
```

Every container name is prefixed with its project, and `djb-b1a_db_data` and
`djb-b1b_db_data` are two volumes. That separation is Docker's, not this
repository's — see the blind spots at the end.

**4. Release each stack**, exactly as `docs/runbooks/deploy.md` steps 10–13:
`migrate` as the schema owner, generate and apply `grants.sql.py`, restart
`web` and `worker`. Do it once per stack, substituting the project name, the env
file, **and the network name** — step 12 there reaches Postgres with `docker run
--network djb-deploy_default`, which is `djb-b1a_default` / `djb-b1b_default`
here. Then confirm each edge answers on its own port:

```bash
curl -sk https://localhost:8443/readyz    # A
curl -sk https://localhost:9443/readyz    # B
# both: {"db": true, "cache": true, "channel_layer": true, "temporal": true}
```

**5. Put a KNOWN ROW on stack A, through its front door.** Not through the ORM
and not through `psql`: the row has to arrive the way a customer's row arrives,
or the drill proves the database and not the deployment.

The one-offs below run as `oneoff` — the `compose run` door, and why, at
`docs/runbooks/deploy.md` Part 1. Both stacks are already up by this
step, so nothing here needs a dependency graph.

```bash
docker compose -p djb-b1a --env-file deploy/.env.b1a -f deploy/compose.yaml --profile laptop \
  run --rm -T oneoff python manage.py seed --force
docker compose -p djb-b1a --env-file deploy/.env.b1a -f deploy/compose.yaml --profile laptop \
  run --rm -T oneoff python manage.py issue_token \
  --email owner@example.com --tenant acme --name b1a-known-row \
  --scope widgets:write
# `--scope` is required — a token is minted with a stated reach, never a
# default one. Writing widgets is the whole of what this drill's token does.
TOKEN_A=<the token that prints>

curl -sk -X POST https://localhost:8443/api/v1/widgets/ \
  -H "Authorization: Bearer $TOKEN_A" -H 'Content-Type: application/json' \
  -d '{"name": "B1-PRIME-KNOWN-ROW"}'
```

Give stack B a **different** row the same way — `B-ORIGINAL-ROW-MUST-VANISH` —
so the restore is seen to *replace* a live deployment's data rather than fill an
empty database. A restore into an empty target proves much less than it looks
like it proves.

**6. Take the backup off stack A, and make it leave.**

```bash
./scripts/backup.sh --stack djb-b1a --env-file deploy/.env.b1a --to-dir /tmp/offsite
```

`--stack` points `pg_dump` at that compose project's `db` container and reads
the database name and the master role out of that stack's env file. `--to-dir`
is the copy: **the same code path `--to-s3` takes**, to a target a laptop has.
On a box the flag is `--to-s3 <bucket/prefix>` and everything above the copy is
byte-for-byte the same work. Read the size it prints; the script refuses a dump
under 1 KiB, because a small file nobody looks at is a backup everyone believes
in.

Beside the dump you now have a `<dump>.origin` — six lines naming the compose
project, the database, the env file, the UTC stamp and the tree. Step 7 cannot
run without it. It is written **only** for `--stack` dumps: the plain
`./scripts/backup.sh` laptop path is unchanged, byte for byte, and a dump that
cannot be aimed at a live stack needs no guard rail.

**7. Prove the drill refuses to be the hazard**, before you let it run for real.
Three refusals, all cheap, all worth performing every time:

```bash
# 7a. the restore target IS the source -> exit 1, refused by name
./scripts/restore_drill.sh backups/<dump> --into-project djb-b1a --env-file deploy/.env.b1a

# 7b. a dump with no origin, aimed at a live stack -> exit 2, could not look
./scripts/restore_drill.sh /tmp/some-plain.dump --into-project djb-b1b --env-file deploy/.env.b1b

# 7c. a mistyped flag -> exit 2, never a silent default
./scripts/restore_drill.sh backups/<dump> --into-projekt djb-b1b
```

**Exit 1 is "I looked and it is wrong"; exit 2 is "I could not look."** They are
different causes and a caller may not treat them alike. 7b is the one worth
understanding: being unable to prove the target is not the source is not the
same as proving it is not, so the script fails closed.

**8. Restore into stack B.**

```bash
./scripts/restore_drill.sh backups/<dump> --into-project djb-b1b --env-file deploy/.env.b1b
```

It stops `web` and `worker` on B (the app would otherwise reconnect into a
half-restored schema), drops and recreates B's application database, restores,
**re-applies the grants**, starts the two containers again and runs
`migrate --check` inside B's own image. The organs — `db`, `redis`, `temporal`,
`zitadel`, `caddy` — stay up throughout.

The re-grant is not bookkeeping. A restore does not replace a schema in place;
it drops a database and builds another one, and GRANTs are per-database, so the
restored tables come back owned by the master role and readable by nobody else.
An app that comes up unable to read a single row it just restored is the
"restore that looked like it worked", and it is what this step exists to make
impossible. It runs `grants.sql.py` **without** `--create-role`: a Postgres role
is cluster-wide and survives its database being dropped, so the role is still
there and no password is needed. If the role is genuinely absent, psql says so
by name and you run the release step (`deploy.md` steps 11–12).

**9. Take the census.** This is the step that turns "the restore completed" into
"the deployment is running the restored data".

```bash
# the KNOWN ROW, through stack B's own REST door, over TLS, on B's port
curl -sk https://localhost:9443/api/v1/widgets/ -H "Authorization: Bearer $TOKEN_A"
#  -> B1-PRIME-KNOWN-ROW, count 1.  Note the token: it is STACK A's, and it
#     works on B because the credential came over in the dump.

# B's own pre-restore token -> 401. Its database is gone, which is the point.
curl -sk https://localhost:9443/api/v1/widgets/ -H "Authorization: Bearer $TOKEN_B"

# B's row that had to vanish
docker compose -p djb-b1b --env-file deploy/.env.b1b -f deploy/compose.yaml --profile laptop \
  exec -T db psql -U djb_master -d djb_laptop -tAc \
  "SELECT count(*) FROM example_widget WHERE name='B-ORIGINAL-ROW-MUST-VANISH'"   # 0

# the schema, both stacks, read and not guessed
docker compose -p djb-b1a ... run --rm -T oneoff python manage.py introspect > /tmp/iA.txt
docker compose -p djb-b1b ... run --rm -T oneoff python manage.py introspect > /tmp/iB.txt
diff <(sed -E 's/0x[0-9a-f]+/0xADDR/g' /tmp/iA.txt) <(sed -E 's/0x[0-9a-f]+/0xADDR/g' /tmp/iB.txt)

# and stack A, unchanged by any of it
docker compose -p djb-b1a ... exec -T db psql -U djb_master -d djb_laptop -tAc \
  "SELECT count(*) FROM example_widget"
```

**Normalise the addresses before diffing `introspect`.** Its URL-map section
prints `repr()` of live view objects, which carries a process-local memory
address, so two identical schemas differ on three lines for a reason that has
nothing to do with either. Ask Postgres the same question if you want a diff
with no normalisation in it:

```bash
... exec -T db psql -U djb_master -d djb_laptop -tAc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
```

**`manage.py zitadel_audit` on a laptop reports that it cannot look**, not that
it found drift: `ZITADEL_ISSUER and ZITADEL_PAT must both be set. There is
nothing to compare against.` (exit 1). That is true on stack A as well as stack
B, so it is a fact about the laptop environment and not about the restore. On a
box, where the pair is set, it is the read-only drift tripwire for the console
that no check can see (house rule 27), and its verdict on a restored environment
is expected to be *drift*: Zitadel's own database rides the same `db` container
on a laptop and comes back with the dump, but on a box it does not, and the
identity platform's rows are not this backup's subject. **The app rows are.**

**10. Tear both stacks down, and prove you did.**

```bash
COMPOSE_PROJECT_NAME=djb-b1a ./deploy/teardown.sh local --purge
COMPOSE_PROJECT_NAME=djb-b1b ./deploy/teardown.sh local --purge

docker compose ls          # no djb-b1a, no djb-b1b
docker ps -a --filter name=djb-b1   # empty
docker volume ls --filter name=djb-b1   # empty
```

`teardown.sh` calls `docker compose` without `-p`, so it would take down
`djb-deploy` if you did not name the project. `COMPOSE_PROJECT_NAME` outranks
the `name:` in the compose file, which is why it is set on the command line
here. Remove the two env files as well; `teardown.sh` only knows about
`deploy/.env`.

---

## Part 2 · The managed layer — deferred to V1's tail

Performed, when the box exists, as follows:

1. Confirm RDS automated backups are on, and record the observed retention
   window and snapshot cadence — the numbers, not the intention.
2. Restore one snapshot to a scratch instance.
3. Point a throwaway app container at it and boot.
4. Read back a row written before the snapshot was taken.
5. Tear the scratch instance down, and paste the census: zero orphan instances.
6. State the RPO, derived from (1) plus the logical dump schedule.

Until every one of those six has been performed, "automated backups: on" is a
console checkbox nobody has ever cashed, and this document says so rather than
implying otherwise.

---

## What this drill does not cover

- **It restores an application database, not RDS.** The managed layer is Part 2
  and it is not done. A laptop `db` container and an RDS instance fail in
  different ways and only one of them is exercised here.
- **Two co-resident stacks never sharing a volume is a Docker fact, not a
  deployment fact.** Project-scoped volume names are how compose has always
  worked; this drill relies on it and proves nothing about it.
- **Zitadel's schema rides the same `db` container on a laptop and restores with
  it** — which is *more* than a box's layout gives, not less. On a box the
  identity platform is its own thing with its own posture, and a restore of the
  application database says nothing about it.
- **Restore-at-scale timing is unmeasured.** The dumps here are seed-sized. How
  long a real restore takes is an observation to be recorded when there is a
  real database, and it is never a gate criterion.
- **`--to-s3` is exercised as a code path, not against the S3 API.** See the
  MinIO trigger above.
- **Nothing here is scheduled.** There is no cron, no beat and no timer, by
  design — anything that waits or retries in this system is a workflow. Who runs
  this drill and how often is the consuming product's decision, recorded above
  as a declared deferral rather than left to be discovered.
