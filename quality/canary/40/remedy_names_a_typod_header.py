

# CANARY (rule 40, second population): a refusal's remedy pointing the caller at
# `X-Tenent`. Every door renders it identically and every one of them is wrong:
# the caller sets the header the refusal named, sends the request again, and is
# refused again — with the same advice. A remedy is a promise that doing the
# named thing changes the answer, and this one cannot keep it because nothing
# in the tree reads a header by that name.
#
# Planted beside the registry above rather than inside a `register_refusal(...)`
# call: the plant lands in a module Django imports, so it composes the remedy
# and registers nothing. The rule reads `Remedy(...)` call sites, which is the
# population wherever they sit.
_canary_typod_remedy = Remedy("Check which tenant you are acting in", "header:X-Tenent")
