"""A PRODUCT's root URL configuration, with its own landing page.

Not a test module: the thing `test_welcome.py` points the resolver at to prove
that `/welcome/` is SHADOWED rather than configured. It is what a product's
`config/urls.py` looks like after it mounts a landing page of its own — its
route first, the platform's list after — and the property under test is that
the product's view is the one that answers, with nothing deleted, nothing
overridden and no setting touched.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.urls import path

from config.urls import urlpatterns as platform_urlpatterns

PRODUCT_BODY = "the product's own landing page"


def product_welcome(request: HttpRequest) -> HttpResponse:
    return HttpResponse(PRODUCT_BODY)


urlpatterns = [
    path("welcome/", product_welcome, name="welcome"),
    *platform_urlpatterns,
]
