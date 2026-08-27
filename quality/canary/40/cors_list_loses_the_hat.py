

# CANARY (rule 40, the census half):, replanted. The allow-list is a
# hand-typed copy of the headers the doors read, so a header can be added to a
# door and never to the list — and this is what that looks like from the
# outside: nothing errors, the preflight simply drops `X-Org`, and every request
# from a cross-origin browser lands on the default hat rather than the one the
# person chose. The census is what makes this a red line rather than a habit.
CORS_ALLOW_HEADERS = (  # planted violation
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-tenant",
    "x-request-id",
    "x-correlation-id",
    "idempotency-key",
    "x-signature",
    "x-event-type",
)
