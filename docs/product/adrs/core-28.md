# ADR core-28

**ADR core-28 · a template migration is grafted onto the product's leaf by a
command, never by hand.** *SIGNED by the owner 2026-09-22 (proposed 2026-09-21 (P21, team D, decision D2 —
the owner chose option A; the signature at CLOSE).)* *Context*: a product that
added migrations to `core`/`accounts` met each release's numbered ancestors
twice — a leaf fork and, after one fold, ancestors it had renamed — and
reparented by hand under `django-linear-migrations`' refusal.
`rebase_migration` moves exactly ONE migration and cannot see a chain or a
renamed ancestor at all. *Decision*: `manage.py fold_migrations <app>` grafts
the arriving chain from the `max_migration.txt` conflict onto the product's
leaf, resolving a renamed ancestor by stem suffix, refusing an applied
migration or an ambiguous stem; template files stay Django-native; stems are
unique per app by test; a new product is advised to extend template apps from
its own. It subclasses `rebase_migration`'s `Command` rather than replacing it
(principle 2), and the library internals that makes it hold are declared in
house rule 44's `linear_migrations_internals_we_hold`. The direction is the
INVERSE of the library's: `rebase_migration` moves yours onto theirs, the fold
moves theirs onto yours, so the markers are read positionally and the library's
merge-time swap is undone. *Rejected*: named-ancestor spelling in template
migration files (non-native, regenerated away by `makemigrations`, and no fix
for the leaf fork); forbidding product migrations in template apps
(unadoptable by the consumer that exists — it already holds `core` 0018–0023).
*The cross-app gap, declared rather than closed*: a dependency from ANOTHER
app onto a migration the fold renumbered — `("accounts", "0008_identity_branding")`
written in `apps/comms/migrations/…` while the fold made it
`0010_identity_branding` — is left exactly as written. Stem resolution runs
only within the app being folded, because a stem is unique per app and nothing
here is entitled to edit another app's files; Django's own loader then raises
`NodeNotFoundError` naming both ends at the next `migrate` or `manage.py
check`. **Loud, and never wrong** — which is why it is a declared gap and not a
silent one: the operator folds the other app too, or repoints that one
dependency by hand. Closing it (a tree-wide pass that rewrites cross-app
tuples) is queued in `queue.md`, not decided here.
*Reversible*: `git checkout -- <app>/migrations && git clean -f
<app>/migrations` undoes a run (principle 6) — **both halves**, because a
rename leaves the new filename as an UNTRACKED file, so a checkout alone
restores the old chain and leaves the grafted copies beside it — and
`--dry-run` prints the plan before anything moves.
*Refused, not attempted*: a stopped `git rebase`. Under one, HEAD is the
upstream and `MERGE_HEAD` does not exist, so the library's merge-time swap does
not happen and this command's un-swap does not either; the two inversions
cancel and the fold would renumber the PRODUCT's chain onto the template's
leaf, silently. `REBASE_HEAD` is read before the markers are, and the command
exits 2 saying so. trigger to revisit: a squashed
template migration (house rule 6's gap), or a product that wants the fold to
run across every app at once rather than one app at a time.
