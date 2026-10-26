# Planted: an invitation's `Out` whose link is resolved from the settings' base
# URL by hand. It answers the staff host for everybody, so a customer's
# invitation lands on the staff face; the seam would have built it for the
# surface of the role the invitation is for.
from django.conf import settings
from ninja import Schema


class ZzzCanaryInvitationOut(Schema):
    """An invitation as its reader sees it."""

    role: str
    sign_in_url: str = ""

    @staticmethod
    def resolve_sign_in_url(obj: object) -> str:
        return f"{settings.PUBLIC_BASE_URL}/accounts/login/"
