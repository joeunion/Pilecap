"""Test doubles for the runner seam — deliberately wrong replies, kept forever.

These are the seam's canaries in the only shape its subject can take: the thing
that must be caught is a runner that will not answer, or answers something the
engine must refuse to believe, and no planted FILE makes a subprocess behave
that way. `quality/gate.py`'s seam leg drives every reply here and demands the
matching refusal.
"""
