"""Top-level routes for the PiCare Django UI."""

from django.urls import include, path


urlpatterns = [
    path("", include("portal.urls")),
]
