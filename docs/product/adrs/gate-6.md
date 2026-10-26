# ADR gate-6

**ADR gate-6 · SIGNED by the owner 2026-09-22 · an unmeasured class says how to be recorded.**
*Proposed 2026-09-21 (P21, team D, the ratchet rung). The owner chose option B in the
ratchet ruling of 2026-09-21; the signature that turns this line into
"Accepted" is the PM's ritual at the cycle's CLOSE.* *Context:* per-app ratchet
classes name only the template's apps; a product's app had no class and the
hook was unpassable until the product reverse-engineered the grammar.
*Decision:* an app outside the partition with no recorded class is unmeasured —
a violation that prints the exact `ratchets:` line, `recorded-at <sha> [fold]`,
down-only afterwards; partition apps stay zero by absence; ratcheted rules
carry `remedies:` that `--explain` prints. *Rejected:* self-recording (no
hand), note-only (green-because-unrecorded), a template-wide zero for products
(the hook stays unpassable). trigger to revisit: F's overlay file.

*Amended (rung X3F, 2026-09-21): the line the unmeasured finding prints is
pasted into `quality/local/rules.yaml` — the product's drawer (P21 EP2) —
under its top-level `ratchets:`, keyed `"<rule id>": {<class>: <n>}`, and every
note that offers a human a number to commit names whichever of the two files
that class's count actually lives in. The decision's `quality/rules.yaml` is
template-owned and a fold overwrites it.* *And the decision's "ratcheted rules
carry `remedies:`" is, as built, rules 54 and 55 only: nine other ratcheted
rules carry none, `--explain` prints the key where it exists, and widening the
population is a rung of its own rather than a sentence here.*

*As built (rung D3), the three places the decision above needed one more
sentence, each recorded rather than implied:* **(a)** a ratchet class is
app-keyed only when the FINDINGS say so — every finding in the class sits under
`apps/<label>/` for the label its key opens with — because `nonconforming` and
`secrets` are class names and a predicate reading the key alone would offer to
record an app nobody has (`unmeasured_app`, `quality/gate.py`); the plan's own
blind spot, that 54's `nonconforming` gets no unmeasured form, is this
derivation's price and is kept. **(b)** an entry recorded at `0` is a
MEASUREMENT and takes the ordinary path; only an ABSENT key is unmeasured, so
the engine reads the recorded key set and not `get(klass, 0)`. **(c)** the
partition is read through `quality/partition.py`, and a lockfile that will not
read shuts the branch rather than emptying the app list — an empty partition
would make every app on the tree a product's and turn one missing file into a
refusal storm; it is exit 2 on its own line instead.

*As built (rung HOTFIX-DRAWER-1, 2026-09-22), the fourth sentence, from the
first consumer's fold: a drawer class on a TEMPLATE rule may name a FINDING
CLASS that rule declares under its own `ratchets:`, as well as an app of the
product's. The decision read every class as app-keyed because every ratcheted
rule it was written against was; rules 50–53 ratchet per finding class
(`literal`, `api-reach`, `barrel`, `consumed-undeclared`), which is not an app
and never will be, so a product with a real backlog in one was refused with a
sentence about an app directory named `literal`. Those rules now declare their classes at `0` —
a measurement, per (b) — and the drawer's number is **added** to the template's
rather than substituted for it, so a product can record its own backlog without
being able to erase a template ceiling from a file the template never reads;
where the template records `0` the sum is the drawer's number and the two
readings coincide. A name that is neither an app nor a declared class is
refused with the sentence it always had, now carrying the list of the classes
that rule does declare.*

*As built (P24 FE-2, and the fix that followed its first train): **a recorded
class above its count is a violation, not a note.** Before it, the self-test
read every rule's canaries with `ratchets=False` and the ratchet leg forged
only one rule's shape, so a number recorded above a class's count was a note
for every rule. The ratchet leg's one reader, `ratchet_headroom`, now judges
every recorded row of every rule that declares `ratchets:` against the tree's
count — on the template's own shape only: a row above its count is a red
carried by the rule's own line and trailer (exit 1, since a tree disagreeing
with its own declaration is a judged red and not a dead instrument), at-count
and at-zero are silent; on any other shape — a declared base, a world — it
judges nothing and prints one line naming the shape and why, because a
template row above a product's count is the fold's business and the live
scan's note already names the number; a shape the census cannot read is
could-not-look, never a silent skip. The forged forms follow the same
decision: a raised row named once on the template's shape, a raised row on a
remote base or a world not named, and a skip that does not name its shape
refused.*
