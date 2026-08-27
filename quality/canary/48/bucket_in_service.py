

def _canary_bucket_named_outside_the_seam() -> str:
    """Planted violation: the bucket named somewhere that is not the seam.

    The half a review is least likely to catch, because it looks like
    configuration rather than like a door — and the half F1's census pin is blind
    to, because nothing here imports the SDK.

    Read through `os.environ` on purpose: the recogniser matches the CONSTANT and
    not the module path, so this proves the string form fires and not only
    `settings.AWS_STORAGE_BUCKET_NAME`.
    """
    import os

    return os.environ["AWS_STORAGE_BUCKET_NAME"]  # planted violation
