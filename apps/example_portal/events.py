"""The names of the things this app says happened.

Names only. `services.py` emits each one inside the write's transaction, with
the request as every door renders it (`PortalRequestOut`), so a webhook
subscriber, a staff screen listening on the socket and the customer who sent it
read one shape.
"""

from __future__ import annotations

# golden: portal begin
PORTAL_REQUEST_SUBMITTED = "example_portal.portal_request.submitted"

# Said once per request a widget merge carries from the merged widget to the one
# that survived: the request's widget changed, and a subscriber following the
# request hears which widget it is about now.
PORTAL_REQUEST_MOVED = "example_portal.portal_request.moved"
# golden: portal end
