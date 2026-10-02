import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("PRODUCTION_BASE_URL", "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev").rstrip("/")
OUT = Path(os.getenv("PRODUCTION_SMOKE_DIR", "artifacts/production-smoke"))
OUT.mkdir(parents=True, exist_ok=True)

PUBLIC_ROUTES = (
    ("/", "home"),
    ("/dogs/?q=", "dogs"),
    ("/kennels/", "kennels"),
    ("/pedigrees/", "pedigrees"),
    ("/pedigrees/virtual-mating/", "virtual-mating"),
    ("/statistics/", "statistics"),
    ("/accounts/login/", "login"),
    ("/member/signup/", "signup"),
    ("/accounts/password_reset/", "password-reset"),
)


def wait_for_real_app(page, path, *, attempts=8):
    url = f"{BASE_URL}{path}"
    response = None
    started = time.perf_counter()
    for _ in range(attempts):
        response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        if response and response.status >= 500:
            raise AssertionError(f"{path} returned HTTP {response.status}")
        warming = response.headers.get("x-cca-edge-warming") if response else None
        if not warming and page.locator(".site-header").count() and page.locator("main").count():
            page.wait_for_load_state("networkidle")
            return response, time.perf_counter() - started
        page.wait_for_timeout(1_500)
    raise AssertionError(f"{path} never reached the live Django UI")


def assert_page(page, label, *, mobile=False):
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    if overflow > 3:
        raise AssertionError(f"{label} has {overflow}px horizontal overflow")

    broken = page.evaluate(
        """() => [...document.images]
          .filter((img) => {
            if (!img.complete || img.naturalWidth !== 0) return false;
            if (img.loading !== "lazy") return true;
            const rect = img.getBoundingClientRect();
            return rect.top < window.innerHeight + 300 && rect.bottom > -300;
          })
          .map((img) => img.currentSrc || img.src)"""
    )
    if broken:
        raise AssertionError(f"{label} has broken images: {broken[:5]}")

    unnamed = page.evaluate(
        """() => [...document.querySelectorAll('button, a[href]')].filter((el) => {
          const name = (el.getAttribute('aria-label') || el.textContent || '').trim();
          return !name && !el.querySelector('img[alt]');
        }).length"""
    )
    if unnamed:
        raise AssertionError(f"{label} has {unnamed} unnamed controls")

    if mobile:
        state = page.evaluate(
            """() => ({
              mainNav: getComputedStyle(document.querySelector('.main-nav')).display,
              actions: getComputedStyle(document.querySelector('.header-actions')).display,
              mobileNav: getComputedStyle(document.querySelector('.mobile-nav')).display,
            })"""
        )
        if state["mainNav"] != "none" or state["actions"] != "none" or state["mobileNav"] == "none":
            raise AssertionError(f"{label} mobile header is incorrect: {state}")


def verify_featured_images(page, label):
    images = page.locator(".featured-dog-grid img")
    if not images.count():
        return
    images.first.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    for index in range(min(images.count(), 4)):
        image = images.nth(index)
        image.scroll_into_view_if_needed()
        image.wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            "(img) => img.complete && img.naturalWidth > 0",
            arg=image.element_handle(),
            timeout=10_000,
        )
    page.screenshot(path=OUT / f"{label}-featured.png", full_page=True)


def visit(page, path, label, *, mobile=False):
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    response, elapsed = wait_for_real_app(page, path)
    assert_page(page, label, mobile=mobile)
    if console_errors:
        raise AssertionError(f"{label} console errors: {console_errors}")

    page.screenshot(path=OUT / f"{label}.png", full_page=True)
    return {
        "path": path,
        "status": response.status if response else None,
        "seconds": round(elapsed, 3),
        "edge_cache": response.headers.get("x-cca-edge-cache") if response else None,
        "server_timing": response.headers.get("server-timing") if response else None,
        "final_url": page.url,
    }


def concurrent_health_probe(total=16, workers=8):
    def one(_):
        started = time.perf_counter()
        response = requests.get(
            f"{BASE_URL}/healthz/",
            headers={"Accept": "application/json", "User-Agent": "CCA-Production-Smoke/1.0"},
            timeout=15,
        )
        return response.status_code, time.perf_counter() - started

    timings = []
    statuses = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i) for i in range(total)]
        for future in as_completed(futures):
            status, elapsed = future.result()
            statuses.append(status)
            timings.append(elapsed)

    if any(status != 200 for status in statuses):
        raise AssertionError(f"Concurrent health probe statuses: {statuses}")

    ordered = sorted(timings)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    result = {
        "requests": total,
        "concurrency": workers,
        "median_seconds": round(statistics.median(timings), 3),
        "p95_seconds": round(ordered[p95_index], 3),
        "max_seconds": round(max(timings), 3),
    }
    if result["p95_seconds"] > 6:
        raise AssertionError(f"Dynamic origin concurrency probe is too slow: {result}")
    return result


def concurrent_profile_probe(path, total=12, workers=8):
    def one(index):
        separator = "&" if "?" in path else "?"
        url = f"{BASE_URL}{path}{separator}smoke=concurrency-{index}"
        started = time.perf_counter()
        response = requests.get(
            url,
            headers={"Accept": "text/html", "User-Agent": "CCA-Production-Smoke/1.0"},
            timeout=20,
        )
        elapsed = time.perf_counter() - started
        warming = response.headers.get("x-cca-edge-warming")
        is_profile = "BRANCO" in response.text.upper()
        return response.status_code, warming, is_profile, elapsed

    timings = []
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i) for i in range(total)]
        for future in as_completed(futures):
            status, warming, is_profile, elapsed = future.result()
            timings.append(elapsed)
            if status != 200 or warming or not is_profile:
                failures.append(
                    {"status": status, "warming": warming, "is_profile": is_profile}
                )

    if failures:
        raise AssertionError(f"Concurrent dog-profile probe failures: {failures}")

    ordered = sorted(timings)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    result = {
        "requests": total,
        "concurrency": workers,
        "median_seconds": round(statistics.median(timings), 3),
        "p95_seconds": round(ordered[p95_index], 3),
        "max_seconds": round(max(timings), 3),
    }
    if result["p95_seconds"] > 5:
        raise AssertionError(f"Concurrent dog-profile probe is too slow: {result}")
    return result


def main():
    report = {"base_url": BASE_URL, "desktop": [], "mobile": [], "details": []}
    dog_load_path = None
    pedigree_load_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for path, label in PUBLIC_ROUTES:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            report["desktop"].append(visit(page, path, f"{label}-desktop"))
            if label == "home":
                gold = page.evaluate(
                    "() => getComputedStyle(document.documentElement).getPropertyValue('--gold').trim()"
                )
                if gold.lower() != "#d2ad57":
                    raise AssertionError(f"Unexpected production theme accent: {gold}")
                if page.locator("[data-theme-toggle]").count():
                    raise AssertionError("Production still exposes the removed theme toggle")
                canonical = page.locator('link[rel="canonical"]').get_attribute("href")
                if canonical != BASE_URL + "/":
                    raise AssertionError(f"Production canonical host is wrong: {canonical}")
                verify_featured_images(page, "home-desktop")
            page.close()

        detail_page = browser.new_page(viewport={"width": 1440, "height": 1000})
        wait_for_real_app(detail_page, "/dogs/?q=Branco")
        dog_links = detail_page.locator(".search-result-card")
        if not dog_links.count():
            raise AssertionError("Production dog search returned no result for Branco")
        dog_href = dog_links.first.get_attribute("href")
        if not dog_href:
            raise AssertionError("Production dog search result has no link")
        dog_load_path = dog_href.split("?", 1)[0]
        dog_path = dog_load_path + "?smoke=1"
        dog_response, dog_elapsed = wait_for_real_app(detail_page, dog_path)
        assert_page(detail_page, "dog-profile-desktop")
        detail_page.screenshot(path=OUT / "dog-profile-desktop.png", full_page=True)
        report["details"].append({
            "dog_profile": detail_page.url,
            "seconds": round(dog_elapsed, 3),
            "server_timing": dog_response.headers.get("server-timing") if dog_response else None,
            "edge_cache": dog_response.headers.get("x-cca-edge-cache") if dog_response else None,
        })
        detail_page.close()

        pedigree_page = browser.new_page(viewport={"width": 1440, "height": 1000})
        wait_for_real_app(pedigree_page, "/pedigrees/")
        pedigree_links = pedigree_page.locator(".pedigree-index-card")
        if pedigree_links.count():
            pedigree_href = pedigree_links.first.get_attribute("href")
            if not pedigree_href:
                raise AssertionError("Production pedigree result has no link")
            pedigree_load_path = pedigree_href.split("?", 1)[0]
            pedigree_path = pedigree_load_path + "?smoke=1"
            pedigree_response, pedigree_elapsed = wait_for_real_app(pedigree_page, pedigree_path)
            assert_page(pedigree_page, "pedigree-detail-desktop")
            pedigree_page.screenshot(path=OUT / "pedigree-detail-desktop.png", full_page=True)
            report["details"].append({
                "pedigree_detail": pedigree_page.url,
                "seconds": round(pedigree_elapsed, 3),
                "server_timing": pedigree_response.headers.get("server-timing") if pedigree_response else None,
                "edge_cache": pedigree_response.headers.get("x-cca-edge-cache") if pedigree_response else None,
            })
        pedigree_page.close()

        for path, label in (
            ("/", "home"),
            ("/dogs/?q=", "dogs"),
            ("/kennels/", "kennels"),
            ("/pedigrees/", "pedigrees"),
            ("/pedigrees/virtual-mating/", "virtual-mating"),
            ("/statistics/", "statistics"),
            ("/accounts/login/", "login"),
            ("/member/signup/", "signup"),
        ):
            page = browser.new_page(viewport={"width": 390, "height": 844})
            report["mobile"].append(visit(page, path, f"{label}-mobile", mobile=True))
            if label == "home":
                page.locator(".mobile-nav > summary").click()
                if not page.locator(".mobile-nav-panel").is_visible():
                    raise AssertionError("Production mobile menu did not open")
                page.screenshot(path=OUT / "home-mobile-menu.png", full_page=True)
                page.evaluate("window.scrollTo(0, 320)")
                page.wait_for_timeout(150)
                if page.locator(".mobile-nav").get_attribute("open") is not None:
                    raise AssertionError("Production mobile menu stays open after scroll")
                skip_link = page.locator(".skip-link")
                skip_top = skip_link.evaluate("(el) => el.getBoundingClientRect().top")
                if skip_top >= 0:
                    raise AssertionError("Production skip-link should remain hidden after pointer/scroll interactions")
                page.evaluate("document.activeElement && document.activeElement.blur()")
                page.keyboard.press("Tab")
                if not skip_link.evaluate("(el) => document.activeElement === el"):
                    raise AssertionError("Production skip-link is not first in keyboard navigation")
                if skip_link.evaluate("(el) => el.getBoundingClientRect().top") < 0:
                    raise AssertionError("Production skip-link is not visible for keyboard focus")
                page.keyboard.press("Tab")
                verify_featured_images(page, "home-mobile")
            if label == "dogs":
                search = page.locator("#q")
                search.fill("Bran")
                page.locator(".dog-suggestion").first.wait_for(state="visible", timeout=10_000)
                if "BRAN" not in page.locator(".dog-suggestion").first.inner_text().upper():
                    raise AssertionError("Production dog autocomplete returned an unexpected suggestion")
            page.close()

        if dog_load_path:
            dog_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            dog_response, dog_elapsed = wait_for_real_app(
                dog_mobile, dog_load_path + "?smoke=mobile"
            )
            assert_page(dog_mobile, "dog-profile-mobile", mobile=True)
            dog_mobile.screenshot(path=OUT / "dog-profile-mobile.png", full_page=True)
            report["details"].append({
                "dog_profile_mobile": dog_mobile.url,
                "seconds": round(dog_elapsed, 3),
                "server_timing": dog_response.headers.get("server-timing") if dog_response else None,
            })
            dog_mobile.close()

        if pedigree_load_path:
            pedigree_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            pedigree_response, pedigree_elapsed = wait_for_real_app(
                pedigree_mobile, pedigree_load_path + "?smoke=mobile"
            )
            assert_page(pedigree_mobile, "pedigree-detail-mobile", mobile=True)
            pedigree_mobile.screenshot(path=OUT / "pedigree-detail-mobile.png", full_page=True)
            report["details"].append({
                "pedigree_detail_mobile": pedigree_mobile.url,
                "seconds": round(pedigree_elapsed, 3),
                "server_timing": pedigree_response.headers.get("server-timing") if pedigree_response else None,
            })
            pedigree_mobile.close()

        private = browser.new_page(viewport={"width": 390, "height": 844})
        response = private.goto(f"{BASE_URL}/dashboard/", wait_until="domcontentloaded")
        if not response or response.status >= 500 or "/accounts/login/" not in private.url:
            raise AssertionError(f"Private dashboard did not redirect safely: {private.url}")
        private.close()

        browser.close()

    report["concurrency"] = {
        "health": concurrent_health_probe(),
        "dog_profile": concurrent_profile_probe(dog_load_path),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
