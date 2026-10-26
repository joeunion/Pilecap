# Authoring the drive: traps an honest drive still pays

Moved from `SKILL.md` § 2 (rule 98's budget); the section is unchanged.

These red a drive that is doing everything right, which is why they are written
down rather than re-discovered: each one cost a builder part of a rung.

**A drive cannot run a nested `./scripts/check.sh` inside a gate.** The
per-checkout gate lock refuses it (`gate_lock_refuse_if_held`), so a drive that
shells out to the gate to prove a leg goes red for the lock and not for the
property. A drive invokes the **leg body** — the sourced function the leg calls
— never the gate around it. (Paid by B2's builder, 2026-09-12.)

**`mktemp … 2>/dev/null` trips the portability census.** That census
(`mktemp_selfline` in `scripts/check.sh`) reads the LAST bare word of the line
as the template, so a trailing redirect becomes the template it judges and the
line reds with no X's in sight. Write the redirect **before** the template, or
not at all. (Paid by the same builder, the same night.)

**A criterion of the form "X refuses in production" needs a production
environment, and it is a module-local dict — never a new settings key.** The two
worked forms in this tree are `PRODUCTION_ENVIRONMENT` in
`apps/core/tests/test_settings.py` and in
`apps/workflows/tests/test_machinery_lifetime.py`: the minimum set of
environment variables `config.settings.production` refuses to start without,
with throwaway real-shaped values and a `# pragma: allowlist secret` on each
one, loaded around an import of the production settings module. Copy the nearer
of the two; do not invent a third spelling, and do not add a settings key so a
test can find one.
