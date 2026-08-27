"""Planted: a policies.py whose actions name a different noun."""


def _allow(actor, obj=None):
    return True


POLICIES = {"otherthing.update": _allow}
