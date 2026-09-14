from django.urls import path

from . import views


urlpatterns = [
    path("", views.about, name="about"),
    path("recommend/", views.recommend, name="recommend"),
    path("qa/", views.qa, name="qa"),
    path("questions/", views.questions, name="questions"),
    path("questions/<int:question_id>/", views.question_detail, name="question_detail"),
    path("lab/", views.lab, name="lab"),
    path("challenge/", views.challenge, name="challenge"),
    path("api/qa/mini-challenge/submit", views.inline_challenge_submit_api, name="inline_challenge_submit_api"),
    path("api/lab/templates", views.lab_templates_api, name="lab_templates_api"),
    path("api/lab/analyze", views.lab_analyze_api, name="lab_analyze_api"),
    path("api/lab/compose", views.lab_compose_api, name="lab_compose_api"),
    path("health/", views.health, name="health"),
]
