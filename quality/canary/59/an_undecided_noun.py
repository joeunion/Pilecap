

# CANARY (rule 59, class undecided_noun): an app declares an event name
# whose noun is neither an authorization kind nor a key of its own
# `EVENT_KINDS`. Since the amendment the owner signed 2026-09-21, `emit()` no
# longer refuses this: the write commits, the row is written, and
# `consumers._may_read` drops every frame of it — so the event is announced to
# NOBODY, silently and forever. This class is the only thing in the tree that
# notices, and its finding carries the `EVENT_KINDS` line to paste.
GIZMO_POLISHED = "example.gizmo.polished"  # planted violation
