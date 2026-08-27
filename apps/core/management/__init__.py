"""The shell door.

A management command is a door like any other: it calls services, it acts as
somebody, and what it did has to be answerable months later. `BaseCommand` here
is the one that binds the context (house rule 20) so that a command's audit
rows and log lines carry `door="shell"` and a correlation id, instead of
arriving with every ambient field blank.

    from apps.core.management import BaseCommand

    class Command(BaseCommand):
        def handle(self, *args, **options): ...

Django's own `BaseCommand` is the base of this one, so nothing else about
writing a command changes.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand as DjangoBaseCommand

from apps.core import context

__all__ = ["BaseCommand"]


class BaseCommand(DjangoBaseCommand):
    """A management command with the ambient context bound around `handle`.

    The binding is in `execute` rather than in `handle`, so a subclass cannot
    forget it by overriding the method it was told to override. `door="shell"`
    and `actor_kind="system"` are the truth about a command: it has a shell, not
    a session, and it acts as the machine unless a service is handed an actor.
    """

    def execute(self, *args: Any, **options: Any) -> Any:
        with context.bound(
            request_id=context.new_id(),
            correlation_id=context.new_correlation_id(),
            actor_kind="system",
            door="shell",
            command=self.__class__.__module__.rsplit(".", 1)[-1],
        ):
            return super().execute(*args, **options)
