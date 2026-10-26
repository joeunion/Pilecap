def canary_why_not_paragraph() -> None:
    """Return nothing.

    why-not a cached result: the caller's transaction must see its own write,
    which is a paragraph now and no longer one line.
    """
    return None
