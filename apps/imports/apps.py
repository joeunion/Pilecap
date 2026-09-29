from django.apps import AppConfig


class ImportsConfig(AppConfig):
    """Bring rows in from a file — checked first, applied second, never twice.

    One platform app for every noun, because staging, the dry run, the per-row
    refusals and the resume after a crash are the same machine whatever the row
    is. What differs per noun is declared by the noun's own app, beside itself:
    an `importers.py` exporting `IMPORTERS = {"<kind>": Importer(...)}` (the
    `core.verbs.Importer` shape — a row schema, a read-only natural key, and an
    `apply` that calls the noun's OWN services). This app finds them through
    `core.verbs.hook("importers")` and imports none of them.

    `depends_on` names five apps and each is load-bearing:

    * `core` — the tenant, the tree, `@service`, the vocabulary, the family seam;
    * `accounts` — the person who staged a run and the person who applied it;
    * `events` — `imports.import.{staged,previewed,applied,failed}` are published
      inside the write that makes them true;
    * `workflows` — the check and the apply are durable runs that survive a
      deploy and resume after a crash;
    * `files` — the CSV is a document: staged by its `FileVersion`, whose digest
      the files seam measured, and read back through the seam's server-side
      stream (`files.storage.iter_object`), never through a door.
    """

    name = "apps.imports"
    verbose_name = "Imports"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "workflows", "files")
