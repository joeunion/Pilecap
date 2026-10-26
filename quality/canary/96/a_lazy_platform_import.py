# Planted: the platform reached from inside a function, out of the module's head.
def reach() -> object:
    from apps.core.authz import require

    return require
