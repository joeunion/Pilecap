"""Who may read what this tenant has consumed. **Nothing here, and that is the news.**

This file used to hold a small permissions system of its own — a
`DeclaredPermission` dataclass, an `ALL_ROLES` set derived from `ROLE_RANK`, and
a `USAGE_READ_REPORT` declaration a product narrowed by editing one line. It was
the right answer to the question it was asked (an owner ruling: *declare the bar,
do not argue it in a docstring*), and P20 answered that question for the whole
platform instead. So the mechanism moves out and the app keeps the decision:

* **the key** is `usage_entry.read` — the derived read of `UsageEntry`, which is
  the row every total here is a sum over. `usage.read_report` still answers, as
  an alias, for one release (`RENAMED_PERMISSIONS` below);
* **who holds it** is the three layers `core.authz` resolves — `owner` by the
  vocabulary, `admin` by `("*",)`, `member` by `("*.read",)`, plus whatever a
  custom role includes and a grant allows or withholds. The template's answer is
  byte-identical to the declaration's: every role read the report before and
  every role reads it now;
* **narrowing is DATA, not an edit.** A product that wants only owners and
  admins to see the bill no longer changes a line in this file and ships it —
  its administrator writes a `RolePermission` exclude on `member`, or a `Grant`
  withhold on one person, through the role editor's own doors, in a running
  deployment, audited. `tests/test_policies.py` drives exactly that, which is
  what the seven tests it used to have became.

**There is still no `usage.record`, and the missing key is still the design.**
Recording is not something anybody asks for: it is the platform's witnessed
side-effect of an action that was already authorized — the completion ran, the
file was stored — and `services.record_usage` carries rule 13's `# authz:` valve
saying exactly that, with the actor kept for the audit row rather than asked for
permission. A `usage.record` predicate would be a permission nobody could ever be
refused, which is a permission that teaches a reader the wrong thing about what
this app does.

**And there is no predicate**, which is the other half of the same sentence.
`POLICIES` is empty because the two questions a predicate could have asked are
both answered elsewhere and better: *which rows* is `for_tenant(t).visible_to(actor)`
in `selectors._ledger` (rule 24), and *whether this kind, here* is the key above,
resolved by `core.authz.require` against rows a tenant can edit. A predicate here
would be a third opinion nobody could change without a deploy. The dict stays so
the discovery walk finds a shape it recognises and so a product's first predicate
is an addition rather than a new file.
"""

from __future__ import annotations

from apps.core.authz import Policy

#: The key this app renamed when the vocabulary became one shape, and the whole
#: cost of renaming one (ADR core-25). `core.authz.allows` resolves the alias one
#: line BEFORE the policy lookup, so a product still calling
#: `require(actor, "usage.read_report")` gets exactly the answer it got before,
#: with one deprecation printed per process. `manage.py rename_permission` is
#: what rewrites rows once a deployment has grants naming the old word.
#:
#: The successor is the DERIVED key of the row the report totals rather than a
#: second spelling of the report: `usage.read_report` named no kind at all —
#: `usage` is an app, `UsageEntry` is the kind — so nothing a tenant wrote about
#: the rows could reach the read that returns them.
RENAMED_PERMISSIONS: dict[str, str] = {
    "usage.read_report": "usage_entry.read",
}


#: **Empty, and it is a statement.** See the module docstring: the row filter is
#: `visible_to`'s and the capability is the vocabulary's, so there is nothing
#: left for a predicate to decide that a tenant could not decide for themselves.
POLICIES: dict[str, Policy] = {}


# The sentence a refused caller reads. Plain language, never the action name;
# a product declares these beside its policies and never edits `core`.
#
# An override of the sentence a derived key would otherwise carry ("You may not
# read this usage entry.", assembled from `verbose_name`): the reader of this
# refusal asked for a REPORT, and a refusal that named a row they never asked
# about would be true and useless. `decided_by` stays `derived` — an
# `ACTION_PROSE` entry for a key the registry already derived is a sentence
# override and not a second declaration (`core.authz._build`, step 1).
ACTION_PROSE: dict[str, str] = {
    "usage_entry.read": (
        "You may not read this tenant's usage. A usage report covers the part of "
        "the organization you are acting as, and reading it is a capability your "
        "role or a grant has to carry."
    ),
}
