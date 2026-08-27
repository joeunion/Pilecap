

# A fixed platform id, written once as a module constant and used by name. The
# STRING is what rule 18 judges — `platform:<app>:<noun>:<key>` is the house
# shape for a run that belongs to the deployment rather than to a tenant (ADR
# workflows-3) — and binding it to a name changes nothing about it. Refusing
# the constant would push authors back to inlining the same literal at every
# callsite, which is worse for exactly the reason a constant exists.
_NEG_PLATFORM_RECONCILE_ID = "platform:example:widget:reconcile"


def _neg_platform_constant_start(*, client):
    from apps.workflows.services import start_workflow

    return start_workflow(
        workflow="WidgetOnboardingWorkflow",
        arg=None,
        tenant=None,
        id=_NEG_PLATFORM_RECONCILE_ID,
        client=client,
    )
