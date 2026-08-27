

def _neg_overridden_read():
    # rule-8: a deliberate cross-tenant maintenance read, proven in its own test
    return Widget.objects.filter(name="x")
