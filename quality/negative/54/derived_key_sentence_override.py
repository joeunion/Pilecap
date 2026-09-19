"""The right form, kept forever: prose overriding a DERIVED key's sentence.

`gadget.create` is one of the four verbs the kind already derives, and an
`ACTION_PROSE` entry for it is not a declaration at all — it is the app saying
what the refusal should read like instead of the sentence built from the
model's `verbose_name`. Reading it as a declared key would report every
well-written app in the tree as non-conforming.
"""

ACTION_PROSE = {"gadget.create": "You may not make gadgets in this branch."}
