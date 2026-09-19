"""The house-rules engine.

`rules.yaml` is the data, `checks.py` the checks, `gate.py` the runner:

    python -m quality.gate               # consistency + live scan + floors
    python -m quality.gate --selftest    # plant every canary, expect fire;
                                         # plant every negative, expect silence
    python -m quality.gate --diff REF    # + the diff-aware checks against REF
    python -m quality.gate --selftest-inputs
                                         # every path that can change the verdict
                                         # above, derived and sorted — what a
                                         # banked verdict is keyed on

Exit codes: 0 clean · 1 violations · 2 enforcement broken. 2 outranks a pass.

THE MEMO, per rule. A live scan consults a per-rule cache before it calls a
rule's `check:` and banks the answer after: the key is `rule-v1:<sha256>` over
that rule's own yaml text, its `scope:` allow-list, the walk of its kind, the
engine's hard-coded reads, its doc anchor and every blob under `quality/` —
all read from the MEASURED tree (`git read-tree HEAD` + `git add -A`), the
same bytes every other verdict in this system is keyed on. It lives under
`<git common dir>/djb-rules-memo/`, per checkout and never committed.

It is a PROJECTION of the scan and never a second opinion about it. The memo
holds one call's `(findings, targets)`; the overrides, the ratchets, the
floors, the runner and the Django leg run on every rule on every run, so no
hit can hide an unbound floor or a ratchet that grew. A rule whose inputs
cannot be derived is not memoised, says so, and scans. A rule that reads
something no blob can name — a live registry, a Postgres plan, an installed
package, a Django boot — declares `memo: { "no": <reason> }` in `rules.yaml`,
and a declaration with no reason is exit 2. Every live scan prints the count
and the declining ids; `--selftest` bypasses the memo entirely, and
`memo_census` proves that bypass with a planted false entry rather than a
printed word. `DJB_RULES_MEMO_DIR` is the scratch seam; `DJB_RULES_NO_MEMO=1`
scans everything.
"""
