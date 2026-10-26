"""`run_failed`: the refusal a run that stopped before it finished records."""

from __future__ import annotations

from apps.core.exceptions import REFUSALS, Conflict, Remedy, remedies_for_noun, wire_refusal

REASON = "The upstream answered 503 three times; the retries are spent."


def test_run_failed_is_registered_with_a_run_s_remedies() -> None:
    """A run's failure has its own code, and none of `conflict`'s write-race advice."""
    from apps.core.exceptions import RunFailed

    refusal = REFUSALS["run_failed"]
    assert refusal.boundary == "service"
    assert refusal.status == 409
    assert refusal.fact == "The run stopped before it finished."
    assert refusal.remedies == (
        Remedy("Read the run's reason", "field:detail"),
        Remedy("Start a new run once the cause is fixed", "route:<noun>-create"),
    )
    assert RunFailed.code == "run_failed"
    assert not issubclass(RunFailed, Conflict)


def test_the_stored_body_carries_the_reason_and_the_run_s_remedies() -> None:
    """The body a run records in `failure` is the one composer's, the reason in `detail`."""
    from apps.core.exceptions import RunFailed

    body = wire_refusal(RunFailed(REASON))
    assert body == {
        "detail": REASON,
        "code": "run_failed",
        "remedies": [
            {"label": "Read the run's reason", "destination": "field:detail"},
            {
                "label": "Start a new run once the cause is fixed",
                "destination": "route:<noun>-create",
            },
        ],
    }
    conflict = {r["destination"] for r in wire_refusal(Conflict(REASON))["remedies"]}
    assert conflict.isdisjoint(r["destination"] for r in body["remedies"])


def test_a_raise_site_that_knows_its_noun_names_its_create_door() -> None:
    """The `<noun>` slot fills from the run's kind, as the family refusals' do."""
    from apps.core.exceptions import RunFailed

    remedies = remedies_for_noun("run_failed", "djb_import")
    body = wire_refusal(RunFailed(REASON, remedies=remedies))
    assert body["remedies"][1]["destination"] == "route:djb_import-create"
