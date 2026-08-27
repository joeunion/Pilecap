

# negative: this module IS the edge where the management I/O happens, and rule
# 27's allow-list says so with the reason. An allow-listed import must stay
# silent, or the allow-list is decoration.
from apps.accounts import zitadel as _negative_allowed_zitadel
