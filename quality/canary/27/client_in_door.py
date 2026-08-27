

# planted violation: a door importing the client, through the other import
# form and from a different app. A route that made a management call would put
# an unbounded network round trip on somebody's request.
from apps.accounts.zitadel import ensure_project as _canary_ensure_project
