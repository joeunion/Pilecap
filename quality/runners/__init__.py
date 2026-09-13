"""External measuring instruments the house-rules engine invokes as subprocesses.

A runner is handed a tree and answers one question — *what did you see* — in the
check-v1 protocol (`quality/check_v1.py`). It carries no verdict semantics:
overrides, ratchets, floors and 0/1/2 all live on the engine's side of the
process boundary, and a runner that cannot be believed is enforcement broken
rather than a clean scan.

A runner is invoked through its interpreter (`python3 <path>`, `node <path>`)
rather than by its own execute bit, deliberately: an executable file outside
`apps/` and `config/` owes a row in the instrument census, and a runner is an
implementation detail of the rule that declares it rather than a thing anybody
runs by hand.
"""
