# ADR deploy-4a

- **ADR deploy-4a — SIGNED by the owner 2026-09-19 ("sign all three", recorded by the PM).** The text below is
  the amendment as the engineering lead wrote it, copied here unchanged for the
  owner to sign; nothing in it is settled until they do, and the builder who
  copied it may not flip this line. *"ADR deploy-4a (2026-09-19, owner) — the
  image is built by the acceptance box of the on-box bank, from the banked
  tree, after the composed verdict row is written and before the boxes go down;
  CI's `images` job keeps `needs: verdict` and skips a tag the registry already
  holds. Which principle: 6 (reversible — the skip is one step; delete it and
  CI builds again) and 7 (the critical path: a stage deploy no longer waits on
  a second full gate on GitHub runners). Why the default is insufficient: the
  CI build sits behind a 30-40 min gate re-run nobody here measures, so
  `pushed → staged ≤ 5 min` is unreachable while it stands. Alternatives: a CI
  job without `needs: verdict` (rejected — an ungated tag is a red tree one
  command from prod, deploy-4 (b)); building on the stage box (rejected in
  deploy-4). Risk: a box with push credentials — mitigated by the OIDC-shaped
  least-privilege role scoped to two repositories and the namespace tag, and
  the invariant that the build starts only after `gate_ledger_record` returned
  0 for the same tree. Reversal: remove the bank step and the skip; CI builds
  as before. Temporary or permanent: permanent, reviewed at the first
  registry/verdict disagreement (the trigger: `image-digest` present for a tree
  with no `full` row)."* · **one thing the signature also decides, surfaced by
  the build and not in the text above:** what the bank pushes is what the box
  can build natively — `linux/arm64` on a Graviton verifier box, measured at 39
  s a service, where deploy-4 (a) says one manifest carrying `linux/amd64` AND
  `linux/arm64`. Building both on the box means QEMU emulation for the half the
  box is not, which is the cost deploy-4a exists to remove; skipping CI's job
  for a bank-built tag therefore leaves that tree's tag single-architecture.
  Every machine this template deploys to today is arm64, so nothing is
  currently broken by it — but it is a narrowing of (a) and it is the owner's
  to accept, refuse, or spend the emulation on.
