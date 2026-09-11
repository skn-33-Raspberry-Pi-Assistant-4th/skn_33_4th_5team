"""Django form boundaries for existing PiCare service inputs."""

from django import forms

from src.contracts.input_limits import INPUT_LENGTH_HINT, MAX_INPUT_CHARS, validate_input_text


OPTIONAL_BOOLEAN_CHOICES = (("", "선택 안 함"), ("true", "예"), ("false", "아니요"))


class RecommendationForm(forms.Form):
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
        try:
            return validate_input_text(self.cleaned_data["purpose"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    @staticmethod
    def as_optional_boolean(value: str) -> bool | None:
        return {"": None, "true": True, "false": False}[value]


class QuestionForm(forms.Form):
    question = forms.CharField(
        label="질문",
        max_length=MAX_INPUT_CHARS,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "질문을 입력하세요"}),
        help_text=INPUT_LENGTH_HINT,
    )

    def clean_question(self) -> str:
        try:
            return validate_input_text(self.cleaned_data["question"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class CommandInputForm(forms.Form):
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
