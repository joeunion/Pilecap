"""CANARY (rule 58): R4's F1 plant, verbatim — the fifteenth app's consumer.

A consumer that names its own group from the query string and accepts with no
credential, mounted bare in `websocket_urlpatterns`. `config/asgi.py` discovers
it exactly as it discovers the real one, so this is an anonymous cross-tenant
door that the gate answered with one marker line in a test file before this rule
existed. Two findings, one per class, from one planted file.
"""

from typing import Any
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.urls import path


class ExampleEventsConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc] # planted violation
    async def connect(self) -> None:
        query: Any = parse_qs(self.scope["query_string"].decode())
        await self.channel_layer.group_add(f"tenant.{query['tenant'][0]}", self.channel_name)
        await self.accept()


websocket_urlpatterns = [
    path("ws/example/", ExampleEventsConsumer.as_asgi(), name="example-events"),
]
