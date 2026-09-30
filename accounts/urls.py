from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("submissions/", views.submission_list, name="submissions"),
    path("disputes/", views.my_disputes, name="my-disputes"),
    path("submit/dog/", views.submit_dog, name="submit-dog"),
    path("submit/kennel/", views.submit_kennel, name="submit-kennel"),
    path("pedigrees/", views.my_pedigrees, name="my-pedigrees"),
    path("pedigrees/<uuid:pk>/", views.member_pedigree_detail, name="member-pedigree"),
    path("pedigrees/<uuid:pk>/export.csv", views.member_pedigree_export, name="member-pedigree-export"),
    path("litters/", views.my_litters, name="my-litters"),
    path("litters/submit/", views.submit_litter, name="submit-litter"),
    path("litters/<uuid:pk>/edit/", views.edit_litter, name="edit-litter"),
    path("dogs/<uuid:pk>/correction/", views.submit_correction, name="submit-correction"),
    path("dogs/<uuid:pk>/photo/", views.submit_image, name="submit-image"),
    path("dogs/<uuid:pk>/document/", views.submit_document, name="submit-document"),
    path("dogs/<uuid:pk>/dispute/", views.open_dispute, name="open-dispute"),
    path("kennels/<uuid:pk>/claim/", views.claim_kennel, name="claim-kennel"),
    path("kennels/<uuid:pk>/edit/", views.edit_kennel, name="edit-kennel"),
    path("documents/", views.documents, name="documents"),
    path(
        "documents/<int:pk>/visibility/",
        views.request_document_visibility,
        name="document-visibility",
    ),
    path("notifications/", views.notifications, name="notifications"),
    path("moderation/", views.moderation_queue, name="moderation"),
    path("moderation/bulk/", views.bulk_moderation, name="bulk-moderation"),
    path("moderation/audit/", views.moderation_audit, name="moderation-audit"),
    path(
        "moderation/submissions/<uuid:pk>/<str:decision>/",
        views.review_submission,
        name="review-submission",
    ),
    path(
        "moderation/disputes/<uuid:pk>/<str:decision>/",
        views.review_dispute,
        name="review-dispute",
    ),
    path("moderation/merge-dogs/", views.merge_dogs_view, name="merge-dogs"),
    path("moderation/verify-dog/", views.verify_dog, name="verify-dog"),
]
