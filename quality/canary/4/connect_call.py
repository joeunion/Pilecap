

from django.db.models.signals import post_delete as _canary_post_delete


def _canary_wire_up():
    _canary_post_delete.connect(lambda **kw: None)
