def negative_why_not() -> None:
    """Return nothing.

    why-not a cached result: the caller's transaction must see its own write.
    """
    # Read the row inside the transaction.
    # why-not: a replica read would miss the write above.
    return None
