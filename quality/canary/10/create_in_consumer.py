

def _canary_create_in_consumer(tenant, payload):  # planted violation (rule 10)
    return Widget.objects.create(tenant=tenant, **payload)
