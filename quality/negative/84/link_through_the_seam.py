# Negative: the same invitation link, built by the one URL seam for the surface
# of the role the invitation is for. Nothing here names the settings' base, so
# the counted class does not move.
from ninja import Schema

from apps.core.surfaces import absolute_url, surface_for_role


class ZzzCanaryInvitationOut(Schema):
    """An invitation as its reader sees it."""

    role: str
    sign_in_url: str = ""

    @staticmethod
    def resolve_sign_in_url(obj: "ZzzCanaryInvitationOut") -> str:
        return absolute_url(path="/accounts/login/", surface=surface_for_role(obj.role))
