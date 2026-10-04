from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("verify-email/<uidb64>/<token>/", views.verify_email, name="verify-email"),
    path("resend-verification/", views.resend_verification, name="resend-verification"),
    path("submissions/", views.submission_list, name="submissions"),
    path(
        "submissions/<uuid:pk>/evidence/",
        views.submission_evidence_upload,
        name="submission-evidence-upload",
    ),
    path(
        "verification-evidence/<uuid:pk>/download/",
        views.submission_evidence_download,
        name="submission-evidence-download",
    ),
    path("payments/new/", views.new_payment, name="new-payment"),
    path("payments/paystack/callback/", views.paystack_callback, name="paystack-callback"),
    path("payments/paystack/webhook/", views.paystack_webhook, name="paystack-webhook"),
    path("payments/<uuid:pk>/", views.payment_detail, name="payment-detail"),
    path("payments/<uuid:pk>/dog/", views.payment_submit_dog, name="payment-submit-dog"),
    path("payments/<uuid:pk>/litter/", views.payment_submit_litter, name="payment-submit-litter"),
    path("payments/<uuid:pk>/puppy/", views.payment_submit_puppy, name="payment-submit-puppy"),
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
    path(
        "moderation/verification/",
        views.verification_dashboard,
        name="verification-dashboard",
    ),
    path(
        "moderation/verification/roles/",
        views.moderation_set_role,
        name="moderation-set-role",
    ),
    path(
        "moderation/verification/rules/<int:pk>/",
        views.verification_rule_update,
        name="verification-rule-update",
    ),
    path(
        "moderation/verification/record-lock/",
        views.moderation_record_lock,
        name="moderation-record-lock",
    ),
    path("moderation/bulk/", views.bulk_moderation, name="bulk-moderation"),
    path("moderation/audit/", views.moderation_audit, name="moderation-audit"),
    path("moderation/data-health/", views.data_health, name="data-health"),
    path(
        "moderation/submissions/<uuid:pk>/",
        views.moderation_submission_detail,
        name="moderation-submission",
    ),
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
