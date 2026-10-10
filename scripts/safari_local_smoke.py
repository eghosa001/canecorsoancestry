"""Focused WebKit/iPhone Safari interaction and upload smoke for local Django."""
import io
import os
import time
from urllib.parse import urljoin

from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE = os.environ.get("SAFARI_TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/"


def go(page, path):
    response = page.goto(urljoin(BASE, path.lstrip("/")), wait_until="load")
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
            photo = page.locator(".dog-portrait-image")
            photo.wait_for(state="visible")
            photo.evaluate("img => img.decode()")
            assert photo.evaluate("img => img.naturalWidth > 0"), "Dog photo failed to load"
            fidelity = photo.evaluate("""img => {
              const style = getComputedStyle(img);
              const frame = getComputedStyle(img.closest('.profile-photo'));
              const box = img.getBoundingClientRect();
              const surface = document.createElement('div');
              surface.style.backgroundColor = 'var(--surface)';
              document.body.append(surface);
              const themeSurface = getComputedStyle(surface).backgroundColor;
              surface.remove();
              return {
                fit: style.objectFit, transform: style.transform,
                imageBackground: style.backgroundColor,
                background: frame.backgroundColor,
                themeSurface, width: box.width,
                height: box.height, naturalRatio: img.naturalWidth / img.naturalHeight
              };
            }""")
            assert fidelity["fit"] == "contain", f"Photo is cropped: {fidelity}"
            assert fidelity["transform"] == "none", f"Photo is zoomed: {fidelity}"
            assert fidelity["imageBackground"] == "rgba(0, 0, 0, 0)", f"Artificial image matte: {fidelity}"
            assert fidelity["background"] == fidelity["themeSurface"], f"Portrait card does not match theme: {fidelity}"
            assert abs(fidelity["width"] / fidelity["height"] - fidelity["naturalRatio"]) < .06, f"Dog aspect ratio distorted: {fidelity}"

            # Owner acceptance: parents stack vertically and profile text
            # has readable spacing, with the original Inter-family headings.
            presentation = page.evaluate("""() => {
              const parents = document.querySelector('.profile-quick-parents');
              const facts = document.querySelector('.profile-facts');
              return {
                columns: getComputedStyle(parents).gridTemplateColumns,
                textFont: getComputedStyle(document.querySelector('.profile-title-row h1')).fontFamily,
                rowPadding: parseFloat(getComputedStyle(facts.querySelector('dt')).paddingBottom),
              };
            }""")
            assert len(presentation["columns"].split()) == 1, f"Sire and dam are side-by-side: {presentation}"
            assert "Georgia" in presentation["textFont"], f"Original heading serif not restored: {presentation}"
            body_font = page.evaluate("getComputedStyle(document.body).fontFamily")
            assert "Inter" in body_font, f"Original body font is not Inter: {body_font}"
            assert "About COI & sources" not in page.locator("body").inner_text(), "Unwanted COI/source panel remains"
            assert presentation["rowPadding"] >= 10, f"Dog details are cramped: {presentation}"

            # Premium gallery must preserve full image proportions while
            # allowing real taps, lightbox navigation, Escape and swipe.
            gallery_thumbs = page.locator("[data-dog-photo-thumb]")
            assert gallery_thumbs.count() == 2, "Approved photo thumbnails are missing"
            gallery_thumbs.nth(1).tap()
            assert gallery_thumbs.nth(1).get_attribute("aria-pressed") == "true"
            assert "safari-side.jpg" in photo.get_attribute("src"), "Thumbnail did not change portrait"
            page.locator("[data-dog-photo-open]").tap()
            modal = page.locator("[data-dog-photo-dialog]")
            assert modal.get_attribute("open") is not None, "Full-screen photo viewer did not open"
            assert "2 / 2" in modal.locator("[data-dog-lightbox-count]").inner_text()
            modal.locator("[data-dog-photo-prev]").click()
            assert "safari-landscape.jpg" in modal.locator("[data-dog-lightbox-image]").get_attribute("src")
            modal.locator("[data-dog-photo-zoom]").click()
            assert modal.locator("[data-dog-photo-stage]").evaluate(
                "el => el.classList.contains('is-zoomed')"
            ), "Explicit zoom did not activate"
            # Zoomed photo: pan in all four directions. JS must move the image,
            # not the document underneath it, and never block a tap-to-fit.
            viewport = modal.locator("[data-dog-photo-viewport]")
            enlarged = modal.locator("[data-dog-lightbox-image]")
            pan_probe = viewport.evaluate("""el => {
              const img = el.querySelector('img');
              const r = el.getBoundingClientRect();
              const cX = r.left + r.width / 2, cY = r.top + r.height / 2;
              const send = (type, x, y, pointerId=70) => {
                const ev = new PointerEvent(type, {
                  bubbles:true, cancelable:true, pointerId, pointerType:'touch',
                  isPrimary:true, clientX:x, clientY:y,
                });
                el.dispatchEvent(ev);
              };
              const initial = img.style.transform;
              send('pointerdown', cX, cY);
              send('pointermove', cX - 85, cY - 70);
              send('pointerup', cX - 85, cY - 70);
              const afterOne = img.style.transform;
              send('pointerdown', cX, cY, 71);
              send('pointermove', cX + 85, cY + 70, 71);
              send('pointerup', cX + 85, cY + 70, 71);
              return {initial, afterOne, afterTwo:img.style.transform};
            }""")
            assert pan_probe["initial"] != pan_probe["afterOne"], f"Cannot pan zoomed photo: {pan_probe}"
            assert pan_probe["afterOne"] != pan_probe["afterTwo"], f"Cannot inspect different dog areas: {pan_probe}"
            assert page.evaluate("document.body.style.position") == "fixed", (
                "Dragging zoomed dog moved the page beneath it"
            )
            # A normal tap on the picture resets zoom; a second tap closes
            # the full-screen view, without using the inconvenient Close button.
            viewport.evaluate("""el => {
              const r = el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
              for (const type of ['pointerdown','pointerup']) el.dispatchEvent(
                new PointerEvent(type, {bubbles:true, pointerId:73, pointerType:'touch',
                                        isPrimary:true,clientX:x,clientY:y}));
            }""")
            page.wait_for_timeout(370)
            assert not modal.locator("[data-dog-photo-stage]").evaluate(
                "el => el.classList.contains('is-zoomed')"
            ), "Tapping the zoomed photo should reset to its original fit"
            viewport.evaluate("""el => {
              const r = el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
              for (const type of ['pointerdown','pointerup']) el.dispatchEvent(
                new PointerEvent(type, {bubbles:true,pointerId:74,pointerType:'touch',
                                        isPrimary:true,clientX:x,clientY:y}));
            }""")
            page.wait_for_timeout(370)
            assert modal.get_attribute("open") is None, (
                "Tapping the fitted photo should close full-screen mode"
            )
            page.locator("[data-dog-photo-open]").tap()
            assert modal.get_attribute("open") is not None
            assert page.evaluate("document.body.style.position") == "fixed", (
                "The page underneath full-screen mode is not scroll locked"
            )
            # Swipe up inside the unzoomed photograph. The first vertical
            # movement must dismiss the dialog and reveal dog details.
            page.evaluate("""() => {
              const stage = document.querySelector('[data-dog-photo-stage]');
              const fire = (name, y) => {
                const evt = new Event(name, { bubbles: true, cancelable: true });
                Object.defineProperty(evt, 'touches', {
                  value: [{ clientX: 150, clientY: y }],
                });
                stage.dispatchEvent(evt);
              };
              fire('touchstart', 340);
              fire('touchmove', 300);
            }""")
            page.wait_for_timeout(650)
            assert modal.get_attribute("open") is None, "Vertical swipe did not immediately dismiss lightbox"
            assert page.evaluate("document.body.style.position") != "fixed", (
                "Full-screen swipe left background scroll locked"
            )
            assert page.evaluate("window.scrollY") > 0, (
                "Closing the viewer did not advance to the dog's details"
            )

            go(page, "/dogs/?q=Safari")
            thumb = page.locator(".search-result-media img")
            assert thumb.count() == 1, "Approved dog image missing from search"
            assert thumb.evaluate("el => getComputedStyle(el).objectFit") == "contain"
            assert thumb.evaluate("el => getComputedStyle(el).transform") == "none"

            go(page, "/accounts/login/")
            page.locator("input[name='username']").fill("safari-smoke@example.test")
            page.locator("input[name='password']").fill("safari-smoke-password")
            page.locator("input[name='username']").locator("xpath=ancestor::form").locator("button[type='submit']").click()
            # WebKit can finish the click before the redirect is committed.
            # Wait for actual navigation instead of checking URL immediately.
            try:
                page.wait_for_url(
                    lambda url: "/accounts/login/" not in str(url),
                    timeout=15_000,
                    wait_until="domcontentloaded",
                )
            except PlaywrightTimeoutError as exc:
                problems = page.locator(".form-error, .errorlist, .flash.error").all_inner_texts()
                excerpt = page.locator("body").inner_text()[:550]
                raise AssertionError(
                    f"Safari login did not complete, errors={problems}, url={page.url}, page={excerpt}"
                ) from exc

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
                if overflow > 3:
                    offenders = page.evaluate("""() => [...document.querySelectorAll('body *')]
                      .map(el => ({
                        tag: el.tagName,
                        cls: typeof el.className === 'string' ? el.className.slice(0, 85) : '',
                        text: (el.textContent || '').trim().slice(0, 50),
                        parent: el.parentElement && typeof el.parentElement.className === 'string' ? el.parentElement.className.slice(0, 95) : '',
                        right: Math.round(el.getBoundingClientRect().right),
                        width: Math.round(el.getBoundingClientRect().width)
                      }))
                      .filter(el => el.right > innerWidth + 3)
                      .sort((a, b) => b.right - a.right)
                      .slice(0, 8)
                    """)
                    raise AssertionError(
                        f"WebKit horizontal overflow at {width}px: {overflow}; offenders={offenders}"
                    )
                assert page.locator(".site-header").is_visible()

            assert not errors, f"WebKit JavaScript exceptions: {errors[:3]}"
            print("PASS: WebKit scrolling/keyboard picker, selectable dogs, uncropped natural photos, member login, uploads, responsive widths")
        finally:
            browser.close()


if __name__ == "__main__":
    run()
