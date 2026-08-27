from typing import ClassVar

from django.apps import AppConfig


class ExampleConfig(AppConfig):
    """The worked example. A product deletes this app once it has its own."""

    name = "apps.example"
    verbose_name = "Example"
    # The one app in this template a deployment may leave OUT, and it says so
    # itself — `config/settings/discovery.py` reads this attribute and nothing
    # anywhere holds a list of what is skippable. A product that has its own
    # domain app sets `DJB_DISABLED_APPS=example` and stops shipping the worked
    # example to production while keeping it in the tree to read; before this,
    # the only way out was to delete the directory. Everything else is
    # non-optional by omission, which is why `DJB_DISABLED_APPS=core` is refused
    # by name rather than honoured.
    optional: ClassVar[bool] = True
    # What this app may import (house rule 7). `workflows` is here because
    # `create_widget` starts a durable run; `events` deliberately is **not** —
    # the app says what happened through the `core.bridge` registry rather than
    # by importing an app that may not be installed. A registry lookup is not an
    # import, and that is the whole point of the bridge.
    # `search` joined the day this app adopted `Searchable` (R-e): `search.py`
    # imports `apps.search.types.Searchable` to spell its declaration, which is
    # the ONE import adopting costs — a value type, no engine, no client. The
    # traffic still runs the other way: `apps.search` discovers this app's
    # `search.py` and consumes its events off the spine, and nothing here
    # imports the spine or the engine (`events` is deliberately absent below for
    # exactly that reason). A declared sideways dependency a reviewer can see is
    # the point of rule 7; the alternative was a magic string naming a model.
    depends_on: tuple[str, ...] = ("core", "accounts", "workflows", "search")
