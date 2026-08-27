

class NegSweptJob(OrgScopedModel):
    """The canary's twin, one file apart: the same writes, plus a real reader.

    `cleared_by_update.py` and this model are written from another module in
    exactly the same two ways — a constructor keyword and a queryset
    `.update()`. The ONLY difference is the selector planted beside it, which
    asks the database a question about the clock. That difference is the whole
    rule, and it is what the callee-restricted keyword match now measures: the
    write half cannot answer, the read half can.
    """

    status = models.CharField(max_length=16, default="pending")
    reaper_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
