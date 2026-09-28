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


def capture(page, path, label, overflow=True):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
    page.locator("main").wait_for(state="visible")
    if overflow:
        assert_no_global_overflow(page, label)
    page.screenshot(path=OUT / f"{label}.png", full_page=True)
    if errors:
        raise AssertionError(f"{label} console errors: {errors}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        capture(desktop, "/", "home-desktop")
        capture(desktop, "/dogs/?q=", "dogs-desktop")
        capture(desktop, "/pedigrees/", "pedigrees-desktop")

        cards = desktop.locator(".pedigree-index-card")
        if cards.count():
            cards.first.click()
            desktop.wait_for_load_state("networkidle")
            desktop.screenshot(path=OUT / "pedigree-detail-desktop.png", full_page=True)

        desktop.goto(f"{BASE_URL}/accounts/login/", wait_until="networkidle")
        desktop.locator("#id_username").fill("ui-reviewer")
        desktop.locator("#id_password").fill("ui-reviewer-password")
        desktop.locator("button[type=submit]").click()
        desktop.wait_for_url("**/dashboard/")
        assert_no_global_overflow(desktop, "dashboard-desktop")
        desktop.screenshot(path=OUT / "dashboard-desktop.png", full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        capture(mobile, "/", "home-mobile")
        capture(mobile, "/dogs/?q=", "dogs-mobile")
        mobile.goto(f"{BASE_URL}/accounts/login/", wait_until="networkidle")
        mobile.locator("#id_username").fill("ui-reviewer")
        mobile.locator("#id_password").fill("ui-reviewer-password")
        mobile.locator("button[type=submit]").click()
        mobile.wait_for_url("**/dashboard/")
        assert_no_global_overflow(mobile, "dashboard-mobile")
        mobile.screenshot(path=OUT / "dashboard-mobile.png", full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
