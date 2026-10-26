#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Could not import Django. Are you sure it is installed and available on your "
            "PYTHONPATH environment variable? Did you forget to activate a virtual environment?"
        ) from exc
    from apps.core.apps import CoreConfig

    CoreConfig.refuse_outside_checkout(sys.argv, Path(__file__).resolve().parent)
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
