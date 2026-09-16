"""Top-level routes for the PiCare Django UI."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    # Legacy feature templates reverse the global ``login`` name. Keep only a
    # query-preserving redirect here; authentication itself stays in accounts.
    path(
        "login/",
        RedirectView.as_view(pattern_name="accounts:login", permanent=False, query_string=True),
        name="login",
    ),
    path("", include("portal.urls")),
]
