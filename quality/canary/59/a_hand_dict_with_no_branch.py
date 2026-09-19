

# CANARY (rule 59): R4's F4 generalised — an org-scoped noun announced with a
# hand-built body that omits the narrowing key. `_subject_organization` reads
# only the top level, an absent key is NULL, and `group_for` reads NULL as
# TENANT-WIDE: every branch's socket hears this branch's ledger row while the
# REST list under the same hat never shows it.
@service
def _canary_announce_a_crossing(*, tenant: Tenant, actor: Actor, entry: object) -> None:
    emit(
        name=THRESHOLD_CROSSED,
        tenant=tenant,
        payload={"meter": "files.bytes.stored", "entry_id": str(entry)},
        actor=actor,
    )
