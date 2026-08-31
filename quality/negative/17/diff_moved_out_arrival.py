

# The arrival half of the move: the same class, field for field, in another
# app's `schemas.py` in the same change. The comparison is the whole field map
# and not the name, so a class that arrives with a field missing or re-typed is
# still a break and is still reported — that is this negative's canary twin
# (quality/canary/17/diff_moved_out_arrival_retyped.py).
class WorkflowRunOut(Schema):
    """One run, as every door reports it. Promoted, not deleted."""

    id: UUID
    workflow_id: str
    run_id: str
    type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str
    input_digest: str
    started_by_id: UUID | None
    started_by_email: str
    created_at: datetime
