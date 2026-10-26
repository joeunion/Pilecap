from typing import ClassVar

from django.apps import AppConfig


class TagsConfig(AppConfig):
    """Tags on any noun — the second owner of an attachment.

    A tag is the tenant's shared word (`Tag`); a link says that one subject row
    carries it (`TagLink`). The subject is POLYMORPHIC — a `(subject_kind,
    subject_id)` pair resolved and authorized at every write by
    `core.verbs.resolve_subject` — so a product's noun gains tags by declaring
    `attachments = ("tags", ...)` on its model and nothing else: no foreign key
    per noun, no route per noun, no migration in the noun's app.

    `depends_on` names three apps and each is load-bearing:

    * `core` — the scoped bases, `Archivable`, the verb seams
      (`resolve_subject`, `archive_row`, `Repointer`) and authorization;
    * `accounts` — `API_AUTH`, the one authenticator list every router carries;
    * `events` — `emit()`, called inside each write's own transaction. This is a
      platform app, so it imports the spine directly rather than through the
      bridge the removable worked example uses.

    Nothing here imports a noun's app: a subject is reached through the kind
    registry, never through an import, which is what lets a product's nouns
    adopt tags without this app learning their names.
    """

    name = "apps.djb_tags"
    verbose_name = "Tags"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 36,
        "91.docstring-tail": 81,
        "91.module-tail": 63,
        "91.narrative": 4,
    }
