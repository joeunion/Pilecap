"""Negative: the scoped model's noun has a write policy."""


def _allow(actor, obj=None):
    return True


POLICIES = {"goodscoped.update": _allow}
