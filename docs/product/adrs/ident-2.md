# ADR ident-2

- **ADR ident-2, amended (2026-08-30) — the console's own surfaces
  are observed, not reconciled** · context: `zitadel_audit` compared what
  our *rows* declare, so two classes of configuration no product manages
  through services — the org's **login policy** and the instance's **SMTP
  sender** — sat entirely inside rule 27's declared blind spot. Both were
  changed on the shared development instance by a sibling product and the
  audit still printed "Zitadel agrees with every row." · decision: **read
  them, print them, judge neither.** `zitadel.login_policy()` and
  `zitadel.smtp_configuration()` are GETs in the reads section;
  `zitadel_audit` prints an `observed` section that adds nothing to the
  drift count and cannot move the exit status, and the residual — what a
  clean verdict does *not* cover — now prints **beside the verdict** on
  every run under both verdicts, rather than living in a module docstring
  only a maintainer reads · rejected: **full intent-row machinery** (rule
  27's whole materialisation path — rows, services, an activity — built to
  guard drift only one actor can cause, and that actor is a person in a
  console we would still not be fencing: shop-the-price), and **a report
  line only** (names the blind spot without narrowing it, leaving the two
  changed surfaces invisible to the person reading the report) · trigger to revisit:
  **the first product that manages login policy or SMTP through services**
  — at that point an intent row exists, the comparison becomes possible,
  and these two move from observed to reconciled.

- **ADR ident-2, amended (2026-09-17) — the reconciler is BUILT; its
  trigger fired, and the trigger that is still open is SCHEDULING it** ·
  the original declined an auto-repairing reconciler and named its
  trigger, *first observed drift or first production deploy*: both
  happened (a one-field console edit to this deployment's own browser
  application lands a person on raw JSON at the identity platform and
  neither the audit nor the seed noticed; a one-way sync locked an owner
  out of the sibling product for a morning) · decision:
  **`manage.py zitadel_reconcile`** — a second command, not a flag on the
  audit, reading through the audit's own section functions (one read, not
  two), asking only services (the management call stays in the activity,
  house rules 10 and 27), `--dry-run`, exit 0/1/2, and an **ownership
  table in its docstring** naming every identity fact's authority, copy,
  settlement, staleness and repair kind (principle 9); the SMTP sender's
  OWNER is named and counted beside the audit's verdict, still judged by
  nothing · rejected: a `--repair` flag on `zitadel_audit` (a writing path
  inside the one command a deploy step trusts to change nothing) and a
  **Temporal Schedule** around the reconciler · trigger to revisit: still open —
  **a drift found in production that nobody in this deployment caused** —
  the command prints that sentence on every run.
