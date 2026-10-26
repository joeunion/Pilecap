"""The self-case's policy block: the archive pair is an administrator's press."""

# golden: archive begin
from apps.core.authz import Policy
from apps.core.policies import may_archive

POLICIES: dict[str, Policy] = {
    "widget.archive": may_archive,
    "widget.restore": may_archive,
}
# golden: archive end
