
from apps.core.models import BaseModel as _CanaryBase


# The rule's whole subject: a concrete model arrives and nothing anywhere says
# how its rows die. A retention document would not have mentioned it — the table
# added on Thursday is never in the document — which is why the declaration
# lives on the model, and why silence here is the finding.
#
# It also proves the RATCHET refuses to grow: `example` is recorded at its
# measured backlog, and one over that number turns every finding in the class
# into a violation naming the growth. An app already in debt does not get to add
# an undeclared table for free.
class CanaryUndeclaredLedger(_CanaryBase):
    """A table with a lifetime nobody wrote down."""

    note = models.TextField(blank=True)
