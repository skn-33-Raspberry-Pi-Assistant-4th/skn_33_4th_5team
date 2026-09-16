"""Signup, login and logout views for the server-side PiCare account flow."""

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .forms import SignupForm


def _safe_next(request, candidate: str | None) -> str:
    """Return an on-site redirect target and reject an external ``next`` URL."""
    if candidate and url_has_allowed_host_and_scheme(candidate, {request.get_host()}, request.is_secure()):
        return candidate
    return reverse("about")


@require_http_methods(["GET", "POST"])
def signup(request):
    """Create Django's default User, log the new member in, and redirect safely."""
    if request.user.is_authenticated:
        return redirect("about")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "회원가입이 완료되었습니다. PiCare에 오신 것을 환영합니다.")
        return redirect(_safe_next(request, request.POST.get("next")))
    return render(request, "accounts/signup.html", {"form": form, "active_page": "accounts", "next": request.GET.get("next", "")})


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Authenticate a member with Django's form and create a DB-backed session."""
    if request.user.is_authenticated:
        return redirect("about")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "로그인했습니다.")
        return redirect(_safe_next(request, request.POST.get("next")))
    return render(request, "accounts/login.html", {"form": form, "active_page": "accounts", "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    """End the current authenticated session through a CSRF-protected POST."""
    logout(request)
    messages.success(request, "로그아웃했습니다.")
    return redirect("about")
