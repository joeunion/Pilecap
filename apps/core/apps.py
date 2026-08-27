from django.apps import AppConfig


class CoreConfig(AppConfig):
    """The foundation: the base model, tenancy, and the request middleware.

    `depends_on` is the app's own declaration of what it may import. `core`
    declares nothing, because `core` imports nothing above it — that is the
    whole of its contract. `config/settings/discovery.py` reads this attribute
    when it derives `INSTALLED_APPS`; house rule 7 reads it at gate time and
    refuses an import outside it.
    """

    name = "apps.core"
    verbose_name = "Core"
    depends_on: tuple[str, ...] = ()

    def ready(self) -> None:
        """Install logging and tracing, once, for whatever started this process.

        `manage.py`, the ASGI server, the Temporal worker and pytest all reach
        `ready()`; none of them has to remember to call anything, which is the
        point — an entrypoint that forgot would log unstructured lines that
        never reach the sink and nobody would notice until the incident.

        Imported here rather than at module scope because `apps.py` is read by
        `config.settings.discovery` before Django exists.

        `audit` and `idempotency` are imported for their side effect: their
        models live in their own modules rather than in `models.py`, because
        they are mechanisms and not domain nouns, and a model is only registered
        once something imports it. `models.py` cannot do the importing — both
        inherit from it — so the app config does.
        """
        # The house-rule system checks (`manage.py check --tag djb`) register on
        # import; this is the one hook that runs in every process.
        from apps.core import (  # noqa: F401
            audit,
            checks,  # noqa: F401
            idempotency,
        )
        from apps.core.observability import configure

        configure()
