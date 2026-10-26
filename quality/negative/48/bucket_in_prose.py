

def _negative_storage_prose() -> str:
    """Names AWS_STORAGE_BUCKET_NAME and boto3 in prose, reaches neither.

    `apps/files/storage.py`, `apps/files/apps.py`, `config/settings/base.py`,
    `config/settings/guards.py`, `.env.example` and `quality/checks/rule_48.py` all do
    exactly this — they have to, to explain the fence — so a check that fired on
    the word rather than on the AST node would fire on its own reasons.
    """
    setting = "the object store's bucket"
    return f"{setting} is called AWS_STORAGE_BUCKET_NAME and boto3 finds the rest itself"
