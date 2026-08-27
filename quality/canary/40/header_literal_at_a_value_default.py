

# CANARY (rule 40): the shape, verbatim — a header read whose default is a
# VALUE rather than None, spelled as a literal. This is the one that cost a
# cycle: `request.headers.get("X-Tenant", "")` reads nothing when the header is
# spelled `X-Tenent` or when somebody renames the constant, and `""` is a
# perfectly good answer to `.strip().lower()`, so the request is served as
# though the caller had named no tenant at all. Nothing raises. Nothing logs.
def _canary_tenant_slug(request):  # planted violation
    return request.headers.get("X-Tenant", "").strip().lower()
