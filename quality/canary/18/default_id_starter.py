

# THE PIN on rule 18's own excluded zone. `workflow_ids` skips
# apps/workflows/** because that module DEFINES the starters — and an exclusion
# is a promise about what lives inside it. This is the promise being broken the
# exact way it was broken before W1: `id` grows a default, every caller who
# forgets it silently gets a fresh one, and every one of those callers has no
# idempotency at all — while the rule stays green, because it is not looking.
#
# Planted into apps/workflows/services.py itself, which is the only place this
# defect can live and the only place the live scan cannot see.
def start_workflow_on_commit(  # noqa: F811
    *,
    workflow,
    arg,
    tenant,
    id=None,
    task_queue=None,
):
    """A starter that will make one up for you if you forget. It must fire."""
    return None
