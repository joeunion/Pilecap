

def _neg_unscoped_read():
    return Membership.objects.filter(pk=None).exists()
