# ADR ident-6

**ADR ident-6 · erasure and deactivation get doors.**
*Context*: `erase_user` and `deactivate_user` were built, tested and
audited, and only a shell reached either — `erase_user` was one of the four
names in accounts' house-rule-42 census, which is the rule's complaint said
about the two most consequential acts in the product. *Decision*: self-serve
(`/users/me/…`) and admin-initiated (`/users/{user_id}/…`) doors over the
EXISTING services, on REST and MCP; **who may erase or deactivate whom is
`policies.py`'s** — `themselves_or_administers_the_whole_tenant`: the person
themselves, or an `admin` or better at the tenant's **root**, the wall stated
in code (C7) and never in a door. `deactivate_user` gained `actor` and
`tenant` — additions, not replacements — because a service that resolves no
actor authorizes nothing and a service that declares no `tenant` is not
audited, so the door could not have been given the wall without breaking C7
from the door side. A broader completeness sweep of the same census remains a separate, unchanged
effort. *Rejected*: waiting for that sweep (doors are ratified now; the
contract does not change when the sweep deepens); erase-by-DELETE on
a user resource (erasure is a service act with an audit row, not a REST
cascade); `me/` twins on MCP (a second pair whose only difference is an
omitted argument is a second place for an agent to guess wrong).
trigger to revisit: the completeness sweep landing — re-run this ADR's door
tests byte-unchanged.

**Amended 2026-10-09 (owner, "we keep all admin logs", 2026-10-08; recorded by the PM; N1989):** `admin.LogEntry` (`django_admin_log`) is retained whole — `apps.core.lifecycle` declares it `unbounded` with the reason "the owner retains every admin log (2026-10-08)", and `erase_user` never touches it; the erasure census excludes the table by that declaration, never by silence (rule 31's `admin` class reads it). Rejected: scrubbing the person's rows at erasure (the log is the operator's record of what staff did, not the person's data); a bounded retention (none was asked for).
