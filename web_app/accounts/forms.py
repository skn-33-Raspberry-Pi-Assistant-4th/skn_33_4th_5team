"""Signup form built on Django's default User model and password validators."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        label="이메일",
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email", "placeholder": "name@example.com"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")
        error_messages = {"username": {"unique": "이미 사용 중인 아이디입니다."}}
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "autocomplete": "username", "placeholder": "아이디"}),
        }

    def __init__(self, *args, **kwargs):
        """Apply PiCare styling and Korean guidance to Django's built-in fields."""
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": "form-control", "autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"class": "form-control", "autocomplete": "new-password"})
        self.fields["username"].help_text = "영문, 숫자 및 @/./+/-/_를 사용할 수 있습니다."

    def clean_email(self) -> str:
        """Normalize email case and reject an address already held by another User."""
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("이미 가입된 이메일입니다.")
        return email
