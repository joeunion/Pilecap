"""Planted by rule 13's self-test: the probe app's own policies.

Here so the planted app is a WHOLE app rather than a models.py nobody holds a
capability over — a `Gadget` with no `policies.py` beside it is rule 13's
django half's finding (`djb.E013`, a scoped model with no policy entry), and a
canary that trips two clauses at once cannot say which one it proved.

The declared sentence also exercises the other half of clause (iv)'s key set:
`gadget.burnish` is not one of the four verbs any kind derives, and it is in
the vocabulary anyway because this file declares it. A negative asks for it and
stays silent, which is what proves the declared half is read rather than
assumed.
"""


def _canary_allow(actor, obj=None):
    return True


ACTION_PROSE = {"gadget.burnish": "You may not burnish this gadget."}

POLICIES = {
    "gadget.create": _canary_allow,
    "gadget.burnish": _canary_allow,
    "gizmo.create": _canary_allow,
}
