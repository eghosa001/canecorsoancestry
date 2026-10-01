from django.urls import path

from . import views

app_name = "registry"

urlpatterns = [
    path("dogs/", views.dog_search, name="dog-search"),
    path("dogs/suggestions/", views.dog_suggestions, name="dog-suggestions"),
    path("dogs/<slug:slug>/", views.dog_detail, name="dog-detail"),
    path("statistics/", views.pedigree_statistics, name="statistics"),
    path("kennels/", views.kennel_list, name="kennel-list"),
    path("kennels/<slug:slug>/", views.kennel_detail, name="kennel-detail"),
    path("litters/<uuid:pk>/", views.litter_detail, name="litter-detail"),
]
