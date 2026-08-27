

class CanaryUnlistedVault(OrgScopedModel):
    """The allow-list's other direction: the same field, off the list.

    Field for field identical to `quality/negative/15/
    allow_listed_vault_secret.py` — same names, same types, same lengths — and
    differing in exactly one thing: the class name, which is what the rule 15
    exemption is keyed on. The pair therefore isolates the allow-list itself
    and nothing else; no other variable is left to explain the difference in
    verdict.

    What it catches: an exemption that stopped being an entry about one judged
    field and quietly became a hole under the whole `apps/example/models.py`
    path — a `path`-only entry, a widened match, a helper that forgot to
    compare the function. The list would still look like a list, the negative
    would still be silent, and every secret-shaped field in that file would be
    unwatched. That is precisely the failure an allow-list nobody exercises
    hides, and this canary is the thing that will not let it be silent.
    """

    label = models.CharField(max_length=64)
    signing_key = models.CharField(max_length=255)
