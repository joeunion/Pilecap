"""The house-rules engine.

`rules.yaml` is the data, `checks.py` the checks, `gate.py` the runner:

    python -m quality.gate               # consistency + live scan + floors
    python -m quality.gate --selftest    # plant every canary, expect fire;
                                         # plant every negative, expect silence
    python -m quality.gate --diff REF    # + the diff-aware checks against REF

Exit codes: 0 clean · 1 violations · 2 enforcement broken. 2 outranks a pass.
"""
