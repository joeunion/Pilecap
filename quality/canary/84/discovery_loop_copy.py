

# Planted: a private discovery walk — the app registry read for a module of the
# walker's own. The one walk is `core.discovery.declared`; this is a copy by FORM,
# and rule 84 counts it past the recorded ratchet.
def canary_discover_frobs() -> list[str]:
    """Every installed app that ships a `frobs` module."""
    import importlib.util

    from django.apps import apps as django_apps

    found = []
    for config in django_apps.get_app_configs():
        if importlib.util.find_spec(f"{config.name}.frobs") is not None:
            found.append(config.name)
    return found
