# Planted: the OTHER door into the same leak, and the one 's own fix
# makes newly reachable.
#
# Once an app flattens to `PREFIX = ""`, the first path segment stops being the
# module's decision and becomes each ROUTE's — so the next builder who writes
# `@router.get("/workflows/...")` in a flattened module puts an app label back
# on the wire without ever typing a `PREFIX`. A check that read only `PREFIX`
# would be silent here, which is why the census walks the MOUNTED path: a
# prefix and a route path are one finding, not two.
#
# Planted on a real product api module rather than on the probe app, so it also
# proves the walk is not looking at one blessed file.

PREFIX = ""


@router.get("/workflows/leak/", url_name="canary-flat-leak")
def canary_flat_leak(request):
    """Leak a taxonomy

    Planted by the quality gate's self-test. It exists for the length of one run.
    """
    return {"ok": True}
