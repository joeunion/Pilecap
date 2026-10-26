# ADR deploy-4

- **ADR deploy-4 (2026-08-31) — build once, promote by digest** ·
  context: **one tree was built three times.** CI built `web` and `worker`
  single-arch, tagged them locally, checked the `USER` line, and let both die
  with the runner — so nothing CI built ever reached a box, and "CI-tested
  image" was a phrase with no referent. `deploy/compose.yaml` carried a
  `build:`, and runbook step 33 built the same tree a **third** time, arm64, on
  the Graviton box: the slowest and least debuggable machine in the system, at
  the moment of a deploy. Three builds of "the same" tree is three chances to
  differ — a base image that moved, a transient mirror, a wheel rebuilt — and
  nothing anywhere could say whether the amd64 thing CI proved and the arm64
  thing the box ran were the same software. · decision: **(a)** the image for a
  tree is built **once**, in CI's images job, `linux/amd64` **and**
  `linux/arm64` in one manifest, pushed to a registry under the derived tree tag
  `tree-<12hex>`; **(b)** that job runs `needs: gate` — a registry tag is a
  promotable artefact and `release.sh` will deploy anything the registry has, so
  an ungated tree must have no tag; **(c)** `deploy/compose.yaml` declares no
  `build:` anywhere and every app image is `${DJB_IMAGE_REGISTRY}/djb-<service>:
  ${DJB_IMAGE_TAG}`, both required and neither defaulted; **(d)** `release.sh`
  resolves the tag to an immutable **digest** before its first act — a tag the
  registry lacks is exit 2 naming the reference, a registry/pin disagreement is
  exit 1 naming both — and pins the released digest into the box's `TREE` marker
  **after** act 6's recreate; **(e)** `TREE`'s grammar becomes line-oriented
  (line 1 the tag, later lines `<key> <value>`) so it can carry that pin, which
  a legacy one-line marker still satisfies; **(f)** **promotion staging→prod is
  neither a re-tag nor a rebuild** — both environments point `DJB_IMAGE_TAG` at
  the same tree, resolve the same digest, and run the same bytes. · rejected:
  **moving environment tags (`:staging`, `:prod`)** — the industry-default shape,
  and it makes "which image is prod running" unanswerable *from the box*, which
  is the exact class of lie the `TREE` mechanism was built to remove; **keeping
  the box build as a fallback for a registry outage** — a fallback that only
  runs on the worst day is a path nothing exercises, and it re-opens the
  divergence the whole ruling closes (the honest trade is stated instead: the
  registry is now a deploy-time dependency, named in `docs/runbooks/deploy.md`
  step 33); **pushing from the laptop** — then the deployed artefact's
  provenance is a person's machine; **content-addressed tags only, no tree tag**
  — a digest a human cannot derive from a checkout makes every runbook step a
  copy-paste of an opaque string. · trigger to revisit: either of two, both cheap to notice —
  **base-image drift between releases** — two trees a month apart resolve
  different base layers and nothing here compares them, so the first product
  that needs reproducible builds re-opens this with a pinned base digest; and
  **a second architecture or a second registry** (a product deploying to
  something other than one ECR account) — `DJB_IMAGE_REGISTRY` is one prefix
  today and that is deliberate, not permanent.
