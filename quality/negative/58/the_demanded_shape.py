"""NEGATIVE (rule 58): the shape the rule is pushing a second consumer to.

A fifteenth app's socket door: the base subclassed, the pattern wrapped, every
group taken from the bridge's own builders. Must stay silent — a rule that
cannot be satisfied by the form it demands is a rule nobody can land.
"""

from typing import Any

from django.urls import path

from apps.realtime.bridge import tenant_group, user_group
from apps.realtime.consumers import TenantEventsConsumer
from apps.realtime.middleware import token_auth


class ExampleEventsConsumer(TenantEventsConsumer):
    async def connect(self) -> None:
        tenant: Any = self.scope["tenant"]
        user: Any = self.scope["user"]
        groups = [tenant_group(tenant.pk), user_group(user.pk)]
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()


websocket_urlpatterns = [
    path("ws/example/", token_auth(ExampleEventsConsumer.as_asgi()), name="example-events"),
]
