

# NEGATIVE (rule 40): the RIGHT shape, and the one the middleware itself is
# written in — the header name is the constant, and a `.get()` with a value
# default is perfectly fine once the name cannot drift. The rule fires on the
# SPELLING, never on the default, or it would be a tax on reading a header.
def _negative_ambient_ids(request):
    return {
        REQUEST_ID_HEADER: request.headers.get(REQUEST_ID_HEADER, ""),
        CORRELATION_ID_HEADER: request.headers.get(CORRELATION_ID_HEADER, ""),
        TENANT_HEADER: request.headers.get(TENANT_HEADER),
        ORG_HEADER: request.headers[ORG_HEADER],
    }
