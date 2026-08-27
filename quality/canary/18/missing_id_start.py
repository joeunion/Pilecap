

def _canary_missing_id(*, tenant):
    start_workflow_on_commit(workflow="WidgetOnboardingWorkflow", arg=None, tenant=tenant)
