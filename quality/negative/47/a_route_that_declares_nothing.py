

# --- planted (house rule 47's second negative) ---------------------------------
#
# The ordinary route: no `@refuses(...)` at all, so the shape derivation decides,
# and everything the derivation can produce is in the status table by
# construction. This is forty-odd of the eighty-seven bound operations and the
# rule must be silent on every one of them — a check that could not tell a
# derived set from a declared one would turn the whole document red.
@router.get(
    "/silent-probe/{widget_id}/", response=WidgetOut, url_name="widget_silent_probe-detail"
)
def silent_probe_detail_route(request: TenantRequest, widget_id: UUID) -> Any:
    """Read a silent-probe widget

    Read a silent-probe widget by id.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no widget with that id that you can reach.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    raise NotFound("the negative route is never called")
