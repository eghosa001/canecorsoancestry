import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv(
    "PRODUCTION_BASE_URL",
    "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
).rstrip("/")
OUT = Path(os.getenv("PRODUCTION_SMOKE_DIR", "artifacts/production-smoke"))
OUT.mkdir(parents=True, exist_ok=True)
AXE_PATH = Path(os.getenv("AXE_CORE_PATH", "node_modules/axe-core/axe.min.js"))


def open_live(page, path, attempts=8):
    url = f"{BASE_URL}{path}"
    for _ in range(attempts):
        response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        if response and response.status >= 500:
            raise AssertionError(f"{path} returned HTTP {response.status}")
        warming = response.headers.get("x-cca-edge-warming") if response else None
        if not warming and page.locator(".site-header").count() and page.locator("main").count():
            page.wait_for_load_state("networkidle")
            return response
        page.wait_for_timeout(1_500)
    raise AssertionError(f"{path} never reached the live Django UI")


def assert_layout(page, label, mobile=False):
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    if overflow > 3:
        raise AssertionError(f"{label} has {overflow}px horizontal overflow")

    broken = page.evaluate(
        """() => [...document.images]
          .filter((img) => img.complete && img.naturalWidth === 0)
          .map((img) => img.currentSrc || img.src)"""
    )
    if broken:
        raise AssertionError(f"{label} has broken images: {broken[:5]}")

    unnamed = page.evaluate(
        """() => [...document.querySelectorAll('button, a[href], input, select, textarea')]
          .filter((el) => {
            if (el.matches('input[type="hidden"]')) return false;
            const aria = (el.getAttribute('aria-label') || '').trim();
            const text = (el.textContent || '').trim();
            const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
            const id = el.id;
            const label = id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null;
            const alt = el.querySelector && el.querySelector('img[alt]');
            return !aria && !text && !labelledBy && !label && !alt;
          }).length"""
    )
    if unnamed:
        raise AssertionError(f"{label} has {unnamed} unnamed interactive controls")

    if mobile:
        header = page.evaluate(
            """() => ({
              mainNav: getComputedStyle(document.querySelector('.main-nav')).display,
              actions: getComputedStyle(document.querySelector('.header-actions')).display,
              mobileNav: getComputedStyle(document.querySelector('.mobile-nav')).display,
              headerTop: document.querySelector('.site-header').getBoundingClientRect().top,
              logoWidth: document.querySelector('.brand-mark').getBoundingClientRect().width,
            })"""
        )
        if header["mainNav"] != "none" or header["actions"] != "none" or header["mobileNav"] == "none":
            raise AssertionError(f"{label} mobile header state is wrong: {header}")
        if header["headerTop"] < -1:
            raise AssertionError(f"{label} header is clipped above the safe area: {header}")
        if header["logoWidth"] < 40:
            raise AssertionError(f"{label} mobile logo is undersized: {header}")

        if page.locator(".hero-copy").count():
            spacing = page.evaluate(
                """() => {
                  const header = document.querySelector('.site-header').getBoundingClientRect();
                  const hero = document.querySelector('.hero-copy').getBoundingClientRect();
                  return hero.top - header.bottom;
                }"""
            )
            if spacing < 40:
                raise AssertionError(
                    f"{label} homepage content is too close to the header: {spacing}px"
                )


def axe_scan(page, label, axe_source):
    page.add_script_tag(content=axe_source)
    result = page.evaluate(
        """async () => await axe.run(document, {
          resultTypes: ['violations'],
          runOnly: {
            type: 'tag',
            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
          }
        })"""
    )
    serious = [
        {
            "id": violation["id"],
            "impact": violation.get("impact"),
            "nodes": len(violation.get("nodes") or []),
            "help": violation.get("help"),
            "targets": [
                node.get("target")
                for node in (violation.get("nodes") or [])[:4]
            ],
        }
        for violation in result.get("violations", [])
        if violation.get("impact") in {"serious", "critical"}
    ]
    if serious:
        raise AssertionError(f"{label} serious/critical accessibility violations: {serious}")


def assert_photo_only_search(page, label):
    open_live(page, "/dogs/?q=Branco")
    cards = page.locator(".search-result-card")
    if not cards.count():
        raise AssertionError(f"{label} known production search returned no photographed dog")
    missing = page.evaluate(
        """() => [...document.querySelectorAll('.search-result-card')]
          .filter((card) => !card.querySelector('img'))
          .map((card) => (card.textContent || '').trim().slice(0, 120))"""
    )
    if missing:
        raise AssertionError(f"{label} public search exposed image-less records: {missing[:5]}")


def assert_autocomplete_interactions(page, label):
    open_live(page, "/dogs/?q=")
    search = page.locator("#q")
    search.fill("Bran")
    option = page.locator(".dog-suggestion").first
    option.wait_for(state="visible", timeout=10_000)

    page.locator("h1").click()
    page.wait_for_timeout(150)
    if page.locator(".dog-suggestion:visible").count():
        raise AssertionError(f"{label} autocomplete does not dismiss on outside click")

    search.fill("Bran")
    page.locator(".dog-suggestion").first.wait_for(state="visible", timeout=10_000)
    page.evaluate("window.scrollTo(0, 260)")
    page.wait_for_timeout(150)
    if page.locator(".dog-suggestion:visible").count():
        raise AssertionError(f"{label} autocomplete does not dismiss on page scroll")


def browser_contract(browser_type, name, axe_source, mobile_options):
    browser = browser_type.launch()
    results = []
    try:
        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        for path, label in (
            ("/", "home"),
            ("/dogs/?q=Branco", "dog-search"),
            ("/pedigrees/", "pedigrees"),
            ("/accounts/login/", "login"),
            ("/member/signup/", "signup"),
            ("/accounts/password_reset/", "password-reset"),
        ):
            response = open_live(desktop, path)
            assert_layout(desktop, f"{name}-{label}-desktop")
            axe_scan(desktop, f"{name}-{label}-desktop", axe_source)
            results.append(
                {
                    "browser": name,
                    "viewport": "desktop",
                    "path": path,
                    "status": response.status if response else None,
                }
            )

        assert_photo_only_search(desktop, f"{name}-desktop")
        missing = desktop.goto(
            f"{BASE_URL}/__production-smoke-missing-page__/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        if not missing or missing.status != 404:
            raise AssertionError(f"{name} branded 404 returned {missing.status if missing else None}")
        if "404 · Page not found" not in desktop.locator("body").inner_text():
            raise AssertionError(f"{name} production 404 is not branded")

        mobile = browser.new_page(**mobile_options)
        for path, label in (
            ("/", "home"),
            ("/dogs/?q=Branco", "dog-search"),
            ("/pedigrees/", "pedigrees"),
            ("/accounts/login/", "login"),
            ("/member/signup/", "signup"),
            ("/accounts/password_reset/", "password-reset"),
        ):
            response = open_live(mobile, path)
            assert_layout(mobile, f"{name}-{label}-mobile", mobile=True)
            axe_scan(mobile, f"{name}-{label}-mobile", axe_source)
            results.append(
                {
                    "browser": name,
                    "viewport": "mobile",
                    "path": path,
                    "status": response.status if response else None,
                }
            )

        assert_photo_only_search(mobile, f"{name}-mobile")
        assert_autocomplete_interactions(mobile, f"{name}-mobile")
        mobile.screenshot(path=OUT / f"cross-browser-{name}-mobile.png", full_page=True)
    finally:
        browser.close()
    return results


def main():
    if not AXE_PATH.exists():
        raise AssertionError(
            f"axe-core was not installed at {AXE_PATH}; install npm package axe-core before running"
        )
    axe_source = AXE_PATH.read_text(encoding="utf-8")

    report = {"base_url": BASE_URL, "checks": []}
    with sync_playwright() as p:
        for name, browser_type in (
            ("chromium", p.chromium),
            ("firefox", p.firefox),
            ("webkit", p.webkit),
        ):
            mobile_options = {
                "viewport": {"width": 390, "height": 844},
                "has_touch": True,
            }
            if name != "firefox":
                mobile_options["is_mobile"] = True

            started = time.perf_counter()
            rows = browser_contract(
                browser_type,
                name,
                axe_source,
                mobile_options,
            )
            report["checks"].extend(rows)
            report[name] = {"seconds": round(time.perf_counter() - started, 3)}

    (OUT / "cross-browser-report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
