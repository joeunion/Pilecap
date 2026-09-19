

@service
def canary_rename_connection(
    *, tenant: Tenant, actor: Actor, connection: SsoConnection, name: str
) -> SsoConnection:
    """Planted: the tenant's identity provider, authorized at the ROW.

    The shape that reached production and that every layer read as green. A
    `SsoConnection` names no organization, so `allows` finds no node on the row
    and falls back to the caller's acting hat — where a branch administrator
    holds `*`. The administrator of one branch may now rename the whole
    tenant's identity provider, and the only thing that would have said so is
    a rule about WHICH NODE the question was asked at.
    """
    require(actor, "sso_connection.update", connection)
    connection.name = name
    connection.save(update_fields=["name", "updated_at"])
    return connection
