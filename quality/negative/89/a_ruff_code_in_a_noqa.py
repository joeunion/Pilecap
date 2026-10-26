

# Legal: a linter's code after `noqa:` is the linter's vocabulary, not a queue row.
class NegHandler:
    """A handler spelled the way the standard library spells it."""

    def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
        return None
