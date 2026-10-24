"""Full QA browser journeys over strictly disposable Django data.

Runs once per browser in independent GitHub-hosted runners. Each scenario
creates its own browser context and records JUnit, screenshots and traces.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import html
import json
import os
import re
import traceback
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import django
django.setup()

from django.contrib.auth import get_user_model
from registry.models import Dog, Submission
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
CREDS = json.loads(Path("/tmp/cca-playwright-audit-credentials.json").read_text())
OUT = Path(os.environ.get("CCA_QA_REPORT_ROOT", "artifacts/full-qa"))
OUT.mkdir(parents=True, exist_ok=True)
MAIL = Path(os.environ["CCA_QA_MAIL_ROOT"])
results = []


def db_call(action):
    # Playwright sync API executes in a greenlet with an active event loop.
    # Run Django ORM queries in a separate ordinary worker thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(action).result()


def go(page, url, status=200):
    response = page.goto(BASE + url, wait_until="domcontentloaded")
    assert response is not None, f"No HTTP response from {url}"
    assert response.status == status, f"{url}: HTTP {response.status}, expected {status}"
    return response


def submit_form_containing(page, field):
    # Never select the hidden global search button ahead of a content form.
    page.locator(field).locator("xpath=ancestor::form").locator("button[type=submit]").first.click()


def sign_in(page, role):
    go(page, "/accounts/login/")
    user = CREDS["roles"][role]
    page.locator("#id_username").fill(user["email"])
    page.locator("#id_password").fill(user["password"])
    submit_form_containing(page, "#id_username")
    page.wait_for_url(lambda url: "/accounts/login/" not in str(url), wait_until="domcontentloaded", timeout=10000)
    assert "/accounts/login/" not in page.url, f"Login failed for {role}: {page.url}"


def latest_email(previous, needle):
    fresh = sorted(set(MAIL.glob("*")) - previous, key=lambda p: p.stat().st_mtime_ns)
    matching = [p.read_text(errors="replace") for p in fresh if needle in p.read_text(errors="replace")]
    assert matching, f"No isolated test email received for {needle}"
    return matching[-1]


def test_visitor(page):
    for width in (375, 430, 834, 1366):
        page.set_viewport_size({"width": width, "height": 900})
        for path in ("/", "/dogs/", "/kennels/", "/pedigrees/", "/statistics/",
                     "/pedigrees/virtual-mating/", "/accounts/login/", "/member/signup/"):
            go(page, path)
            assert page.locator("main").count(), f"No main region at {path}"
            extra = page.evaluate("document.documentElement.scrollWidth - innerWidth")
            assert extra <= 5, f"Unintended {extra}px overflow at {path} width={width}"
    go(page, "/dogs/browser-audit-offspring/")
    assert "Browser Audit Offspring" in page.locator("main").inner_text()
    go(page, "/dogs/?q=Browser+Audit+Private")
    assert not any("Browser Audit Private" in card for card in page.locator(".search-result-card").all_inner_texts()), "Unpublished dog leaked in search result cards"
    page.screenshot(path=OUT / "visitor-desktop.png", full_page=True)


def test_account_email_lifecycle(page):
    new_email = f"cca.qa.signup.{uuid.uuid4().hex[:10]}@example.test"
    password = "Qa-safeguarded-password-2026!"
    go(page, "/member/signup/")
    before = set(MAIL.glob("*"))
    page.locator("#id_email").fill(new_email)
    page.locator("#id_password1").fill(password)
    page.locator("#id_password2").fill(password)
    submit_form_containing(page, "#id_email")
    page.wait_for_load_state("domcontentloaded")
    email_body = latest_email(before, new_email)
    link = re.search(r"/member/verify-email/[^\s]+/[^\s]+/", email_body)
    assert link, "Verification email missing usable activation route"
    user = db_call(lambda: get_user_model().objects.get(email=new_email))
    assert not user.is_active, "New account bypassed required email verification"
    go(page, urlparse(BASE + link.group(0)).path)
    assert db_call(lambda: get_user_model().objects.get(pk=user.pk).is_active), "Activation link did not activate the account"
    assert "/dashboard/" in page.url, "Activation did not authenticate/redirect"
    go(page, link.group(0), status=400)
    go(page, "/accounts/password_reset/")
    before = set(MAIL.glob("*"))
    page.locator("#id_email").fill(new_email)
    submit_form_containing(page, "#id_email")
    page.wait_for_load_state("domcontentloaded")
    reset_email = latest_email(before, new_email)
    match = re.search(r"/accounts/reset/[^\s]+/[^\s]+/", reset_email)
    assert match, "Password reset email missing recovery link"
    go(page, match.group(0))
    assert "reset" in page.url, "Password reset link was not recognized"


def test_member_draft_with_photo(page):
    sign_in(page, "member")
    go(page, "/member/submit/dog/")
    name = "QA Private Draft " + uuid.uuid4().hex[:8]
    page.locator("#id_name").fill(name)
    page.locator("#id_sex").select_option("male")
    page.locator("#id_kennel").select_option(CREDS["kennel_id"])
    page.locator("#id_colour").fill("Brindle")
    page.locator("#id_primary_photo").set_input_files(CREDS["fixtures"]["dog-landscape.jpg"])
    page.get_by_role("button", name="Save dog privately").click()
    page.wait_for_url("**/member/submissions/", wait_until="domcontentloaded", timeout=10000)
    assert "/member/submissions/" in page.url, "Draft was not saved to member submissions"
    record = db_call(lambda: Submission.objects.get(submitted_by_id=CREDS["roles"]["member"]["id"],
                                    kind=Submission.Kind.DOG, payload__name=name))
    assert record.attachment, "Draft image was not stored"
    assert record.status == Submission.Status.PENDING, "Draft skipped payment/moderation"
    assert not db_call(lambda: Dog.objects.filter(name=name).exists()), "Unpaid dog published as a canonical dog"
    page.reload(wait_until="domcontentloaded")
    assert name in page.locator("main").inner_text(), "Draft not visible after reload"


def test_invalid_member_draft(page):
    sign_in(page, "member")
    go(page, "/member/submit/dog/")
    page.locator("#id_sex").select_option("female")
    page.locator("#id_kennel").select_option(CREDS["kennel_id"])
    page.get_by_role("button", name="Save dog privately").click()
    assert "/member/submit/dog/" in page.url, "Invalid submission unexpectedly completed"
    assert (page.locator(".field-error").count() > 0 or
            not page.locator("#id_name").evaluate("(el) => el.checkValidity()")), "Required name was neither rejected by HTML validation nor the server"


def test_member_photo_review_and_corrupt_image(page):
    sign_in(page, "member")
    dog_id = CREDS["dog_id"]
    go(page, f"/member/dogs/{dog_id}/photo/")
    page.locator("#id_attachment").set_input_files(CREDS["fixtures"]["invalid-image.jpg"])
    submit_form_containing(page, "#id_attachment")
    assert page.locator(".field-error").count() > 0, "Fake JPEG accepted"
    go(page, f"/member/dogs/{dog_id}/photo/")
    caption = "QA image " + uuid.uuid4().hex[:8]
    page.locator("#id_attachment").set_input_files(CREDS["fixtures"]["dog-portrait.png"])
    page.locator("#id_caption").fill(caption)
    submit_form_containing(page, "#id_attachment")
    page.wait_for_url("**/member/submissions/", wait_until="domcontentloaded", timeout=10000)
    assert "/member/submissions/" in page.url, "Photo did not enter review queue"
    evidence = db_call(lambda: Submission.objects.filter(
        dog_id=dog_id, kind=Submission.Kind.IMAGE,
        submitted_by_id=CREDS["roles"]["member"]["id"], payload__caption=caption
    ).first())
    assert evidence and evidence.attachment, "Photo upload lacks persisted review evidence"
    assert evidence.status == Submission.Status.PENDING, "Photo was published without review"



def test_document_evidence_upload(page):
    sign_in(page, "member")
    go(page, f"/member/dogs/{CREDS['dog_id']}/document/")
    title = "QA pedigree certificate " + uuid.uuid4().hex[:8]
    page.locator("#id_title").fill(title)
    page.locator("#id_attachment").set_input_files(CREDS["fixtures"]["evidence.pdf"])
    submit_form_containing(page, "#id_attachment")
    page.wait_for_url("**/member/submissions/", wait_until="domcontentloaded", timeout=10000)
    assert "/member/submissions/" in page.url, "Certificate not added to review"
    record = db_call(lambda: Submission.objects.filter(
        submitted_by_id=CREDS["roles"]["member"]["id"],
        dog_id=CREDS["dog_id"], kind=Submission.Kind.DOCUMENT, payload__title=title,
    ).first())
    assert record and record.attachment, "Certificate missing from persisted evidence"
    assert record.status == Submission.Status.PENDING, "Certificate bypassed moderation"


def test_member_correction_review(page):
    sign_in(page, "member")
    dog_id = CREDS["dog_id"]
    before = db_call(lambda: Dog.objects.get(pk=dog_id).colour)
    go(page, f"/member/dogs/{dog_id}/correction/")
    proposed = "QA Brindle " + uuid.uuid4().hex[:7]
    page.locator("#id_colour").fill(proposed)
    page.locator("#id_notes").fill("Test-only colour proposal to verify pending review.")
    submit_form_containing(page, "#id_colour")
    page.wait_for_url("**/member/submissions/", wait_until="domcontentloaded", timeout=10000)
    assert "/member/submissions/" in page.url, "Correction not queued"
    record = db_call(lambda: Submission.objects.filter(
        submitted_by_id=CREDS["roles"]["member"]["id"], dog_id=dog_id,
        kind=Submission.Kind.CORRECTION, payload__colour=proposed
    ).first())
    assert record and record.status == Submission.Status.PENDING, "Correction not pending"
    after = db_call(lambda: Dog.objects.get(pk=dog_id).colour)
    assert after == before, "Unreviewed correction modified the canonical dog"


def test_authenticated_pedigree_and_virtual_mating(page):
    sign_in(page, "member")
    go(page, "/pedigrees/browser-audit-offspring/?generations=5")
    assert "Browser Audit Offspring" in page.locator("main").inner_text()
    response = page.request.get(BASE + "/pedigrees/browser-audit-offspring/export.csv?generations=5")
    assert response.status == 200, "Pedigree export failed for logged-in member"
    assert "text/csv" in response.headers.get("content-type", ""), "Pedigree CSV uses wrong media type"
    assert "Browser Audit Offspring" in response.text(), "Export does not contain requested dog"
    dam = db_call(lambda: str(Dog.objects.get(slug="browser-audit-dam").pk))
    go(page, f"/pedigrees/virtual-mating/?sire={CREDS['dog_id']}&dam={dam}&generations=5")
    assert "Browser Audit Sire" in page.locator("main").inner_text()
    assert "Browser Audit Dam" in page.locator("main").inner_text()


def test_moderator_creates_private_canonical_dog(page):
    sign_in(page, "moderator")
    go(page, "/member/moderation/dogs/add/")
    name = "QA Moderator New Dog " + uuid.uuid4().hex[:7]
    page.locator("#id_name").fill(name)
    page.locator("#id_sex").select_option("female")
    page.locator("#id_reason").fill("Test-only audited canonical creation with photograph.")
    page.locator("#id_primary_photo").set_input_files(CREDS["fixtures"]["dog-landscape.jpg"])
    submit_form_containing(page, "#id_name")
    page.wait_for_load_state("domcontentloaded")
    dog = db_call(lambda: Dog.objects.filter(name=name).first())
    assert dog is not None, "Moderator new dog was not saved"
    assert not dog.is_public, "Moderator-created canonical dog published without review"
    assert db_call(lambda: dog.images.count()) > 0, "Moderator dog image did not persist"
    assert "/member/moderation/dogs/" in page.url, "New dog edit page did not load"


def test_cross_account_and_roles(page):
    dog_id = CREDS["dog_id"]
    sign_in(page, "member2")
    go(page, f"/member/dogs/{dog_id}/photo/", status=403)
    go(page, f"/member/dogs/{dog_id}/document/", status=403)
    go(page, "/member/moderation/", status=403)


def test_editor_contributor_access(page):
    dog_id = CREDS["dog_id"]
    sign_in(page, "editor")
    go(page, f"/member/dogs/{dog_id}/photo/")
    go(page, f"/member/kennels/{CREDS['kennel_id']}/edit/")


def test_staff_and_admin_boundaries(page):
    sign_in(page, "moderator")
    go(page, "/member/moderation/")
    go(page, "/member/profile/", status=403)
    go(page, "/member/moderation/merge-dogs/", status=403)
    go(page, "/member/moderation/dogs/add/")
    go(page, "/member/moderation/verification/", status=403)


def test_owner_admin(page):
    sign_in(page, "owner")
    go(page, "/admin/")
    go(page, "/admin/registry/dog/")
    go(page, f"/admin/registry/dog/{CREDS['dog_id']}/change/")
    go(page, "/member/moderation/verification/")
    page.screenshot(path=OUT / "super-admin-dog-edit.png", full_page=True)


CASES = [
    ("guest", "public_search_navigation_responsive", test_visitor),
    ("member", "email_signup_verification_password_reset", test_account_email_lifecycle),
    ("member", "dog_draft_photo_database", test_member_draft_with_photo),
    ("member", "dog_draft_invalid", test_invalid_member_draft),
    ("member", "image_upload_rejection_review", test_member_photo_review_and_corrupt_image),
    ("member", "document_certificate_evidence_review", test_document_evidence_upload),
    ("member", "dog_correction_pending_canonical_integrity", test_member_correction_review),
    ("member", "pedigree_csv_and_virtual_mating", test_authenticated_pedigree_and_virtual_mating),
    ("moderator", "staff_private_dog_create_with_image", test_moderator_creates_private_canonical_dog),
    ("member2", "cross_account_dog_authorization", test_cross_account_and_roles),
    ("editor", "kennel_editor_permissions", test_editor_contributor_access),
    ("moderator", "staff_isolation", test_staff_and_admin_boundaries),
    ("super_admin", "django_admin_synthetic_dog", test_owner_admin),
]


def write_reports(browser):
    root = ET.Element("testsuite", name=f"cca-{browser}", tests=str(len(results)),
                      failures=str(sum(r["status"] == "FAIL" for r in results)))
    for r in results:
        testcase = ET.SubElement(root, "testcase", name=r["name"], classname=r["role"])
        if r["status"] == "FAIL":
            failure = ET.SubElement(testcase, "failure", message=r["error"])
            failure.text = r.get("traceback", "")
    ET.ElementTree(root).write(OUT / f"junit-{browser}.xml", encoding="utf-8", xml_declaration=True)
    (OUT / f"cases-{browser}.json").write_text(json.dumps(results, indent=2))
    table = "".join(
        "<tr><td>" + html.escape(r["role"]) + "</td><td>" + html.escape(r["name"]) +
        "</td><td>" + html.escape(r["status"]) + "</td><td><pre>" +
        html.escape(r.get("error", "")) + "</pre></td></tr>"
        for r in results
    )
    (OUT / f"report-{browser}.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Cane Corso QA</title>"
        "<h1>Browser journey results</h1><table border='1'>"
        "<tr><th>Role</th><th>Journey</th><th>Status</th><th>Error</th></tr>" +
        table + "</table>"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", required=True, choices=("chromium", "firefox", "webkit"))
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = getattr(p, args.browser).launch()
        try:
            for role, name, fn in CASES:
                ctx = browser.new_context(viewport={"width": 1366, "height": 900})
                ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                try:
                    fn(page)
                    assert not errors, "Browser console exceptions: " + "; ".join(errors[:5])
                    results.append({"name": name, "role": role, "browser": args.browser, "status": "PASS"})
                    ctx.tracing.stop()
                except Exception as exc:
                    item = {"name": name, "role": role, "browser": args.browser,
                            "status": "FAIL", "error": str(exc), "traceback": traceback.format_exc()}
                    results.append(item)
                    print("FAIL " + name + ": " + str(exc), flush=True)
                    try:
                        page.screenshot(path=OUT / f"FAIL-{args.browser}-{name}.png", full_page=True)
                        ctx.tracing.stop(path=str(OUT / f"trace-{args.browser}-{name}.zip"))
                    except Exception:
                        pass
                else:
                    print("PASS " + name, flush=True)
                finally:
                    ctx.close()
        finally:
            browser.close()
    write_reports(args.browser)
    assert len(results) == len(CASES), "QA scenarios silently skipped"
    if any(r["status"] != "PASS" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
