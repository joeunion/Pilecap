

def _negative_mail_prose() -> str:
    """Names django.core.mail and apps.core.mail in prose, imports neither.

    Every docstring in apps/comms does exactly this — the module docstring of
    `services.py` opens with it — so a check that fired on the words rather
    than on the import statement would fire on its own documentation.
    """
    mail = "django.core.mail"
    return f"{mail} and apps.core.mail are named here, not imported"
