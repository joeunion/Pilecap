"""`manage.py integrations` — what this deployment actually talks to.

    uv run python manage.py integrations            # the report
    uv run python manage.py integrations --wall     # and refuse if anything is not real
    uv run python manage.py integrations --wall \
        --accept-fake <census-key>                  # …except that one, out loud, forever

**The question a fresh clone asks in its first hour and a production morning
asks too**: is this integration real here, is something standing in for it, or
is it simply absent — and if it is not real, what does somebody type? The
answer is one census (`apps.core.integrations`) read by four surfaces, and this
is the on-demand one; `scripts/setup.sh`'s epilogue, `deploy/release.sh`'s wall
and the standing prober read the same value and print the same words.

**It changes nothing.** Every declaration is a settings read or a read-only
probe, and the one live probe in the platform's own seam is the `HEAD` that
`/readyz` already makes on the bucket.

**`--wall` is the deploy's half, and it is a refusal rather than a warning.** A
release that reaches production with the console mail backend still set is a
product whose password resets are being printed to a log — the fake that
succeeded, which is the whole failure class this census exists for. With the
flag, anything that is not `configured` stops the release and the remedy is
printed beside it.

## `--accept-fake`, and why it is per key rather than a mode

A deployment can have a legitimate reason to stand on a named stand-in — a
template's own staging box ships `FakeSmsChannel` and has no gateway to point
at, and refusing to release it means the runbook cannot be performed on the box
it documents. The obvious fix was "a DECLARED fake passes": it was rejected,
because **every fake this census can see is declared by construction** —
`providers.DeclaresFakeness` is the only route by which fakeness reaches a row —
so that rule deletes the wall and keeps its name.

What passes instead is one key, named by the operator, and only while that key is
**FAKE right now**:

* `--wall --accept-fake <census-key>`, repeatable.
* A key that is `configured`, that is `not_configured`, or that no row carries at
  all is **refused, exit 1**. You cannot accept an absence, and a stale
  acceptance — one whose integration has since become real — must be deleted
  rather than left to quietly cover the next fake that arrives under that key.
* It never affects **exit 2**. An operator may acknowledge a fake they have
  looked at; nobody can acknowledge a seam that would not answer.
* Every accepted key is printed, with its detail and its remedy, on **every
  run, forever**. The acceptance is a standing announcement, not a silence.
* **The report itself never learns the word.** These rows go on saying `FAKE` in
  this command's own output, in `scripts/setup.sh`'s epilogue and in the standing
  prober, because an acceptance is the deploy's verdict and not the census's
  finding — the moment a row read "accepted", the thing that was accepted would
  stop being visible as a thing.

`deploy/release.sh` expands `DJB_ACCEPTED_FAKES` from `deploy/.env` into these
flags, so the acceptance is a named, vault-managed artifact somebody had to write
down rather than a flag somebody typed once on a box.

## Exit status

* **0** — the report was produced. With `--wall`, also: everything is real, or
  every fake that is not is one the operator named.
* **1** — `--wall` only: something is a fake or absent, or an acceptance names a
  key that is not a fake. Nothing was changed.
* **2** — **a seam could not be read.** An app's `register` raised, so the
  census does not know what that app talks to. "I could not look" is not "I
  looked and it is not there", and this command refuses to turn the first into
  the second — the instrument checklist's line, and `scripts/goalpost_scan.py`'s
  own convention. Exit 2 happens with or without `--wall`, and it outranks
  every other verdict.

## What it cannot see

The census's declared blind spots, repeated here because the person reading a
clean report is the person who most needs to know what clean covers: a fake that
misdeclares itself as real is invisible; probe depth varies by integration and
each row says which it had; per-tenant credentials (Twilio, FCM) are rows and
not settings, so a configured *slot* is not a tenant that can send; and
infrastructure readiness is `/readyz`'s and is deliberately not repeated here.
`apps/core/integrations.py`'s docstring is the long form.
"""

from __future__ import annotations

from typing import Any

from apps.core.integrations import Census, Integration, IntegrationStatus, census
from apps.core.management import BaseCommand

#: The status column, padded so the rows line up under a skim. The words are the
#: status values themselves rather than a second vocabulary — a report that
#: renamed `not_configured` to "missing" would be the third spelling of a thing
#: that already has one.
_LABELS = {
    IntegrationStatus.CONFIGURED: "configured",
    IntegrationStatus.FAKE: "FAKE",
    IntegrationStatus.NOT_CONFIGURED: "NOT CONFIGURED",
}
_WIDTH = max(len(label) for label in _LABELS.values())

#: What an acknowledged stand-in is called, in the one place it is spelled. The
#: release transcript, the runbook and `deploy/tests/test_release.sh` all read
#: this string, so it is a constant rather than four literals that can drift.
#: Deliberately louder than the status labels above: it is the line an operator
#: is meant to trip over on every single release, for as long as it is true.
ACCEPTED_LABEL = "ACCEPTED FAKE"

#: Where an operator edits the acceptance. Named in every refusal below, because
#: a refusal that says something is wrong and not where to fix it sends a person
#: to the source — the instrument checklist's line, held here.
ACCEPTANCE_SLOT = "DJB_ACCEPTED_FAKES in deploy/.env (deploy/release.sh expands it)"


class Command(BaseCommand):
    help = (
        "Report every external service this deployment talks to, and what is "
        "standing in for the ones that are not real. Changes nothing."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--wall",
            action="store_true",
            help=(
                "Exit 1 if any integration is not configured. For a deploy: no "
                "silent fakes in production."
            ),
        )
        parser.add_argument(
            "--accept-fake",
            action="append",
            default=[],
            dest="accept_fake",
            metavar="CENSUS-KEY",
            help=(
                "With --wall: let this one census key past the wall while it is "
                "FAKE, announcing it on every run. Repeatable. Refused (exit 1) "
                "for a key that is configured, absent, or not declared at all — "
                "you cannot accept an absence, and a stale acceptance is deleted "
                "rather than left standing."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = census()
        self._report(report)

        if not report.is_readable:
            self.stderr.write(
                self.style.ERROR(
                    f"{len(report.unreadable)} seam(s) could not be read, so this "
                    "report does not cover them. Nothing here is a judgment about "
                    "what those apps talk to."
                )
            )
            raise SystemExit(2)

        if not options.get("wall"):
            # The acceptance is the WALL's vocabulary and deliberately nothing
            # else's: with no wall in front of it there is nothing to let past,
            # and a report that annotated its own rows would be the census
            # describing this deployment as less fake than it is.
            return

        accepted = self._accepted(report, options.get("accept_fake") or [])

        unmet = tuple(row for row in report.unmet if row.key not in accepted)
        if unmet:
            self.stderr.write(
                self.style.WARNING(
                    f"REFUSED: {len(unmet)} integration(s) are not configured — "
                    + ", ".join(row.key for row in unmet)
                    + ". Each remedy is printed above. Nothing was changed."
                )
            )
            raise SystemExit(1)
        if accepted:
            # NOT "all integrations are configured", because they are not. The
            # wall passed; the deployment is still standing on the stand-ins
            # printed above, and the last line a release quotes is the one most
            # likely to be the only line anybody reads.
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(report.integrations) - len(accepted)} integration(s) are "
                    f"configured and {len(accepted)} accepted fake(s) were named by the "
                    f"operator. The wall passes; the fakes are still fakes."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"All {len(report.integrations)} integrations are configured.")
        )

    def _accepted(self, report: Census, keys: list[str]) -> dict[str, Integration]:
        """The operator's acknowledgements, enumerated against the LIVE census.

        Per key, and only a key that is FAKE right now. That is the whole of what
        keeps this honest, and each of the three refusals below closes a
        different way an acceptance rots:

        * **A key nobody declares** is a typo, and a typo that silently accepted
          nothing would leave the operator believing they had answered a refusal
          they had not.
        * **A configured key** is a STALE acceptance — the integration went real
          and the line stayed. It is the dangerous one: left standing, it is a
          slot the operator believes is guarded, and the next fake to arrive
          under that key walks straight through.
        * **A not-configured key** is an absence. Nothing is standing in for it,
          so there is nothing to stand on; what it needs is the remedy printed
          above it, not an acknowledgement.

        The accepted rows are ANNOUNCED HERE, before the wall's own verdict, so
        the line is in the transcript whether the release then proceeds or stops
        on something else.
        """
        rows = {row.key: row for row in report.integrations}
        # Ordered, de-duplicated: the slot is a hand-maintained string in a vault,
        # so a repeated key is a typo rather than a second opinion.
        wanted = list(dict.fromkeys(keys))

        refusals: list[str] = []
        accepted: dict[str, Integration] = {}
        for key in wanted:
            row = rows.get(key)
            if row is None:
                refusals.append(
                    f"{key!r} — no integration declares that key. Run this command "
                    f"with no flags and copy the key exactly, or delete it from "
                    f"{ACCEPTANCE_SLOT}."
                )
                continue
            if row.status is IntegrationStatus.CONFIGURED:
                refusals.append(
                    f"{key!r} — {_LABELS[row.status]}. There is no fake to accept: "
                    f"this acceptance is stale and must be DELETED from "
                    f"{ACCEPTANCE_SLOT}, or it will cover the next stand-in that "
                    f"arrives under this key."
                )
                continue
            if row.status is not IntegrationStatus.FAKE:
                refusals.append(
                    f"{key!r} — {_LABELS[row.status]}. Nothing is standing in for "
                    f"it, so there is nothing to accept; an absence is fixed rather "
                    f"than acknowledged. The remedy is printed above. Delete it from "
                    f"{ACCEPTANCE_SLOT} once it is configured."
                )
                continue
            accepted[key] = row

        if refusals:
            self.stderr.write(
                self.style.WARNING(f"REFUSED: {len(refusals)} acceptance(s) do not name a fake:")
            )
            for line in refusals:
                self.stderr.write(self.style.WARNING(f"  {line}"))
            self.stderr.write(self.style.WARNING("Nothing was changed."))
            raise SystemExit(1)

        for key, row in accepted.items():
            self.stdout.write(self.style.WARNING(f"{ACCEPTED_LABEL}  {key} — {row.detail}"))
            self.stdout.write(f"{' ' * len(ACCEPTED_LABEL)}  remedy: {row.remedy}")
            self.stdout.write(
                f"{' ' * len(ACCEPTED_LABEL)}  accepted by the operator in "
                f"{ACCEPTANCE_SLOT}. This deployment is standing on it."
            )
        return accepted

    def _report(self, report: Census) -> None:
        """The rows, then the seams that would not answer. Both, always.

        The unreadable seams are printed even when there are integrations to
        show, because a partial census that looks complete is the shape this
        command exists to refuse.
        """
        if not report.integrations:
            self.stdout.write("no integration is declared by any app.")
        for row in report.integrations:
            label = _LABELS[row.status].ljust(_WIDTH)
            line = f"{label}  {row.key} — {row.detail}"
            if row.status is IntegrationStatus.CONFIGURED:
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(self.style.WARNING(line))
                self.stdout.write(f"{' ' * _WIDTH}  remedy: {row.remedy}")
            self.stdout.write(f"{' ' * _WIDTH}  probe: {row.probe} · declared by {row.declared_by}")

        for seam in report.unreadable:
            self.stdout.write(
                self.style.ERROR(f"{'UNREADABLE'.ljust(_WIDTH)}  {seam.module} — {seam.reason}")
            )
