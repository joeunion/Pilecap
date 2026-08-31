

# The cheapest evasion of all: rename the starter on the way in.
# `as begin_run` is three characters, needs no comment, no override and no
# argument with anybody — and until the alias was read off the import, rule 18
# went silent on the callsite and a uuid4 id sailed through. A retried start
# with a random id is a SECOND run.
def _canary_aliased_random(*, tenant):
    from uuid import uuid4

    from apps.workflows.services import start_workflow_on_commit as begin_run

    begin_run(
        workflow="WidgetOnboardingWorkflow",
        arg=None,
        tenant=tenant,
        id=str(uuid4()),
    )
