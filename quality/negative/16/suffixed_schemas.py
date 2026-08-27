

# Negatives: all five suffixes, including one that inherits another schema.
class GizmoIn(Schema):
    name: str


class GizmoOut(Schema):
    id: str


class GizmoIssuedOut(GizmoOut):
    issued_at: str


class GizmoPatch(Schema):
    name: str | None = None


class GizmoFilter(FilterSchema):
    name: str | None = None


class GizmoPage(Schema):
    count: int
