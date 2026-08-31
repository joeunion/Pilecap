# Planted: a top-level key in the OpenAPI document that rule 41's
# `openapi_top_level_keys` census does not declare.
#
# This is the shape nothing could see before `djb.E042`. Forty-seven rules
# covered the document's operations and its refusal codes; the document ITSELF —
# which specification version it speaks, who it is, where it can be reached —
# was governed by nothing, so a key could appear, change meaning or vanish with
# no check anywhere noticing. `openapi_extra` is ninja's own supported road to
# adding one, which is exactly why it needs a census rather than a convention.
api.openapi_extra["x-canary-undeclared"] = {"canary-top-level": True}
