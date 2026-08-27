

# The same alias, used honestly. Reading the alias closes the escape without
# outlawing the import form: what rule 18 judges is the ID, and an id built by
# workflow_id() is the right answer whatever the caller called the starter.
def _neg_aliased_built_id(*, tenant):
    from apps.core import bridge
    from apps.workflows.services import start_workflow_on_commit as begin_run

    build_id = bridge.get(bridge.WORKFLOW_ID)
    begin_run(
        workflow="WidgetOnboardingWorkflow",
        arg=None,
        tenant=tenant,
        id=build_id(tenant=tenant, app="example", noun="widget", key="neg-alias"),
    )
