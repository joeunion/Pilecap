# Planted: the collision a product meets the day it folds a release that
# mounts a platform app — a second module binding a path another module already
# serves. django-ninja refuses nothing: the URL resolves to whichever module was
# discovered first, the published document describes the other, and nothing
# 500s. Both modules answer "fine" on their own; only the pair is wrong.
#
# Planted as a ROUTE PATH on a real root-mounted module (`PREFIX = ""`) rather
# than as a `PREFIX` on the probe app, because the probe's `PREFIX` is one
# module global every django form of every rule appends to — rule 32's own
# canary owns it — and a `PREFIX` line here would silently re-mount every other
# form. A route path under an empty prefix and a `PREFIX` are one finding, not
# two: the check reads the MOUNTED path. On a real module, so the walk is also
# shown not to be looking at the probe alone.


@router.get("/djb_notes/", url_name="zzz_canary_shadow-list")
def zzz_canary_shadow_list(request):
    """List a shadowed page

    Planted by the quality gate's self-test. It exists for the length of one run.
    """
    return {"who": "the second module"}
