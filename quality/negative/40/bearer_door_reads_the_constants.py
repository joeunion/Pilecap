

# NEGATIVE (rule 40): the machine door's two reads, exactly as `ApiTokenAuth`
# writes them. The bearer path is the second of the four routes to the same
# answer, and it must cost nothing to write correctly — a rule that fired here
# would push the next door back to a literal to keep the gate quiet.
def _negative_token_scoping(request):
    if not request.headers.get(AUTHORIZATION_HEADER):
        return None, None
    return (
        request.headers.get(TENANT_HEADER),
        request.headers.get(ORG_HEADER),
    )
