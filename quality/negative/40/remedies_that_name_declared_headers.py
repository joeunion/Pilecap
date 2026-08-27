

# NEGATIVE (rule 40, second population): the remedies the tree already ships —
# a declared header's value, and two destinations in other declared kinds. All
# three must stay silent, or every refusal in `core.exceptions` becomes a
# violation and the rule is an argument against composing remedies at all.
_negative_remedies = (
    Remedy("Resend the identical body to replay the first answer", "header:Idempotency-Key"),
    Remedy("Check which organization you are wearing", "header:X-Org"),
    Remedy("Read the shape this endpoint accepts", "docs:openapi"),
    Remedy("Check the role your membership gives you here", "self:membership"),
)
