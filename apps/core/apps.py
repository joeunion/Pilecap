import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from django.apps import AppConfig

#: Where a dev-only command is found, and the one sentence the image answers it with.
COMMANDS = "apps/core/management/commands/"
OUTSIDE_CHECKOUT = (
    "`manage.py {command}` runs in a checkout, never in the image: it reads the gate, which the "
    "image does not carry — docs/sdk/the-one-path.md is the road.\n"
)


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
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 4408,
        "91.docstring-tail": 11213,
        "91.module-tail": 4174,
        "91.narrative": 121,
    }
    #: The paths that read the gate (`quality/`): checkout-only, and `.dockerignore` drops each.
    DEV_ONLY: ClassVar[tuple[str, ...]] = (
        "apps/core/scaffold",
        f"{COMMANDS}declare.py",
        f"{COMMANDS}newapp.py",
        f"{COMMANDS}roads.py",
        f"{COMMANDS}scaffold.py",
    )

    @classmethod
    def refuse_outside_checkout(cls, argv: Sequence[str], root: Path) -> None:
        """Exit 2 with the one refusal when `argv` names a `DEV_ONLY` command the tree lacks."""
        if len(argv) < 2:
            return
        path = f"{COMMANDS}{argv[1]}.py"
        if path in cls.DEV_ONLY and not (root / path).is_file():
            sys.stderr.write(OUTSIDE_CHECKOUT.format(command=argv[1]))
            raise SystemExit(2)

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
