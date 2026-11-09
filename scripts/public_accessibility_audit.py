"""Public-only WCAG check for the pre-launch Cloudflare/Oracle edge.

Never authenticates, modifies content or requests private pedigree pages.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROUTES = ("/", "/dogs/", "/pedigrees/", "/accounts/login/", "/billing-policy/")


def validate_site(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Accessibility audit needs a bare HTTPS website origin.")
    return url.rstrip("/")


def run(base_url, axe_path, output):
    from playwright.sync_api import sync_playwright
    base_url = validate_site(base_url)
    report = []
    failed = False
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        try:
            for viewport in ({"width": 1280, "height": 800}, {"width": 390, "height": 844}):
                page = browser.new_page(viewport=viewport, reduced_motion="reduce")
                for route in ROUTES:
                    url = base_url + route
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if response is None or response.status != 200:
                        raise AssertionError(f"Accessibility route unavailable: {route}, HTTP {response.status if response else 'none'}")
                    page.add_script_tag(path=axe_path)
                    result = page.evaluate("""async () => {
                      const r = await axe.run(document, {
                        runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}
                      });
                      return r.violations.map(v => ({
                        id: v.id, impact: v.impact,
                        examples: v.nodes.slice(0, 3).map(n => n.target.join(' '))
                      }));
                    }""")
                    severe = [v for v in result if v["impact"] in ("critical", "serious")]
                    record = {"route": route, "width": viewport["width"], "violations": result}
                    report.append(record)
                    print(f"WCAG {route} {viewport['width']}px: {len(result)} violations ({len(severe)} serious/critical)")
                    for item in severe:
                        print(f"  {item['impact']}: {item['id']} selectors={item['examples']}")
                    failed |= bool(severe)
                page.close()
        finally:
            browser.close()
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
    if failed:
        raise SystemExit("Public-page accessibility audit found serious/critical WCAG violations.")
    print("PASS: no serious/critical automated WCAG violations on sampled public pages.")


if __name__ == "__main__":
    run(os.environ.get("PRODUCTION_BASE_URL", ""),
        os.environ.get("AXE_PATH", "node_modules/axe-core/axe.min.js"),
        os.environ.get("CCA_A11Y_REPORT", "artifacts/public-accessibility.json"))
