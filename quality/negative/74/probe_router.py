"""The probe app's api.py BASE, planted only when no other rule's form made one.

`mode: default` — when the whole corpus runs, rule 3's form has already created
the probe's `api.py` and this file is never written; when `--rule 74` runs
alone, it is the router and the described, named tag the road below appends to.
"""

from ninja import Router

from apps.core.api.docs import Tag

TAGS = {
    "zzz-canary": Tag(
        "Gate probe",
        "The quality gate's probe app. Nothing here is a product capability: these "
        "routes exist for the length of one self-test run, so a planted violation "
        "can be shown to fire through the real registries.",
    ),
}

router = Router(tags=["zzz-canary"])

# The first path segment names a resource, never the app label (house rule 32):
# the probe's routes hang under a word no installed app is called.
PREFIX = "probe"
