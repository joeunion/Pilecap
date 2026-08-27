

# Out of the population by construction: a plain helper in services.py is not a
# `@service`, so it is not a capability and has no door to be missing. Reading
# it as one would make every private function in the tree a finding.


def _next_widget_note(widget: Widget) -> str:
    """A private helper. Rule 13 is what keeps a WRITE from hiding in one."""
    return widget.notes.strip()
