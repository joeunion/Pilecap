

# CANARY (rule 59): R4's F4 generalised — an org-scoped noun announced with a
# hand-built body that omits the narrowing key. `_subject_organization` reads
# only the top level, an absent key is NULL, and `group_for` reads NULL as
# TENANT-WIDE: every branch's socket hears this branch's row while the REST list
# under the same hat never shows it.
@service
def _canary_announce_a_bare_widget(*, tenant: Tenant, actor: Actor, widget: object) -> None:
    emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload={"id": str(widget), "name": "A widget"},
        actor=actor,
    )
