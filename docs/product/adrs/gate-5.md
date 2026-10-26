# ADR gate-5

**ADR gate-5 · SIGNED by the owner 2026-09-22 · rule ids are two namespaces.** *Proposed 2026-09-21
(P21, team D, rung D1). The owner chose option A in the rule-id ruling of
2026-09-21; the signature that turns this line into "Accepted" is the PM's
ritual at the cycle's CLOSE.* *Context:* house-rule ids were one integer
sequence the template and a product both appended to; a fold merged duplicate
ids and fixture dirs (`canary/54` = theirs + ours), exit 2 at the product's
first gate, renumbered by hand each release. *Decision:* only the
template mints integers; a product declares `rule_id_namespace: <ns>` once and
its rules are `<ns>-<n>` in id, fixture dir, valve and check tag; the engine
refuses any other shape and any fixture file no entry claims. *Rejected:* an
integer range (unrefusable), allocation at publish (renumbers the product), a
second file alone (no grammar, a moved rule still collides). trigger to revisit: a
product with two namespaces.

*Amended (rung X3, 2026-09-21): the two keys' HOME is
`quality/local/rules.yaml`, the product's drawer, and the engine refuses either
of them in the template-owned `quality/rules.yaml` with the line that names the
move.* D1 wrote them into `quality/rules.yaml` because the drawer did not exist
yet; a declaration in a file a fold overwrites is a declaration that disappears
at the next release, which is the same failure the namespace itself exists to
end, one file up. Everything else about gate-5 is unchanged — the grammar, the
four spellings, the refusals and the residence split.

*As built (rung D1), the two places the decision above needed one more
sentence, both recorded rather than implied:* **(a)** a shape wall alone cannot
refuse a product that types a bare integer — an integer is the template's legal
shape and nothing else on the tree says which integers the template minted — so
the declaration is two keys, `rule_id_namespace: <ns>` beside
`template_rule_ids_through: <n>` (in `quality/local/rules.yaml`, per the
amendment above), the second being the highest integer the
folded template release had minted. It is `quality/partition.yaml`'s and
`FROZEN_FAMILIES`' pattern (a record of the past, in a diff a human reads), the
template never carries it, and the template's self-test prints the number a
product should record on every run. **(b)** the residence census counts TEMPLATE
ids only (D4), so `selftest_residence_backlog` stays a template fact a product
folds and never retypes, and a product's own rules are counted against zero.
