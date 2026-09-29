

# The legal shape: the same rename listing `updated_at`, so the version moves.


class ZzzVersionedNote(OrgScopedModel, Versioned):  # noqa: F821
    name = "a noun whose writes carry the version they were made against"


def zzz_rename_note(note: ZzzVersionedNote, name: str) -> None:
    note.name = name
    note.save(update_fields=["name", "updated_at"])
