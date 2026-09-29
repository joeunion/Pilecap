

# Planted: a `Versioned` noun renamed through `save(update_fields=[...])` that
# does not list `updated_at` — the name changes and the version does not.


class ZzzVersionedNote(OrgScopedModel, Versioned):  # noqa: F821
    name = "a noun whose writes carry the version they were made against"


def zzz_rename_note(note: ZzzVersionedNote, name: str) -> None:
    note.name = name
    note.save(update_fields=["name"])
