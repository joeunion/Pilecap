

# `hash()` needs no import, so it slipped past a rule that was
# watching the import line — and PYTHONHASHSEED is randomised per PROCESS, so
# a str/bytes/tuple hashes differently in the worker that replays than in the
# one that first ran. A hash-keyed branch takes the other leg on replay and
# Temporal calls the whole run non-deterministic.
def _canary_hash_branch(key: str) -> int:
    return hash(key) % 8
