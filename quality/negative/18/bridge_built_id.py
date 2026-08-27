

def _neg_bridge_start(*, tenant):
    from apps.core import bridge

    build_id = bridge.get(bridge.WORKFLOW_ID)
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    start(
        workflow="WidgetOnboardingWorkflow",
        arg=None,
        tenant=tenant,
        id=build_id(tenant=tenant, app="example", noun="widget", key="neg"),
    )
