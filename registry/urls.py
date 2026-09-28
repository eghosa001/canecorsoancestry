from django.urls import path

from . import views

app_name = "registry"

urlpatterns = [
    path("dogs/", views.dog_search, name="dog-search"),
    path("dogs/<slug:slug>/", views.dog_detail, name="dog-detail"),
]
