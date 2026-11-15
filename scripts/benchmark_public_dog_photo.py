"""Public-page image waterfall probe for both desktop and phone viewports.

This checks actual live browser paint, not only a mock R2 response.
No credentials, image bodies or signed URL query parameters are printed.
"""
import sys
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout


ROOT = "https://canecorsoancestry.com/"


def sample_profile(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto(ROOT, wait_until="domcontentloaded", timeout=45000)
    card = page.locator("a.dog-card").first
    card.wait_for(state="attached", timeout=20000)
    url = urljoin(ROOT, card.get_attribute("href"))
    context.close()
    if urlsplit(url).hostname != "canecorsoancestry.com":
        raise RuntimeError("Sample link escaped the official production domain")
    return url


def probe(browser, url, name, mobile=False):
    context = browser.new_context(
        viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 900},
        device_scale_factor=2 if mobile else 1,
        is_mobile=mobile, has_touch=mobile,
        reduced_motion="reduce",
    )
    page = context.new_page()
    observed_images = []
    def on_response(response):
        if "/_thumb/" in response.url:
            headers = response.headers
            observed_images.append({
                "variant": headers.get("x-cca-image-variant", ""),
                "cache": headers.get("x-cca-image-cache", ""),
                "type": headers.get("content-type", "").split(";", 1)[0],
                "size": headers.get("content-length", "?"),
                "status": response.status,
            })
    page.on("response", on_response)
    try:
        for pass_number in (1, 2):
            observed_images.clear()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            photo = page.locator("[data-dog-photo-main]").first
            photo.wait_for(state="attached", timeout=12000)
            # The photo only counts as visible once decoded pixels are present.
            page.wait_for_function(
                "() => { const i = document.querySelector('[data-dog-photo-main]');"
                " return i && i.complete && i.naturalWidth > 0; }",
                timeout=30000,
            )
            metrics = page.evaluate("""() => {
                const navigation = performance.getEntriesByType('navigation')[0];
                const photo = document.querySelector('[data-dog-photo-main]');
                const current = photo.currentSrc || photo.src;
                const src = new URL(current);
                const resources = performance.getEntriesByType('resource');
                const media = resources.filter(r => r.name === current);
                const resource = media.at(-1);
                return {
                    navTtfbMs: Math.round(navigation?.responseStart || 0),
                    domMs: Math.round(navigation?.domContentLoadedEventEnd || 0),
                    visibleMs: Math.round(performance.now()),
                    imageHost: src.hostname,
                    photoVariant: src.searchParams.get('variant') || 'source',
                    imageTransferMs: resource ? Math.round(resource.duration) : null,
                    naturalWidth: photo.naturalWidth,
                    paintEntries: performance.getEntriesByType('paint').map(e =>
                        [e.name, Math.round(e.startTime)]),

                };
            }""")
            fcp_ms = next((v for k, v in metrics["paintEntries"]
                           if k == "first-contentful-paint"), 0)
            selected = next((r for r in observed_images if
                             r["variant"] == metrics["photoVariant"] or
                             r["variant"] == "original-fallback"), {})
            print(
                "PHOTO-PERF " + " ".join(
                    f"{key}={val}" for key, val in {
                        "mode": name,
                        "pass": pass_number,
                        "page": urlsplit(url).path,
                        "html_ttfb_ms": metrics["navTtfbMs"],
                        "html_dom_ms": metrics["domMs"],
                        "image_visible_ms": metrics["visibleMs"],
                        "image_after_dom_ms": max(
                            0, metrics["visibleMs"] - metrics["domMs"]
                        ),
                        "first_contentful_paint_ms": fcp_ms,
                        "image_after_first_paint_ms": max(
                            0, metrics["visibleMs"] - fcp_ms
                        ),
                        "image_request_ms": metrics["imageTransferMs"],
                        "image_host": metrics["imageHost"],
                        "variant": metrics["photoVariant"],
                        "decoded_width": metrics["naturalWidth"],
                        "media_response_variant": selected.get("variant", "browser-cache"),
                        "media_response_cache": selected.get("cache", "browser-cache"),
                        "media_response_type": selected.get("type", "browser-cache"),
                        "media_response_bytes": selected.get("size", "?"),
                    }.items()
                ),
                flush=True,
            )
    finally:
        context.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            url = sample_profile(browser)
            print("PHOTO-PERF note=GitHub-runner-network-not-Nigeria", flush=True)
            probe(browser, url, "desktop")
            probe(browser, url, "mobile", mobile=True)
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except BrowserTimeout as error:
        print(f"PHOTO-PERF status=timeout type={type(error).__name__}", file=sys.stderr)
        raise
