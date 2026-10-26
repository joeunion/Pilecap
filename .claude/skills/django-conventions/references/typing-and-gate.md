# What mypy measures

The long form of `django-conventions` §13.

- **`mypy` reads `INSTALLED_APPS`, so a disabled app changes what type-checks.**
  django-stubs' plugin builds its model knowledge from the resolved app
  registry, and the `<fk>_id` shadow attributes it synthesises for a foreign key
  exist only for models in that registry. Disable an app and every reference to
  one of its `_id` attributes — from inside the app itself included — becomes
  an `[attr-defined]` error. Measured on this tree: `mypy --strict` clean is
  **exit 0, "Success: no issues found in 495 source files"**; the same command
  under `DJB_DISABLED_APPS=example` is **exit 1, 5 `[attr-defined]` errors in 5
  files** (`apps/example/models.py:374` on `WidgetEntry.widget_id`, and
  `Widget.owner_id` in `test_services.py:71`, `test_admin.py:85`,
  `test_mcp.py:268`, `test_api.py:105`). Nothing is wrong with that code; the
  app it belongs to is simply not installed in the world mypy was pointed at.
  So: **a rung that touches the optional-app machinery states which world it
  measured in**, because "mypy is green" is a claim about a configuration and
  not about the tree. `apps/example` is the one app a deployment may leave out
  and it says so itself (`apps/example/apps.py:19`, `optional = True`);
  everything else is non-optional by omission.

- Run `--loop` per rung. **Do not run the full gate by hand** — pre-push
  consults the verdict ledger and runs it once, on the tree you push.
- **Never pipe it** — you replace its exit status with the pipe's. **Exit 2
  means the enforcement is broken, not your code**: stop and report; do not
  "fix" a rule to make it pass. Pre-commit runs `--fast`; `--no-verify` is
  never the answer.
- Your worktree has its own database and task queue (`scripts/db.sh`); nothing
  you run touches anyone else's tree. Stage explicit paths.
