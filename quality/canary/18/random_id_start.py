

def _canary_random_start(*, tenant, widget):
    from uuid import uuid4

    start_workflow_on_commit(
        workflow="WidgetOnboardingWorkflow",
        arg=None,
        tenant=tenant,
        id=str(uuid4()),
    )
