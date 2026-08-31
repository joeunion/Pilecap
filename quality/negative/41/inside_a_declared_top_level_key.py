# Negative: the document grows, and it grows INSIDE a key the census already
# declares. `info` is declared; adding a field to it adds no top-level key, so
# `djb.E042` must stay silent.
#
# Firing here would make the census a tax on saying anything new about the API
# at all, which is the opposite of what it is for: it watches the SET of
# contract elements, and rule 41's other clauses watch what is inside them.
api.openapi_extra["info"] = {"x-canary-note": "the negative corpus was here"}
