from apps.zzz_canary.models import Thing


# Legal: an app imports its own modules.
def first() -> object:
    return Thing
