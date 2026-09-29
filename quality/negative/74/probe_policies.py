"""The probe app's policies.py BASE, planted only when no other rule's form made one.

`mode: default` — when the whole corpus runs, rule 13's negative has already
created the probe's `policies.py` with its `POLICIES` dict and this file is
never written; when `--rule 74` runs alone, it is the dict the road's policy
pair below is appended to.
"""

POLICIES: dict = {}
