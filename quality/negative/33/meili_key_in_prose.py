

def _negative_meili_prose() -> str:
    """Names MEILI_MASTER_KEY and MEILI_URL in prose, reads neither.

    `apps/search/engine.py`, `config/settings/guards.py`, `.env.example` and
    `quality/checks.py` all do exactly this — they have to, to explain the fence
    — so a check that fired on the word rather than on the AST node would fire
    on its own reasons.
    """
    setting = "the search index's credential"
    return f"{setting} is called MEILI_MASTER_KEY and is read at MEILI_URL in one place"
