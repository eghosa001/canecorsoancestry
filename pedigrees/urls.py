from django.urls import path

from . import views

app_name = "pedigrees"

urlpatterns = [
    path("", views.pedigree_index, name="index"),
    path("virtual-mating/", views.virtual_mating, name="virtual-mating"),
    path("<slug:slug>/", views.pedigree_detail, name="detail"),
]
