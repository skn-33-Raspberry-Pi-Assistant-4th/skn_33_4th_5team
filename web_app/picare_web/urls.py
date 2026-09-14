"""Top-level routes for the PiCare Django UI."""

from django.urls import include, path


urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("", include("portal.urls")),
]
