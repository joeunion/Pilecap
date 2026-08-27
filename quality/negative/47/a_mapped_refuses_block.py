

# --- planted (house rule 47's negative) ----------------------------------------
#
# A route that narrows its refusals with `@refuses(...)` and names only codes the
# status table can key. Every one of them reaches the document, so there is
# nothing to say — and a rule that fired here would be refusing `@refuses`
# itself, which is the decorator the whole contract discipline is built on.
@router.post(
    "/negative-probe/", response={201: WidgetOut}, url_name="widget_negative_probe-create"
)
@refuses("invalid", "forbidden", "not_found", "conflict", "rate_limited")
def negative_probe_write_route(request: TenantRequest, payload: WidgetIn) -> Any:
    """Create a negative-probe widget

    Create a negative-probe widget.

    Refusals you can get here:

    * `400 invalid` — the body was malformed.
    * `403 forbidden` — you may not create widgets here.
    * `404 not_found` — a named row this actor could not reach.
    * `409 conflict` — a rule about the data did not hold.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    raise NotFound("the negative route is never called")
