

# CANARY (rule 40): the socket door's own shape of the same mistake. A websocket
# handshake has no `request`, so the hat is read by walking `scope["headers"]`
# and comparing byte keys — and a byte literal is a second spelling of `X-Org`
# that no rename will ever follow. The consumer that reads it joins the wrong
# groups and hears somebody else's branch.
def _canary_requested_org(scope):  # planted violation
    for key, value in scope.get("headers", []):
        if key.lower() == b"x-org":
            return value.decode("latin-1")
    return None
