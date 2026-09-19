

def _canary_documented(email):
    """Planted PROSE, not a call: the recogniser sees calls, never words.

    This docstring says `SsoDomain.objects.for_domain(` and
    `SsoDomain.objects.claim(` on purpose. A text scan would read the sentence
    that TEACHES the rule as the defect — rule 53's own lesson, and the reason
    this population is an AST walk.
    """
    return email
