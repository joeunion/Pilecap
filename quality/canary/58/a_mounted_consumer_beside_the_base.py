

class _CanaryLooseConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc] # planted violation
    """CANARY (rule 58): the MOUNT half on its own — authenticated, and unrelated.

    Wrapped in `token_auth`, so the credential half is answered; written beside
    `TenantEventsConsumer` rather than under it, so it inherits none of the three
    refusals — no principal, no tenant, no self-named group — however carefully
    it was reviewed.
    """

    async def connect(self) -> None:
        await self.accept()


websocket_urlpatterns = [
    path("ws/canary/", token_auth(_CanaryLooseConsumer.as_asgi()), name="canary-events"),
]
