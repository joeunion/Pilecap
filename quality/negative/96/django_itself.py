from django.db import transaction


# Legal: Django, the stdlib and third-party packages are no platform app.
def atomically() -> object:
    return transaction.atomic
