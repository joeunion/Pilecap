# Planted: a second app titling a family of its own with the platform's words.
# The key is new, so no token ceiling reaches both apps and the tag clause is
# silent — but the published document emits each key's display as a heading
# and compares none, so the reader meets two "Notes" sections and cannot tell
# which family is which. Human or agent, the heading is what they read.
#
# Planted as an ADDED `TAGS` entry and one route under it on a real module, so
# the module's own sections keep their words and no router is rebound.

TAGS["zzz_canary_notes"] = Tag(
    "Notes",
    "A second app's notes, for the length of one self-test run.",
)


@router.get("/zzz-canary-headed/", url_name="zzz_canary_headed-list", tags=["zzz_canary_notes"])
def zzz_canary_headed_list(request):
    """List a headed section

    Planted by the quality gate's self-test. It exists for the length of one run.
    """
    return {"who": "a second heading"}
