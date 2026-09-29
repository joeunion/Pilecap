from django.apps import AppConfig


class NotesConfig(AppConfig):
    """Notes on any noun — the first of the three attach owners.

    **A note points at its subject; nothing points at a note.** The subject is a
    polymorphic pair, `(subject_kind, subject_id)`, rather than a foreign key
    per noun: a template cannot know which nouns a product will have, and a
    concrete link table per noun would cost a model, a migration and a set of
    routes every time a product added one. The price is declared rather than
    hidden: the database will not stop a note outliving its subject. What stops
    that from ever being WRONG is the read road — a note is read only through
    its subject (`?subject=<kind>:<id>`), which is resolved and authorized
    first, so a note whose subject is gone is unreachable, never misattributed.

    **Every write resolves the subject again** through `core.verbs.resolve_subject`
    (the kind registry, the tenant, archived rows included, the acting hat,
    `may_be_named`), and the note lands in the SUBJECT's organization, so a
    note can be seen by exactly the hats that can see what it is about.

    **A noun opts in by declaring it**: `attachments = ("notes", ...)` on the
    model class. A kind that has not declared notes is refused `invalid`
    naming `subject` — the declaration is the whole population, and nothing
    here holds a list of nouns.

    `depends_on`:

    * `core` — the scoped managers, `@service`, the authorization vocabulary,
      and `core.verbs` (the subject resolver, the archive pair, `Repointer`);
    * `accounts` — `author` is a foreign key to `settings.AUTH_USER_MODEL`, and
      the actor a note is written under is a person from that app;
    * `events` — every note write says what happened, inside its transaction.
    """

    name = "apps.notes"
    verbose_name = "Notes"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")
