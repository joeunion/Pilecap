

# A MOVE THAT IS ALSO A BREAK. The class arrives in another module — so a
# name-only move test would go silent here and a client reading `started_at` as
# a timestamp would find an integer — but one field is re-typed. The move
# branch compares the whole field map for exactly this reason, and the finding
# names where the class went as well as what changed.
class WorkflowRunOut(Schema):
    """One run, promoted AND re-typed: two facts, and only one of them is free."""

    id: UUID
    workflow_id: str
    run_id: str
    type: str
    status: str
    started_at: int
    finished_at: datetime | None
    error: str
    input_digest: str
    started_by_id: UUID | None
    started_by_email: str
    created_at: datetime
