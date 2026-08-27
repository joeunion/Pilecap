

async def _negative_connect_read(tenant, org):
    # The consumer's one legal database touch: the connect-time subtree read,
    # through run_db, and never a write.
    return await run_db(list_subtree_org_ids, tenant=tenant, org=org)
