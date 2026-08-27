

def _canary_meili_key() -> str:
    """Planted violation: the master key named outside the fenced module.

    A second reader is a second place a master key reaches a log line, an
    exception message or a subprocess environment — and a fourth way to dial an
    index whose whole isolation story is a filter injected somewhere else.
    """
    import os

    return os.environ["MEILI_MASTER_KEY"]  # planted violation
