

from django.http import Http404


def _canary_lookup():
    raise Http404("planted")
