# ADR platform-lifecycle-2

**ADR platform-lifecycle-2 · one mechanism, one rung, two apps.**
*Context*: the fix changes the `SCHEDULES` seam in `apps/workflows` (which owns the
engine) and in `apps/events` (which is its only other declaring client), and the
schema discipline's default is one app per rung. *Decision*: the exception is
taken deliberately and recorded here — it is **one mechanism**, `apps.workflows`
owns it and `apps.events` is its declaring client, and the two halves are a
single seam whose two sides cannot be typed independently (the shape lives in
`apps/core/schedules.py`, below both, because `import-linter` holds the platform
apps independent of one another). Migrations: zero, so the collision the
discipline exists to prevent is not in play. *Rejected*: **two rungs**, which
would carry the declaration shape in prose across the gap between them and land
a tree in which one app declares against a seam the other has not built yet.
trigger to revisit: a third schedule-declaring app — at which point the seam is
established vocabulary and a change to it is an ordinary one-app rung.
