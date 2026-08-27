

def _negative_reaches_the_store_the_legal_way(tenant: object, key: str) -> str:
    """The seam's own public API, called the way every caller is supposed to.

    This is the NAME-COLLISION case, on purpose. `delete_object` is both a boto3
    client method and `apps/files/storage.py`'s own public function — and
    `apps/exports/services.py` really calls it, in the retention sweep. A
    recogniser holding that name would fire on the legal door, which is why it is
    not in `OBJECT_READ_METHODS`; this negative is what keeps that decision from
    quietly reverting.

    `presign_get` and `presign_put` are here for the same reason on the signing
    side: the seam publishes its own verbs, and they are not the SDK's.
    """
    from apps.files import storage as files_storage

    files_storage.delete_object(tenant=tenant, key=key)
    return files_storage.presign_get(tenant=tenant, key=key)
