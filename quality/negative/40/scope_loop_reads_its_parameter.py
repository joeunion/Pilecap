

# NEGATIVE (rule 40): the seam itself. All three ASGI doors read a header by
# walking `scope["headers"]` through a helper whose NAME is a parameter, and the
# callers pass the constant — so the loop compares against a parameter and there
# is no spelling here to get wrong. A rule that fired on the loop rather than on
# the caller's argument would refuse the one shape it exists to encourage.
def _negative_scope_header(scope, name):
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return str(value.decode("latin-1"))
    return None


def _negative_requested_org(scope):
    return _negative_scope_header(scope, ORG_HEADER)
