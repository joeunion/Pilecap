

def _negative_pat_prose() -> str:
    """Names ZITADEL_PAT in prose, reads nothing.

    The docstrings in `apps/accounts/zitadel.py`, `config/settings/base.py` and
    `quality/checks/rule_27.py` all do exactly this — they have to, to explain the rule
    — so a check that fired on the word rather than on the AST node would fire
    on its own reasons.
    """
    setting = "the PAT setting"
    return f"{setting} is called ZITADEL_PAT and is read in one place"
