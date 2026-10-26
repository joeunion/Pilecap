# Negative: an operator message that names the setting through core's constant.
# The name `PUBLIC_BASE_URL_SETTING` contains the setting's word but reads no
# base URL, so no link is built from it and the counted class does not move.
from apps.core.surfaces import PUBLIC_BASE_URL_SETTING


def zzz_canary_base_url_advice() -> str:
    """The sentence an operator reads when the deployment's base URL is unset."""
    return f"Set {PUBLIC_BASE_URL_SETTING} to the address the deployment is reached at."
