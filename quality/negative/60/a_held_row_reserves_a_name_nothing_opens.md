
## A PLANTED `drawers` BLOCK — the control for the `held` state

A RESERVED NAME IS NOT A BROKEN ROW. A `held` row writes `—` for both machine
fields and names a drawer no reader opens yet: the name is reserved so no
release can ship it and no later rung can take it for something else, and the
rule prints it as held rather than firing on a reader that is deliberately not
there. Without this control the two `held` rows this table really carries
(`scripts/local/hooks/`, `deploy/verifier/local/bake.d/`) would be indistinguishable
from the form above, and the state would be decoration.

```drawers
held | a seam reserved against a rung that has not landed | scripts/local/reserved.d/<name>.sh | — | —
```
