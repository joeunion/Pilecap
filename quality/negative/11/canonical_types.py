"""Negative: types.py is canonical."""

from dataclasses import dataclass


@dataclass
class CanaryPayload:
    key: str
