from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("submissions/", views.submission_list, name="submissions"),
    path("submit/dog/", views.submit_dog, name="submit-dog"),
    path("dogs/<uuid:pk>/correction/", views.submit_correction, name="submit-correction"),
    path("dogs/<uuid:pk>/photo/", views.submit_image, name="submit-image"),
    path("dogs/<uuid:pk>/document/", views.submit_document, name="submit-document"),
    path("kennels/<uuid:pk>/edit/", views.edit_kennel, name="edit-kennel"),
    path("documents/", views.documents, name="documents"),
    path("notifications/", views.notifications, name="notifications"),
    path("moderation/", views.moderation_queue, name="moderation"),
    path(
        "moderation/submissions/<uuid:pk>/<str:decision>/",
        views.review_submission,
        name="review-submission",
    ),
    path("moderation/merge-dogs/", views.merge_dogs_view, name="merge-dogs"),
    path("moderation/verify-dog/", views.verify_dog, name="verify-dog"),
]
