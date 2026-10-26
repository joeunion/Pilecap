"""The service-verb matcher: which verb a service's name begins with. Standard library only.

Three readers ask this one question, and before this module each asked it its
own way: house rule 16 (does a service begin with a declared verb — the gate,
which imports no settings module), the machine door's `service_verbs()` (which
verbs the product's services use — a twinless tool's scope), and the history
card (`HistoryEntryOut.verb`, the verb an audit row's action did). A first-word
split and a longest-prefix match disagree on exactly the names that matter — a
two-word verb (`dead_letter_delivery` is `dead_letter`, not `dead`) — so the one
matcher is the longest-prefix one, and a caller with no declared lexicon gets
the first word, which is what a longest-prefix match over nothing answers.

Standard library only, beside `apps/core/roads.py`, for the reason that module
gives: the quality engine imports it without Django.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.core.roads import road


@road("service_verb", example="apps/core/mcp.py::service_verbs")
def verb_of(name: str, verbs: Iterable[str] = ()) -> str:
    """The verb `name` begins with: the longest of `verbs` it starts with, else its first word.

    `name` may carry a dotted owner (`example.update_widget`, an audit action);
    only the last segment is read. A verb matches the whole name or a prefix
    ending at `_`, so `archive` never matches `archived_count`.
    """
    bare = name.rpartition(".")[2]
    for verb in sorted(verbs, key=len, reverse=True):
        if bare == verb or bare.startswith(f"{verb}_"):
            return verb
    return bare.split("_", 1)[0]


#: The endings of a singular word that ends in `s` (rule 16's plural test).
#: Standard library only: the gate's engine imports this module.
SINGULAR_S_ENDINGS = ("ss", "us", "is")

#: Plurals no `s` marks. Reach: platform; a product adds one as an `app_name_exemptions` entry.
IRREGULAR_PLURALS: tuple[str, ...] = (
    "people",
    "children",
    "staff",
    "personnel",
    "media",
    "data",
    "criteria",
    "men",
    "women",
    "feet",
    "teeth",
    "mice",
    "geese",
    "alumni",
    "fungi",
)

#: The one sentence rule 16 and `newapp` end an app-name refusal with.
PLURAL_REMEDY = (
    "an irregular plural (people, children…) is already admitted; a deliberate singular "
    "(a mass noun such as billing) is an entry under scope_extensions: {16: …} in "
    "quality/local/rules.yaml, with its reason"
)


#: Words with no plural of their own: a noun's history is one history, so the
#: history road's list (`<noun>_history-list`) is `list_<noun>_history`.
UNCOUNTABLE: frozenset[str] = frozenset({"history", "usage"})


def inflected(noun: str) -> str:
    """`apps.core.verbs.plural`'s body, importable where Django is not configured."""
    head, _, last = noun.rpartition("_")
    if last in UNCOUNTABLE or looks_plural(last):
        return noun
    if last.endswith("y") and last[-2:-1] not in ("a", "e", "i", "o", "u"):
        last = f"{last[:-1]}ies"
    elif last.endswith(("s", "x", "z", "ch", "sh")):
        last = f"{last}es"
    else:
        last = f"{last}s"
    return f"{head}_{last}" if head else last


def looks_plural(word: str) -> bool:
    """Whether a word's last `_`-segment is plural: an irregular, or `s` not `ss`/`us`/`is`."""
    last = word.lower().rpartition("_")[2]
    if last in IRREGULAR_PLURALS:
        return True
    return last.endswith("s") and not last.endswith(SINGULAR_S_ENDINGS)
