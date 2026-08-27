"""Negative: the boundary. A BaseModel-only row — no tenant foreign key — with a
recency index of its own and the comment naming the read that wants it.

Out of the population entirely: rule 37 censuses SCOPED models, and an unscoped
table's indexes are per-model decision territory (ADR core-11's BaseModel-only
table, each entry carrying its reader or its `none`). The proof that this rule
does not reach past scoped rows.
"""

from apps.core.models import BaseModel as _Canary37Base


class Canary37Unscoped(_Canary37Base):
    status = models.CharField(max_length=16)
    # The reader: the deployment-wide drain that walks oldest-first.
    settled_at = models.DateTimeField(db_index=True)

    class Meta(_Canary37Base.Meta):
        indexes: ClassVar[list] = [
            models.Index(fields=["status", "-created_at"], name="canary37_unscoped_status"),
            models.Index(fields=["-created_at"], name="canary37_unscoped_created"),
        ]
