

# negative: this module IS the edge where `core.mail`'s I/O happens, and rule
# 25's allow-list says so with the reason. An allow-listed import must stay
# silent, or the allow-list is decoration.
from apps.core import mail as _negative_allowed_mail
