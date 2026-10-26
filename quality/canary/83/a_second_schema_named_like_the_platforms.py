# Planted: a second app answering its own schema class under the platform's
# schema name. django-ninja publishes one component per class name and neither
# raises nor mangles on a second: the class discovered last describes every
# route of both apps, so the platform's notes routes are documented with this
# shape (or this route with theirs), and nothing 500s.
#
# Planted on a real module beside its siblings; the import is aliased so no
# name of the module it lands in is rebound.

from ninja import Field as _Field83
from ninja import Schema as _Schema83

from apps.core.schemas import example as _example83


class DjbNoteOut(_Schema83):
    body: str = _Field83(json_schema_extra=_example83("a probe's note"))
    stars: int = _Field83(json_schema_extra=_example83(3))


@router.get("/zzz-canary-noted/{note_id}/", response=DjbNoteOut, url_name="zzz_canary_noted-detail")
def zzz_canary_noted_detail(request, note_id: str):
    """Retrieve a second note

    Planted by the quality gate's self-test. It exists for the length of one run.
    """
    return {"body": "a probe's note", "stars": 3}
