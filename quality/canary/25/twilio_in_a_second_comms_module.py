

# canary: the SDK reached from a comms module that is NOT `providers.py`. Being
# the comms app is not the exemption — ADR comms-9 pins the vendor SDKs to
# `apps/comms/providers*`, and a service importing the client would be a send
# that never passed `send()`'s consent, quiet-hours and suppression walls.
import twilio.rest as _canary_twilio_in_services  # planted violation
