

# Not this rule's population: the same two writes on a noun that never declared
# `Versioned` — it is last-write-wins by the settled default, and no version
# exists to go stale.


class ZzzPlainNote(OrgScopedModel):  # noqa: F821
    name = "a noun with no version"


def zzz_rename_plain(note: ZzzPlainNote, pk: object, name: str) -> None:
    note.save(update_fields=["name"])
    ZzzPlainNote.objects.filter(pk=pk).update(name=name)
