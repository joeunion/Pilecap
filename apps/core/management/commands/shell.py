"""`manage.py shell` is the shell door, and it binds the chain a door binds.

Django's stock `shell` is a plain Django command: it binds nothing, so a service
called at its prompt (or through `shell -c`) runs below no door. Every write
still lands, and whatever the service hands to `transaction.on_commit` — a
workflow start, which asks `core.context.child_of_current` for the chain —
fails inside the commit hook, where Django logs it and the caller sees success:
a tenant row with no identity-realm run behind it.

This command is the stock one with `core.management.BaseCommand` in front of
it, so the binding is that class's own — the same `execute` wrapper every
command here inherits, never a second copy of it: a fresh request id and
correlation chain, `actor_kind="system"`, `door="shell"`, `command="shell"`.
Everything else about the shell (`-c`, standard input, the interpreters, the
automatic imports) is Django's, unchanged.
"""

from __future__ import annotations

from django.core.management.commands import shell

from apps.core.management import BaseCommand


class Command(BaseCommand, shell.Command):
    """Django's interactive shell, run with the shell door's context bound."""
