

# planted violation: a service reaching the search index itself. This is the
# shape the rule exists for — a second client is a second query path, and
# nothing on it injects the tenant filter, so the index becomes an oracle
# anybody with a keyword can probe.
import meilisearch as _canary_meili  # planted violation
