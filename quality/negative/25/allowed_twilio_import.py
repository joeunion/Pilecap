

# negative: the pinned exemption, proved in the one module rule 25's allow-list
# actually names. `apps/comms/providers.py` holds the vendor transport and the
# vendor's own signature check; an allow-list entry with no negative behind it
# is an exemption nobody re-reads.
from twilio.request_validator import RequestValidator as _negative_allowed_validator
