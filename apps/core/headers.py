"""The Temporal header names a run's principal and its correlation chain travel under.

Standard library only: the interceptor module that reads them is loaded into the workflow sandbox.
"""

from __future__ import annotations

#: The tenant a run acts for.
TENANT_HEADER = "djb-tenant-id"
#: The hat (organization) a run acts as.
ORG_HEADER = "djb-org-id"
#: The person a run acts for.
USER_HEADER = "djb-user-id"
#: The business chain a run belongs to; HTTP's spelling is `core.middleware.CORRELATION_ID_HEADER`.
CORRELATION_HEADER = "djb-correlation-id"
#: The step that caused this run.
CAUSATION_HEADER = "djb-causation-id"
