# Negative: a noun declaring the attachment words beside a family of its own.
# `attachments = ("notes", "tags", "files")` names the OWNERS' words — read by
# the attach resolver and the merge repointers, never by the scope census —
# and `notes` and `tags` are not `TAGS` keys on any app while `files` is the
# key of exactly one. So a second noun listing them is not a second carrier of
# any family or title, by construction.
#
# A plain class carrying the declaration rather than a model: a model that
# takes attachments owes its whole attach road (house rule 74), and every
# negative shares the probe app, so a model here would be another rule's
# finding in every negative's batch. The declaration's shape is the one a
# noun writes.

from typing import ClassVar as _ClassVar83


class ZzzCanaryNotebook:
    attachments: _ClassVar83[tuple[str, ...]] = ("notes", "tags", "files")


TAGS["zzz_canary_notebooks"] = Tag(
    "Gate probe notebooks",
    "A section of the quality gate's probe app whose noun takes attachments, for one run.",
)


@router.get(
    "/zzz-canary-notebooks/{notebook_id}/",
    url_name="zzz_canary_notebook-detail",
    tags=["zzz_canary_notebooks"],
)
def zzz_canary_notebook_detail(request, notebook_id: str):
    """Retrieve a notebook

    One notebook by id, from the part of the tenant this hat covers.

    A notebook in a sibling branch answers `not_found`, exactly as one in
    another tenant does.
    """
    return {"id": notebook_id, "attachments": list(ZzzCanaryNotebook.attachments)}
