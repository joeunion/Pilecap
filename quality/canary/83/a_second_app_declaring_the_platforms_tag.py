# Planted: one tag key carried by a second app. A tag is a scope family — the
# key a token's ceiling names — so an operation in another app tagged with the
# platform's `djb_notes` puts that app's route under a ceiling minted for the
# platform's notes, and the document files it under the platform's section.
# Nothing refuses it at the door: the scope derives cleanly from the tag.
#
# Planted as a route-level `tags=` on a real module (a route's own `tags=`
# replaces its router's), so no router or `TAGS` rebinding disturbs any other
# form planted beside it.


@router.get("/zzz-canary-borrowed/", url_name="zzz_canary_borrowed-list", tags=["djb_notes"])
def zzz_canary_borrowed_list(request):
    """List a borrowed section

    Planted by the quality gate's self-test. It exists for the length of one run.
    """
    return {"who": "a borrower"}
