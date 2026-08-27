

# planted violation: a service reaching the management API itself. This is the
# C2 shape the rule exists for — the call would run inside the service's
# transaction, so a Zitadel hiccup rolls back a row that was perfectly good.
from apps.accounts import zitadel as _canary_zitadel  # planted violation
