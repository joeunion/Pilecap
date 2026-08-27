

def _neg_governing_marked(*, tenant, org):
    # The model declared InheritedDownward, so the nearest-ancestor read is the
    # legal one and .visible_to is not the chain it wants.
    return CanaryWidgetPolicy.objects.for_tenant(tenant).governing(org).first()
