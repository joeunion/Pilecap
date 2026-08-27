

def _negative_readiness_probe_reaches_the_organ() -> None:
    """The allow-listed importer, proved in the module the allow-list names.

    `/readyz` reports on object storage as an organ, and `core` cannot import
    `files` — that is an upward import house rule 7 refuses. So the probe builds
    its own client, names the bucket and the credentials to do it, and heads the
    bucket. It mints no key, signs no URL and reads no object, so nothing about
    the key grammar this rule protects passes through it.

    An allow-list that fires is decoration.
    """
    import boto3
    from django.conf import settings

    client = boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )
    client.head_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
