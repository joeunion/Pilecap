

# NEGATIVE (rule 36): the kick — a group_send to user_group carrying an
# instruction to hang up, never a payload. Must stay silent (M4 §8's second
# proposed negative).
async def _negative_kick(user_id, reason):
    await _layer().group_send(
        user_group(user_id),
        {"type": KICK_TYPE, "reason": reason},
    )
