

async def _neg_temporal_connect(address):
    # Client.connect is Temporal's client factory, not a Django signal.
    return await Client.connect(address)
