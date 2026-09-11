from django.urls import path

from . import views


urlpatterns = [
    path("", views.about, name="about"),
    path("recommend/", views.recommend, name="recommend"),
    path("qa/", views.qa, name="qa"),
    path("health/", views.health, name="health"),
]
