# NEGATIVE SUPPORT (rule 38): the read shapes of the two non-model namesakes,
# without `organization_id`.
from ninja import Schema


class WidgetOut(Schema):
    name: str


class HolderOut(Schema):
    name: str
