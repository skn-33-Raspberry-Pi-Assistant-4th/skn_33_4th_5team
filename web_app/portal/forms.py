"""Django form boundaries for existing PiCare service inputs."""

from django import forms
from django.contrib.auth.models import User

from src.contracts.input_limits import INPUT_LENGTH_HINT, MAX_INPUT_CHARS, validate_input_text

from .models import Comment, Post


OPTIONAL_BOOLEAN_CHOICES = (("", "선택 안 함"), ("true", "예"), ("false", "아니요"))
POST_CONTENT_MAX_LENGTH = 10_000
COMMENT_CONTENT_MAX_LENGTH = 2_000


class ProfileUpdateForm(forms.ModelForm):
    """로그인한 사용자가 수정할 수 있는 기본 정보만 노출한다."""

    class Meta:
        model = User
        fields = ("username", "email")
        labels = {"username": "사용자명", "email": "이메일"}
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }

    def clean_email(self) -> str:
        """Normalize email and reject an address held by another user."""
        email = self.cleaned_data["email"].strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("이미 가입된 이메일입니다.")
        return email


class PostForm(forms.ModelForm):
    """게시글의 사용자 입력 필드만 노출한다."""

    title = forms.CharField(
        label="제목",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "제목을 입력하세요"}),
    )
    content = forms.CharField(
        label="내용",
        max_length=POST_CONTENT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "내용을 입력하세요"}),
    )

    class Meta:
        model = Post
        fields = ("title", "content")


class CommentForm(forms.ModelForm):
    """댓글의 사용자 입력 필드만 노출한다."""

    content = forms.CharField(
        label="댓글",
        max_length=COMMENT_CONTENT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "댓글을 입력하세요"}),
    )

    class Meta:
        model = Comment
        fields = ("content",)


class CommandAnalyzeForm(forms.Form):
    """Display-only command analysis input; service validation remains authoritative."""

    command = forms.CharField(
        label="명령어 분석",
        max_length=2000,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "예: ssh pi@raspberrypi.local",
                "autocomplete": "off",
            }
        ),
    )


class RecommendationForm(forms.Form):
    """제품 추천에 필요한 사용 목적과 선택 조건을 입력받는다."""

    purpose = forms.CharField(
        label="어디에 사용하실 건가요?",
        max_length=MAX_INPUT_CHARS,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "예: 모니터 없이 홈 서버로 사용하고 싶어요.",
            }
        ),
        help_text=INPUT_LENGTH_HINT,
    )
    user_level = forms.ChoiceField(
        label="사용자 수준",
        choices=(("선택 안 함", "선택 안 함"), ("입문자", "입문자"), ("중급자", "중급자"), ("고급자", "고급자")),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    performance = forms.ChoiceField(
        label="성능 우선순위",
        choices=(("선택 안 함", "선택 안 함"), ("낮음", "낮음"), ("보통", "보통"), ("높음", "높음")),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    wifi = forms.ChoiceField(label="Wi‑Fi 필요", choices=OPTIONAL_BOOLEAN_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-select"}))
    camera = forms.ChoiceField(label="카메라 사용", choices=OPTIONAL_BOOLEAN_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-select"}))
    gpio = forms.ChoiceField(label="GPIO 사용", choices=OPTIONAL_BOOLEAN_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-select"}))
    monitor_absent = forms.ChoiceField(label="모니터 없음", choices=OPTIONAL_BOOLEAN_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-select"}))

    def clean_purpose(self) -> str:
        """Apply the shared input-length and whitespace policy to a purpose."""
        try:
            return validate_input_text(self.cleaned_data["purpose"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    @staticmethod
    def as_optional_boolean(value: str) -> bool | None:
        """Translate the HTML select value into the domain contract's tri-state boolean."""
        return {"": None, "true": True, "false": False}[value]


class QuestionForm(forms.Form):
    """RAG Q&A에 전달할 사용자 질문을 입력받고 검증한다."""

    question = forms.CharField(
        label="질문",
        max_length=MAX_INPUT_CHARS,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "질문을 입력하세요"}),
        help_text=INPUT_LENGTH_HINT,
    )

    def clean_question(self) -> str:
        """Apply the same shared text policy used by the grounded Q&A service."""
        try:
            return validate_input_text(self.cleaned_data["question"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class CommandInputForm(forms.Form):
    """명령어 실험실에서 분석할 단일 명령어를 입력받는다."""

    command = forms.CharField(
        label="한 줄 명령어",
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 2,
                "placeholder": "예: ssh learner@raspberrypi.local",
            }
        ),
        help_text="검수 완료된 예시와 일치하는 명령어만 분석합니다. 실제 실행은 하지 않습니다.",
    )
