"""What this app makes findable. **The worked adoption, and the whole of it.**

This file is the answer to "how does a product put its own rows into search?",
and its shortness is the answer: one list, one declaration, no registration.
`apps.search.registry` discovers `apps/<x>/search.py` and reads `SEARCHABLES`
out of it — the `events.py` / `meters.py` pattern — so adding a kind edits no
shared file, and one agent per app can add one in parallel. Nothing here is
imported by `config/`, `pyproject.toml` or the search app; the search app comes
looking.

**Three things this file owes, all of them checked at boot rather than at
review** (`registry.validate`, from `SearchConfig.ready()` — `ImproperlyConfigured`
stops the process, which is the strongest tier this tree has for a declaration):

* **Every field is a concrete column on the model.** A field that is not there
  indexes `None` for ever: the kind exists, the index exists, the queries run,
  and nothing is ever found, with no error anywhere to say why.
* **Every weight is one of `A`, `B`, `C`, `D`** — Postgres's four `setweight`
  labels, and the vocabulary is closed. Meilisearch has no weights at all
  (declaration ORDER is its ranking), so a fifth letter is *inert* on the
  primary engine and an *error* from the database on the degradation engine:
  it would ship green and break on the day the circuit opens, which is the day
  everything else is already going wrong.
* **Every `refresh_on` name is a constant from the emitting app's own
  `events.py`** — never a literal (house rule 16). A name nobody publishes is a
  subscription that silently never fires: the startup reconcile builds the first
  document and then nothing ever refreshes it, which reads as "search is stale"
  long after the deploy that caused it.

**The label is public vocabulary and it freezes the day a client can send it.**
It is lowercase letters, digits, `_` and `-`, starting with a letter or a digit,
because it becomes the tail of the Meilisearch index uid (`<prefix>_<label>`)
and the value `?kinds=` names on the wire — an illegal one is a 400 from the
server at the first write of a fresh checkout, and a public vocabulary nobody
can type. One label is one index: two kinds sharing one would interleave two
document shapes in one place and each rebuild would silently empty the other.

**The other half of adopting lives in `models.py`**: `Widget.search_vector`, the
`GeneratedField` the degradation engine reads when Meilisearch is unreachable.
The adopting app owns its own column — `apps/search` declares and reads, it
never adds a column to somebody else's table — and the field list below is the
single source for both: this list ranks the Meilisearch document AND builds that
tsvector. Two lists would be two rankings that agree until somebody edits one.
"""

from __future__ import annotations

from apps.example import events
from apps.example.models import Widget
from apps.search.types import Searchable

#: The one kind this app declares.
#:
#: `name` before `notes` is the ranking on BOTH engines, said once: declaration
#: order is Meilisearch's ranking and the `A`/`B` weights are Postgres's, and
#: they are deliberately the same order rather than two opinions about which
#: field matters more.
#:
#: `display` is what a hit is CALLED — `name`, not `str(row)`. It is the same
#: answer on both engines (`activities.display_for`), because a hit rendered
#: `Widget object (…)` while the index is down and `Bench press #4` while it is
#: up would be a difference a user sees every time this product fails over.
#:
#: `refresh_on` names the events that change what a reader would find, and
#: leaves one out on purpose. Created, updated and deleted each change the
#: document — the third is the one that REMOVES it, and a kind that subscribed
#: only to the first two would leave deleted rows findable until the hourly
#: reconcile got to them. Moved changes WHO may find it: the document carries
#: the widget's organization, and a moved widget whose document still named the
#: old node would be found by the branch it left and missed by the one it
#: joined. `WIDGET_ONBOARDED` is not here because onboarding
#: moves `onboarded_at`, which is neither a searchable field nor the display:
#: subscribing to it would buy one engine round trip per onboarding and change
#: no document.
SEARCHABLES: list[Searchable] = [
    Searchable(
        model=Widget,
        label="widgets",
        fields=[("name", "A"), ("notes", "B")],
        refresh_on=(
            events.WIDGET_CREATED,
            events.WIDGET_UPDATED,
            events.WIDGET_DELETED,
            events.WIDGET_MOVED,
        ),
        display="name",
    ),
]
