# Two gotchas

The long form of `django-conventions`' closing section.

## Two gotchas, at the site they bite

**A ninja `resolve_` hook dies inside a `Page`.** A resolver is consulted
before attribute access on whatever object is being validated — re-validating
an `Out` as an item of a `Page` hands the resolver the wrong object and it
finds nothing: it works at the HTTP door and fails at the machine one. Wrong
form: `resolve_event_name` on the schema. Right form: a model `@property` —
found by both doors, no resolver timing.

**mypy narrows a subscripted expression across statements.** After
`assert x[-1]["verified"] is False`, every later read of that same expression
is `Literal[False]` and `--strict` marks the rest of the test `[unreachable]`.
Right form: read through a small function (`verified(receiver)`) — narrowing
cannot see through a call.
