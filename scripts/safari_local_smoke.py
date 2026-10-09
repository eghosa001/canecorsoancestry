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
            # Tap actual visible hero text, not the top-left of <main>:
            # its bounding box may begin underneath Safari's sticky header.
            page.locator(".hero-copy h1").tap()
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
            # Playwright wait_for_function uses eval, forbidden by our CSP.
            # Let the 100ms debounce run, then inspect through page.evaluate.
            page.wait_for_timeout(300)
            assert page.evaluate("window.__safariResolve.length") > 0, "Suggestion fetch was not scheduled"
            page.locator("h1").tap()
            page.evaluate("window.__safariResolve.shift()()")
            page.wait_for_timeout(250)
            assert not page.locator(".dog-suggestion:visible").count(), "Safari stale picker reopened after dismissal"

            # The iOS keyboard changes VisualViewport size and Safari can
            # scroll the document while the user types. Keep results open and
            # selectable rather than hiding the picker during those changes.
            go(page, "/dogs/?q=")
            page.route("**/dogs/suggestions/**", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body='{"results":[{"id":"safari-fixture","slug":"safari-dog","name":"Safari Dog","registration":"","kennel":"","sex":"Male"}]}',
            ))
            field = page.locator("#q")
            field.fill("Safari")
            suggestions = page.locator(".dog-suggestions--viewport:visible")
            suggestions.locator(".dog-suggestion").first.wait_for(state="visible")
            assert suggestions.evaluate("el => el.parentElement === document.body"), "Picker is clipped inside a form"
            page.evaluate("window.scrollTo(0, 30)")
            page.set_viewport_size({"width": 390, "height": 560})
            page.evaluate("""() => {
              if (window.visualViewport) {
                visualViewport.dispatchEvent(new Event('resize'));
                visualViewport.dispatchEvent(new Event('scroll'));
              }
            }""")
            page.wait_for_timeout(160)
            assert suggestions.is_visible(), "iPhone keyboard/scroll closed the dog result list"
            assert field.get_attribute("aria-expanded") == "true", "Safari lost active suggestions"
            bounds = suggestions.bounding_box()
            assert bounds and bounds["height"] >= 54, "Suggestions are not tappable above keyboard"
            suggestions.locator(".dog-suggestion").first.tap()
            page.wait_for_url("**/dogs/safari-dog/**", timeout=10_000)

            # Dog photos retain their native landscape aspect ratio; no
            # zoom/crop, hard grey matte or CSS image scaling on profiles.
            photo = page.locator(".profile-photo img")
            photo.wait_for(state="visible")
            photo.evaluate("img => img.decode()")
            assert photo.evaluate("img => img.naturalWidth > 0"), "Dog photo failed to load"
            fidelity = photo.evaluate("""img => {
              const style = getComputedStyle(img);
              const frame = getComputedStyle(img.closest('.profile-photo'));
              const box = img.getBoundingClientRect();
              return {
                fit: style.objectFit, transform: style.transform,
                background: frame.backgroundColor, width: box.width,
                height: box.height, naturalRatio: img.naturalWidth / img.naturalHeight
              };
            }""")
            assert fidelity["fit"] == "contain", f"Photo is cropped: {fidelity}"
            assert fidelity["transform"] == "none", f"Photo is zoomed: {fidelity}"
            assert fidelity["background"] == "rgba(0, 0, 0, 0)", f"Gray photo frame: {fidelity}"
            assert abs(fidelity["width"] / fidelity["height"] - fidelity["naturalRatio"]) < .06, f"Dog aspect ratio distorted: {fidelity}"

            go(page, "/dogs/?q=Safari")
            thumb = page.locator(".search-result-media img")
            assert thumb.count() == 1, "Approved dog image missing from search"
            assert thumb.evaluate("el => getComputedStyle(el).objectFit") == "contain"
            assert thumb.evaluate("el => getComputedStyle(el).transform") == "none"

            go(page, "/accounts/login/")
            page.locator("input[name='username']").fill("safari-smoke@example.test")
            page.locator("input[name='password']").fill("safari-smoke-password")
            page.locator("input[name='username']").locator("xpath=ancestor::form").locator("button[type='submit']").click()
            page.wait_for_load_state("domcontentloaded")
            if "/accounts/login/" in page.url:
                problems = page.locator(".form-error, .errorlist").all_inner_texts()
                raise AssertionError(f"Safari login did not complete, errors={problems}, url={page.url}")

            dog_id = os.environ["SAFARI_TEST_DOG_ID"]
            go(page, f"/member/dogs/{dog_id}/photo/")
            buffer = io.BytesIO()
            Image.new("RGB", (48, 48), (80, 105, 130)).save(buffer, format="JPEG")
            page.locator("input[type='file']").set_input_files({
                "name": "iphone-safari.jpg",
                "mimeType": "image/jpeg",
                "buffer": buffer.getvalue(),
            })
            page.locator("form.member-form button[type='submit']").click()
            page.wait_for_url("**/member/submissions/", timeout=12000)
            assert "Photo submitted for review." in page.locator("body").inner_text()

            go(page, f"/member/dogs/{dog_id}/document/")
            page.locator("input[name='title']").fill("Safari PDF evidence")
            page.locator("input[type='file']").set_input_files({
                "name": "safari-pedigree.pdf",
                "mimeType": "application/pdf",
                "buffer": b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n",
            })
            page.locator("form.member-form button[type='submit']").click()
            page.wait_for_url("**/member/submissions/", timeout=12000)
            assert "Document submitted for review." in page.locator("body").inner_text()

            for width in (375, 430, 768):
                page.set_viewport_size({"width": width, "height": 844})
                go(page, "/dogs/?q=Safari")
                overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                assert overflow <= 3, f"WebKit horizontal overflow at {width}px: {overflow}"
                assert page.locator(".site-header").is_visible()

            assert not errors, f"WebKit JavaScript exceptions: {errors[:3]}"
            print("PASS: WebKit scrolling/keyboard picker, selectable dogs, uncropped natural photos, member login, uploads, responsive widths")
        finally:
            browser.close()


if __name__ == "__main__":
    run()
