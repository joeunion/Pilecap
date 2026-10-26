# NEGATIVE (rule 38): a pydantic class that shares an org-scoped model's name is
# not a model, so its app owes `WidgetOut` nothing. Must stay silent.
from pydantic import BaseModel


class Widget(BaseModel):
    name: str
