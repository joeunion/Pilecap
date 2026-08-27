

# The chokepoint's own legitimate import, planted in the module the allow-list
# names. An allow-list that fires is decoration; this is the half that proves it
# does not.
from apps.search import engine as _negative_engine  # noqa: F401
