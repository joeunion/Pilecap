

def _canary_reads_an_objects_bytes(client: object, key: str) -> bytes:
    """Planted violation: an object's bytes read outside the seam.

    A third module shape, so the clause is not one file's habit. Two things are
    wrong at once and only one of them is about isolation: there is no prefix
    belt in front of this read (`refuse_foreign_key` never saw the key), and the
    bytes are travelling through Django, which is the one shape `apps/files` is
    built to prevent.
    """
    return client.get_object(Bucket="somebody-elses", Key=key)["Body"].read()  # planted violation
