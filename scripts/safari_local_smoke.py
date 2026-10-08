"""Focused WebKit/iPhone Safari interaction and upload smoke for local Django."""
import io
import os
import time
from urllib.parse import urljoin

from PIL import Image
from playwright.sync_api import sync_playwright


BASE = os.environ.get("SAFARI_TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/"


def go(page, path):
    response = page.goto(urljoin(BASE, path.lstrip("/")), wait_until="domcontentloaded")
    assert response and response.status == 200, f"{path} returned {response.status if response else 'no response'}"


def run():
    with sync_playwright() as play:
        browser = play.webkit.launch()
        try:
            page = browser.new_page(
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
            )
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            go(page, "/")
            assert page.locator(".site-header").is_visible()
            nav = page.locator(".mobile-nav")
            nav.locator("summary").tap()
            assert nav.get_attribute("open") is not None, "iPhone menu will not open"
            page.locator("#main-content").tap(position={"x": 15, "y": 15})
            assert nav.get_attribute("open") is None, "tapping outside leaves Safari menu open"

            go(page, "/dogs/?q=")
            field = page.locator("#q")
            size = float(field.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
            assert size >= 16, f"Safari search zoom risk: {size}px input"
            # Control the delayed suggestion response to reproduce the Safari
            # blur / navigation race without depending on network timing.
            page.evaluate("""() => {
              const nativeFetch = window.fetch;
              window.__safariResolve = [];
              window.fetch = (url, opts) => {
                if (String(url).includes('/dogs/suggestions/')) {
                  return new Promise(resolve => {
                    window.__safariResolve.push(() => resolve({
                      ok: true, json: async () => ({ results: [{
                        id:'fake', slug:'safari-dog', name:'Safari Dog',
                        registration:'', kennel:'', sex:'Male'
                      }]})
                    }));
                  });
                }
                return nativeFetch(url, opts);
              };
            }""")
            field.fill("Safari")
            page.wait_for_function("window.__safariResolve.length > 0", timeout=6000)
            page.locator("h1").tap()
            page.evaluate("window.__safariResolve.shift()()")
            page.wait_for_timeout(250)
            assert not page.locator(".dog-suggestion:visible").count(), "Safari stale picker reopened after dismissal"

            go(page, "/accounts/login/")
            page.locator("input[name='username']").fill("safari-smoke-member")
            page.locator("input[name='password']").fill("safari-smoke-password")
            page.locator("button[type='submit']").first.click()
            page.wait_for_load_state("domcontentloaded")
            assert "/accounts/login/" not in page.url, "Safari login did not complete"

            dog_id = os.environ["SAFARI_TEST_DOG_ID"]
            go(page, f"/member/dogs/{dog_id}/photo/")
            buffer = io.BytesIO()
            Image.new("RGB", (48, 48), (80, 105, 130)).save(buffer, format="JPEG")
            page.locator("input[type='file']").set_input_files({
                "name": "iphone-safari.jpg",
                "mimeType": "image/jpeg",
                "buffer": buffer.getvalue(),
            })
            page.locator("button[type='submit']").last.click()
            page.wait_for_url("**/member/submissions/", timeout=12000)
            assert "Photo submitted for review." in page.locator("body").inner_text()

            go(page, f"/member/dogs/{dog_id}/document/")
            page.locator("input[name='title']").fill("Safari PDF evidence")
            page.locator("input[type='file']").set_input_files({
                "name": "safari-pedigree.pdf",
                "mimeType": "application/pdf",
                "buffer": b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n",
            })
            page.locator("button[type='submit']").last.click()
            page.wait_for_url("**/member/submissions/", timeout=12000)
            assert "Document submitted for review." in page.locator("body").inner_text()

            for width in (375, 430, 768):
                page.set_viewport_size({"width": width, "height": 844})
                go(page, "/dogs/?q=Safari")
                overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                assert overflow <= 3, f"WebKit horizontal overflow at {width}px: {overflow}"
                assert page.locator(".site-header").is_visible()

            assert not errors, f"WebKit JavaScript exceptions: {errors[:3]}"
            print("PASS: WebKit touch navigation, stale suggestions, no zoom, member login, JPG/PDF upload, responsive widths")
        finally:
            browser.close()


if __name__ == "__main__":
    run()
