

# NEGATIVE (rule 40): a header read off somebody else's RESPONSE. `Retry-After`
# and `Content-Type` are standard HTTP vocabulary defined by RFC 9110, not this
# product's contract — there is no constant to name because there is no
# decision to make. The rule's population is INBOUND reads, and this is the
# declared restraint that proves it: the receiver's name is what tells the two
# apart, so `response.headers.get(...)` stays silent forever.
def _negative_retry_after(response):
    seconds = response.headers.get("Retry-After", "")
    kind = response.headers.get("Content-Type", "application/json")
    return seconds, kind
