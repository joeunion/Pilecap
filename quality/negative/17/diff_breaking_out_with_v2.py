"""Planted: WidgetOut with its published fields torn off (and one re-typed)."""

from uuid import UUID

from ninja import Schema


class WidgetOut(Schema):
    id: UUID
    notes: int
