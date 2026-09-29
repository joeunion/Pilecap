

# The documented query parameter the route really declares: `?show=` on a list
# that takes `show`. Firing here would make documenting a parameter a finding.


@router.get("/baubles/", url_name="bauble-list")
def canary_bauble_list(request, show: str = "live"):
    """List baubles

    Every bauble this hat can see — the live ones unless `?show=archived` asks
    for the others.
    """
    return []
