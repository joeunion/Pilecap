

def _neg_reads_the_tree(*, tenant, user):
    # Both nouns are named here and neither is written. Naming a model is not
    # a grant and not a re-parent; a rule that fired on this one would be a
    # rule nobody could read the tree under.
    held = Membership.objects.filter(user_id=user.pk, tenant=tenant).select_related(
        "organization"
    )
    tree = Organization.objects.for_tenant(tenant).order_by("path")
    return [membership.role for membership in held], [node.path for node in tree]
