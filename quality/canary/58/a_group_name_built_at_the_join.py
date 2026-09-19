

# CANARY (rule 58): the JOIN half on its own, in the app the seam lives in — a
# correctly mounted consumer whose handler subscribes to a name it built itself.
# Closing only the mount half would leave this: a valid credential, a group name
# the caller chose, somebody else's tenant.
async def _canary_join_a_name_of_its_own(self: Any, requested: str) -> None:  # planted violation
    await self.channel_layer.group_add(f"tenant.{requested}", self.channel_name)
