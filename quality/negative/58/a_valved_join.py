

# NEGATIVE (rule 58): the valve with its sentence, on the flagged line's own
# comment block. A reason a person wrote down is the escape hatch; a silent one
# is not, and a bare marker is its own finding.
async def _negative_valved_join(self: Any, name: str) -> None:
    # rule-58: an operator's diagnostic subscribes to a name typed at a
    # management command that resolved the tenant first; no client reaches here.
    await self.channel_layer.group_add(name, self.channel_name)
