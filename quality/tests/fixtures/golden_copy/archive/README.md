# The golden-copy drive's self-case: a planted archive adoption

`quality/tests/test_golden_copy.py`'s self-case writes each `.py` file here to the
same relative path in an EMPTY scratch source — nothing of `apps/example` is in
it, so the example's own real fences cannot meet these — each behind one
unfenced decoy line the copy must leave behind, then runs the drive's copy →
check → drop cycle over that source. Each
file is one fenced block — `# golden: archive begin` … `# golden: archive end` —
written the way the worked example writes a block a product copies: on `Widget`,
complete enough that the text between the fences, renamed `Widget`→`Gadget`,
builds an app on its own.

It proves the INSTRUMENT, not the example: the real worked example's fences are
the adopting noun's, and `--verb archive` reads those.

**The placement canary and its negative.** `services.py` here also carries a
private helper whose fenced `require_live(...)` sits after its `return` — dead
code a copy would carry and the copied test would never reach. The self-case
plants this tree twice: a CANARY source with the files as they are, whose copy
the placement step must red on (naming the copied `services.py` line and the
source fence it came from), and a BUILD source with
`../negative/archive/services.py` in this file's place — the clean negative
the copy actually builds, checks and tests, on which the placement step must
stay silent.

**The verb list's two, and its negative.** `models.py` is fenced
`# golden: archive version begin` — one block two verbs share, which the
archive copy must take (its marker line, `golden-copy-two-verb-fence`, is looked
for in the copy). `events.py` also carries a block fenced for `version` ALONE,
whose one line raises if it is carried: the archive copy must leave it behind.
`../typo/models.py` names `verison` in its fence; the self-case plants it into a
third scratch source and the extractor must refuse it, naming the word.
