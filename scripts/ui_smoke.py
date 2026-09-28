import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("UI_BASE_URL", "http://127.0.0.1:8000")
OUT = Path(os.getenv("UI_SCREENSHOT_DIR", "artifacts/ui"))
OUT.mkdir(parents=True, exist_ok=True)


def assert_no_global_overflow(page, label):
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    if overflow > 3:
        raise AssertionError(f"{label} has {overflow}px of global horizontal overflow")


def screenshot(page, label, overflow=True):
    page.locator("main").wait_for(state="visible")
    if overflow:
        assert_no_global_overflow(page, label)
    page.screenshot(path=OUT / f"{label}.png", full_page=True)


def capture(page, path, label, overflow=True):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
    screenshot(page, label, overflow=overflow)
    if errors:
        raise AssertionError(f"{label} console errors: {errors}")


def login(page):
    page.goto(f"{BASE_URL}/accounts/login/", wait_until="networkidle")
    page.locator("#id_username").fill("ui-reviewer")
    page.locator("#id_password").fill("ui-reviewer-password")
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/dashboard/")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        capture(desktop, "/", "home-desktop")
        capture(desktop, "/dogs/?q=", "dogs-desktop")

        dog_cards = desktop.locator(".search-result-card")
        if dog_cards.count():
            dog_cards.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "dog-profile-desktop")

        capture(desktop, "/pedigrees/", "pedigrees-desktop")
        pedigree_cards = desktop.locator(".pedigree-index-card")
        if pedigree_cards.count():
            pedigree_cards.first.click()
            desktop.wait_for_load_state("networkidle")
            desktop.get_by_text("Ancestor contribution", exact=False).first.wait_for()
            desktop.get_by_text("Linebreeding paths", exact=False).first.wait_for()
            screenshot(desktop, "pedigree-detail-desktop", overflow=False)

        login(desktop)
        screenshot(desktop, "dashboard-desktop")
        capture(desktop, "/member/pedigrees/", "my-pedigrees-desktop")
        member_pedigrees = desktop.locator(".pedigree-workspace-card .btn-gold")
        if member_pedigrees.count():
            member_pedigrees.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "member-pedigree-detail-desktop", overflow=False)

        capture(desktop, "/member/litters/", "my-litters-desktop")
        capture(desktop, "/member/documents/", "documents-desktop")
        capture(desktop, "/member/moderation/", "moderation-desktop")
        capture(desktop, "/member/moderation/audit/", "moderation-audit-desktop")
        capture(desktop, "/member/disputes/", "my-disputes-desktop")
        capture(desktop, "/member/submit/dog/", "submit-dog-desktop")
        capture(desktop, "/kennels/claimable-kennel/", "claimable-kennel-desktop")
        claim_button = desktop.get_by_role("link", name="Claim this kennel")
        if claim_button.count():
            claim_button.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "kennel-claim-desktop")

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        capture(mobile, "/", "home-mobile")
        capture(mobile, "/dogs/?q=", "dogs-mobile")
        capture(mobile, "/pedigrees/", "pedigrees-mobile")
        mobile_pedigrees = mobile.locator(".pedigree-index-card")
        if mobile_pedigrees.count():
            mobile_pedigrees.first.click()
            mobile.wait_for_load_state("networkidle")
            mobile.locator(".analysis-mobile-summary").wait_for(state="visible")
            screenshot(mobile, "pedigree-detail-mobile", overflow=False)

        mobile_dogs = mobile.locator(".search-result-card")
        if mobile_dogs.count():
            mobile_dogs.first.click()
            mobile.wait_for_load_state("networkidle")
            screenshot(mobile, "dog-profile-mobile")

        login(mobile)
        screenshot(mobile, "dashboard-mobile")
        capture(mobile, "/member/pedigrees/", "my-pedigrees-mobile")
        capture(mobile, "/member/litters/", "my-litters-mobile")
        capture(mobile, "/member/documents/", "documents-mobile")
        capture(mobile, "/member/disputes/", "my-disputes-mobile")
        capture(mobile, "/member/submit/dog/", "submit-dog-mobile")

        browser.close()


if __name__ == "__main__":
    main()
