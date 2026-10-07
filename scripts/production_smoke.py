# Final UX live contract v75
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


def assert_visual_contrast(page, background_selector, foreground_selector, label, minimum=4.5):
    result = page.evaluate(
        """([backgroundSelector, foregroundSelector]) => {
          const backgroundNode = document.querySelector(backgroundSelector);
          const foregroundNode = document.querySelector(foregroundSelector);
          if (!backgroundNode || !foregroundNode) return null;

          const parse = (value) => {
            const parts = (value.match(/[0-9.]+/g) || []).slice(0, 3).map(Number);
            return parts.length === 3 ? parts : null;
          };
          const channel = (value) => {
            const normalized = value / 255;
            return normalized <= 0.04045
              ? normalized / 12.92
              : Math.pow((normalized + 0.055) / 1.055, 2.4);
          };
          const luminance = (rgb) =>
            0.2126 * channel(rgb[0]) +
            0.7152 * channel(rgb[1]) +
            0.0722 * channel(rgb[2]);

          const background = parse(getComputedStyle(backgroundNode).backgroundColor);
          const foreground = parse(getComputedStyle(foregroundNode).color);
          if (!background || !foreground) return null;
          const backgroundLuminance = luminance(background);
          const foregroundLuminance = luminance(foreground);
          const ratio =
            (Math.max(backgroundLuminance, foregroundLuminance) + 0.05) /
            (Math.min(backgroundLuminance, foregroundLuminance) + 0.05);
          return {
            ratio,
            background: getComputedStyle(backgroundNode).backgroundColor,
            foreground: getComputedStyle(foregroundNode).color,
          };
        }""",
        [background_selector, foreground_selector],
    )
    if result is None:
        raise AssertionError(f"{label} elements are missing")
    if result["ratio"] < minimum:
        raise AssertionError(f"{label} contrast is too low: {result}")


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


def live_virtual_mating_probe():
    headers = {
        "Accept": "application/json",
        "User-Agent": "CCA-Production-Smoke/1.0",
    }
    male = requests.get(
        f"{BASE_URL}/dogs/suggestions/?q=&browse=1&sex=male",
        headers=headers,
        timeout=15,
    )
    female = requests.get(
        f"{BASE_URL}/dogs/suggestions/?q=&browse=1&sex=female",
        headers=headers,
        timeout=15,
    )
    male.raise_for_status()
    female.raise_for_status()
    male_rows = male.json().get("results") or []
    female_rows = female.json().get("results") or []
    if not male_rows or not female_rows:
        raise AssertionError("Virtual mating suggestions did not return both sexes")

    sire = male_rows[0]
    dam = next(
        (row for row in female_rows if row.get("id") != sire.get("id")),
        female_rows[0],
    )
    started = time.perf_counter()
    response = requests.get(
        f"{BASE_URL}/pedigrees/virtual-mating/",
        params={
            "sire": sire["id"],
            "sire_q": sire["name"],
            "dam": dam["id"],
            "dam_q": dam["name"],
            "generations": "4",
            "smoke": "pairing",
        },
        headers={"Accept": "text/html", "User-Agent": "CCA-Production-Smoke/1.0"},
        timeout=20,
    )
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        raise AssertionError(f"Virtual mating returned HTTP {response.status_code}")
    body = response.text
    if "Projected offspring COI" not in body or "Virtual mating result" not in body:
        raise AssertionError("Virtual mating did not render a completed analysis")
    if 'class="notice error"' in body:
        raise AssertionError("Virtual mating rendered an application error")
    return {
        "sire": sire["name"],
        "dam": dam["name"],
        "seconds": round(elapsed, 3),
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
    warming_responses = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i) for i in range(total)]
        for future in as_completed(futures):
            status, warming, is_profile, elapsed = future.result()
            timings.append(elapsed)
            if warming:
                warming_responses += 1
            if status != 200 or not is_profile:
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
    kennel_detail_path = None
    litter_detail_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for path, label in PUBLIC_ROUTES:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            report["desktop"].append(visit(page, path, f"{label}-desktop"))
            if label == "home":
                if page.locator(".dog-card .verification-pill").count():
                    raise AssertionError("Homepage still shows dog verification badges")
                gold = page.evaluate(
                    "() => getComputedStyle(document.documentElement).getPropertyValue('--gold').trim()"
                )
                if gold.lower() != "#c7a25d":
                    raise AssertionError(f"Unexpected dark-theme accent: {gold}")
                if page.locator("[data-theme-toggle]").count() != 3:
                    raise AssertionError("Production does not expose desktop, header-mobile, and menu-mobile theme controls")
                if page.locator(".hero-mark").count():
                    raise AssertionError("Obsolete decorative hero plaque is still rendered")
                assert_visual_contrast(
                    page,
                    ".hero-search input",
                    ".hero-search input",
                    "Dark-theme hero search",
                )
                assert_visual_contrast(
                    page,
                    ".action-card",
                    ".action-card strong",
                    "Dark-theme home action card",
                )
                if page.locator(".hero-stats article").count() != 4:
                    raise AssertionError("Homepage should expose exactly four compact public metrics")
                bg = page.evaluate(
                    "() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
                )
                if bg.lower() != "#101110":
                    raise AssertionError(f"Unexpected dark-theme background: {bg}")

                page.locator("[data-theme-toggle]").first.click()
                if page.locator("html").get_attribute("data-theme") != "light":
                    raise AssertionError("Production theme toggle did not switch to light mode")
                light_bg = page.evaluate(
                    "() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
                )
                if light_bg.lower() != "#f4f0e8":
                    raise AssertionError(f"Unexpected light-theme background: {light_bg}")
                assert_visual_contrast(
                    page,
                    ".hero-search input",
                    ".hero-search input",
                    "Light-theme hero search",
                )
                assert_visual_contrast(
                    page,
                    ".action-card",
                    ".action-card strong",
                    "Light-theme home action card",
                )
                page.locator("[data-theme-toggle]").first.click()
                if page.locator("html").get_attribute("data-theme") != "dark":
                    raise AssertionError("Production theme toggle did not restore dark mode")
                brand = page.locator(".brand-mark")
                brand_src = brand.get_attribute("src") or ""
                if "cane-corso-head-logo-right" not in brand_src or brand_src.startswith("data:"):
                    raise AssertionError(f"Header is not using the cached Cane Corso head asset: {brand_src}")
                if brand.evaluate("(el) => !el.complete || el.naturalWidth < 32 || el.naturalHeight < 32"):
                    raise AssertionError("Cane Corso head logo did not render correctly")
                canonical = page.locator('link[rel="canonical"]').get_attribute("href")
                if canonical != BASE_URL + "/":
                    raise AssertionError(f"Production canonical host is wrong: {canonical}")
                verify_featured_images(page, "home-desktop")
            if label == "kennels":
                kennel_detail_path = page.evaluate(
                    """() => {
                      const cards = [...document.querySelectorAll(".kennel-card")];
                      const withLitters = cards.find((card) => {
                        const stats = [...card.querySelectorAll(".mini-stats strong")].map((node) =>
                          Number((node.textContent || "0").replace(/[^0-9]/g, "")) || 0
                        );
                        return (stats[1] || 0) > 0;
                      });
                      return (withLitters || cards[0])?.getAttribute("href") || null;
                    }"""
                )
                if not kennel_detail_path:
                    raise AssertionError("Kennel directory did not expose a navigable kennel profile")
            page.close()

        if kennel_detail_path:
            kennel_page = browser.new_page(viewport={"width": 1440, "height": 1000})
            kennel_response, kennel_elapsed = wait_for_real_app(kennel_page, kennel_detail_path)
            assert_page(kennel_page, "kennel-detail-desktop")
            if kennel_page.locator(".dog-card").count() > 24:
                raise AssertionError("Kennel detail renders more than 24 dog cards at once")
            if kennel_page.locator(".litter-row").count() > 20:
                raise AssertionError("Kennel detail renders more than 20 litters at once")
            if kennel_page.locator(".litter-row").count():
                litter_detail_path = kennel_page.locator(".litter-row").first.get_attribute("href")
            kennel_page.screenshot(path=OUT / "kennel-detail-desktop.png", full_page=True)
            report["details"].append({
                "kennel_detail": kennel_page.url,
                "seconds": round(kennel_elapsed, 3),
                "server_timing": kennel_response.headers.get("server-timing") if kennel_response else None,
                "edge_cache": kennel_response.headers.get("x-cca-edge-cache") if kennel_response else None,
            })
            kennel_page.close()

        if litter_detail_path:
            litter_page = browser.new_page(viewport={"width": 1440, "height": 1000})
            litter_response, litter_elapsed = wait_for_real_app(litter_page, litter_detail_path)
            assert_page(litter_page, "litter-detail-desktop")
            if not litter_page.locator(".dog-card").count():
                raise AssertionError("Public litter detail has no navigable offspring cards")
            litter_page.screenshot(path=OUT / "litter-detail-desktop.png", full_page=True)
            report["details"].append({
                "litter_detail": litter_page.url,
                "seconds": round(litter_elapsed, 3),
                "server_timing": litter_response.headers.get("server-timing") if litter_response else None,
                "edge_cache": litter_response.headers.get("x-cca-edge-cache") if litter_response else None,
            })
            litter_page.close()

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
        if detail_page.locator(".profile-title-row .verification-pill").count():
            raise AssertionError("Dog profile still shows the verification badge beside the name")
        if "SOURCE ATTACHED" in detail_page.locator("body").inner_text().upper():
            raise AssertionError("Dog profile still exposes the Source attached verification label")
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
            ("/accounts/password_reset/", "password-reset"),
        ):
            page = browser.new_page(viewport={"width": 390, "height": 844})
            report["mobile"].append(visit(page, path, f"{label}-mobile", mobile=True))
            if label == "home":
                if page.locator(".hero h1 br").count():
                    raise AssertionError("Production mobile hero title still contains a literal line break")
                title_stack = page.evaluate(
                    """() => {
                      const primary = document.querySelector(".hero-title-primary");
                      const corso = document.querySelector(".hero-mobile-break");
                      const secondary = document.querySelector(".hero-title-secondary");
                      const primaryBox = primary.getBoundingClientRect();
                      const secondaryBox = secondary.getBoundingClientRect();
                      return {
                        corsoDisplay: getComputedStyle(corso).display,
                        gap: secondaryBox.top - primaryBox.bottom,
                      };
                    }"""
                )
                if title_stack["corsoDisplay"] != "block":
                    raise AssertionError(f"Production CORSO line is not stacked: {title_stack}")
                if title_stack["gap"] > 8:
                    raise AssertionError(f"Production mobile hero title has an oversized line gap: {title_stack}")
                restored_mobile = page.evaluate(
                    """() => {
                      const header = document.querySelector(".site-header").getBoundingClientRect();
                      const title = document.querySelector(".hero h1").getBoundingClientRect();
                      const stats = [...document.querySelectorAll(".hero-stats article")].map((el) => el.getBoundingClientRect());
                      const theme = document.querySelector(".mobile-header-theme");
                      return {
                        heroOffset: title.top - header.bottom,
                        firstY: stats[0]?.top,
                        secondY: stats[1]?.top,
                        thirdY: stats[2]?.top,
                        fourthY: stats[3]?.top,
                        themeVisible: theme ? getComputedStyle(theme).display !== "none" : false,
                        themeTop: theme ? theme.getBoundingClientRect().top : -1,
                        menuTop: document.querySelector(".mobile-nav").getBoundingClientRect().top,
                        logoWidth: document.querySelector(".brand-mark").getBoundingClientRect().width,
                      };
                    }"""
                )
                if not 24 <= restored_mobile["heroOffset"] <= 110:
                    raise AssertionError(f"Mobile hero spacing is unreasonable: {restored_mobile}")
                if (
                    abs(restored_mobile["firstY"] - restored_mobile["secondY"]) > 3
                    or abs(restored_mobile["thirdY"] - restored_mobile["fourthY"]) > 3
                    or restored_mobile["thirdY"] <= restored_mobile["firstY"]
                ):
                    raise AssertionError(f"Mobile homepage statistics are not a balanced 2x2 grid: {restored_mobile}")
                if not restored_mobile["themeVisible"]:
                    raise AssertionError("Mobile light/dark control is not directly visible in the header")
                if restored_mobile["logoWidth"] < 40:
                    raise AssertionError(f"Mobile logo is undersized: {restored_mobile}")
                if abs(restored_mobile["themeTop"] - restored_mobile["menuTop"]) > 8:
                    raise AssertionError(f"Mobile theme and menu controls are not on the same row: {restored_mobile}")
                skip_link = page.locator(".skip-link")
                page.evaluate("window.scrollTo(0, 0)")
                page.keyboard.press("Tab")
                if not skip_link.evaluate("(el) => document.activeElement === el"):
                    raise AssertionError("Production skip-link is not first in keyboard navigation")
                if skip_link.evaluate("(el) => el.getBoundingClientRect().top") < 0:
                    raise AssertionError("Production skip-link is not visible for keyboard focus")
                page.keyboard.press("Tab")
                page.locator(".mobile-nav > summary").click()
                if not page.locator(".mobile-nav-panel").is_visible():
                    raise AssertionError("Production mobile menu did not open")
                mobile_theme = page.locator(".mobile-nav-panel [data-theme-toggle]")
                mobile_theme.click()
                if page.locator("html").get_attribute("data-theme") != "light":
                    raise AssertionError("Production mobile theme toggle did not switch to light mode")
                assert_visual_contrast(
                    page,
                    ".action-card",
                    ".action-card strong",
                    "Mobile light-theme action card with menu open",
                )
                page.screenshot(path=OUT / "home-mobile-light-menu.png", full_page=True)
                mobile_theme.click()
                if page.locator("html").get_attribute("data-theme") != "dark":
                    raise AssertionError("Production mobile theme toggle did not restore dark mode")
                assert_visual_contrast(
                    page,
                    ".action-card",
                    ".action-card strong",
                    "Mobile dark-theme action card with menu open",
                )
                page.screenshot(path=OUT / "home-mobile-menu.png", full_page=True)
                page.evaluate("window.scrollTo(0, 320)")
                page.wait_for_timeout(150)
                if page.locator(".mobile-nav").get_attribute("open") is not None:
                    raise AssertionError("Production mobile menu stays open after scroll")
                skip_top = skip_link.evaluate("(el) => el.getBoundingClientRect().top")
                if skip_top >= 0:
                    raise AssertionError("Production skip-link should remain hidden after pointer/scroll interactions")
                verify_featured_images(page, "home-mobile")
            if label == "kennels" and page.locator(".kennel-card").count() > 24:
                raise AssertionError("Mobile kennel directory renders more than 24 cards at once")
            if label == "pedigrees" and page.locator(".pedigree-index-card").count() > 18:
                raise AssertionError("Mobile pedigree browser renders more than 18 cards at once")
            if label == "dogs":
                if page.locator(".search-result-card .verification-pill").count():
                    raise AssertionError("Dog search still shows verification badges")
                search = page.locator("#q")
                search.fill("Bran")
                page.locator(".dog-suggestion").first.wait_for(state="visible", timeout=10_000)
                if "BRAN" not in page.locator(".dog-suggestion").first.inner_text().upper():
                    raise AssertionError("Production dog autocomplete returned an unexpected suggestion")
            if label in {"login", "signup", "password-reset"}:
                auth_offset = page.evaluate(
                    """() => {
                      const header = document.querySelector(".site-header").getBoundingClientRect();
                      const card = document.querySelector(".auth-card").getBoundingClientRect();
                      return card.top - header.bottom;
                    }"""
                )
                if not 16 <= auth_offset <= 90:
                    raise AssertionError(f"{label} mobile auth card spacing is unreasonable: {auth_offset}")
            page.close()

        if kennel_detail_path:
            kennel_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            kennel_response, kennel_elapsed = wait_for_real_app(
                kennel_mobile, kennel_detail_path + "?smoke=mobile"
            )
            assert_page(kennel_mobile, "kennel-detail-mobile", mobile=True)
            kennel_mobile.screenshot(path=OUT / "kennel-detail-mobile.png", full_page=True)
            report["details"].append({
                "kennel_detail_mobile": kennel_mobile.url,
                "seconds": round(kennel_elapsed, 3),
                "server_timing": kennel_response.headers.get("server-timing") if kennel_response else None,
            })
            kennel_mobile.close()

        if litter_detail_path:
            litter_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            litter_response, litter_elapsed = wait_for_real_app(
                litter_mobile, litter_detail_path + "?smoke=mobile"
            )
            assert_page(litter_mobile, "litter-detail-mobile", mobile=True)
            litter_mobile.screenshot(path=OUT / "litter-detail-mobile.png", full_page=True)
            report["details"].append({
                "litter_detail_mobile": litter_mobile.url,
                "seconds": round(litter_elapsed, 3),
                "server_timing": litter_response.headers.get("server-timing") if litter_response else None,
            })
            litter_mobile.close()

        touch_search = browser.new_page(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        wait_for_real_app(touch_search, "/dogs/?q=")
        touch_input = touch_search.locator("#q")
        touch_input.fill("Bran")
        touch_option = touch_search.locator(".dog-suggestion").first
        touch_option.wait_for(state="visible", timeout=10_000)
        expected_href = touch_option.get_attribute("href")
        if not expected_href or not expected_href.startswith("/dogs/"):
            raise AssertionError(
                f"Dog autocomplete suggestion has no navigable profile link: {expected_href}"
            )
        with touch_search.expect_navigation(wait_until="domcontentloaded", timeout=45_000) as nav:
            touch_option.tap()
        touch_response = nav.value
        if touch_response and touch_response.headers.get("x-cca-edge-warming"):
            raise AssertionError("Dog suggestion tap opened an edge database-warming page")
        if "/dogs/" not in touch_search.url or "source=search" not in touch_search.url:
            raise AssertionError(
                f"Dog suggestion tap did not navigate to the selected profile: {touch_search.url}"
            )
        assert_page(touch_search, "dog-autocomplete-tap-mobile", mobile=True)
        if "CONNECTING TO THE PEDIGREE DATABASE" in touch_search.locator("body").inner_text().upper():
            raise AssertionError("Dog suggestion tap exposed the database-warming interstitial")
        touch_search.close()

        if dog_load_path:
            dog_mobile = browser.new_page(viewport={"width": 390, "height": 844})
            dog_response, dog_elapsed = wait_for_real_app(
                dog_mobile, dog_load_path + "?smoke=mobile"
            )
            assert_page(dog_mobile, "dog-profile-mobile", mobile=True)
            dog_height = dog_mobile.evaluate("() => document.documentElement.scrollHeight")
            if dog_height > 6500:
                raise AssertionError(f"Mobile dog profile is excessively long: {dog_height}px")
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
            pedigree_columns = pedigree_mobile.locator(".pedigree-column")
            if pedigree_columns.count() > 1:
                first_box = pedigree_columns.nth(0).bounding_box()
                second_box = pedigree_columns.nth(1).bounding_box()
                if not first_box or not second_box or second_box["x"] <= first_box["x"] + first_box["width"]:
                    raise AssertionError("Mobile pedigree generations are stacked instead of horizontal boxes")
                overflow_x = pedigree_mobile.locator(".pedigree-scroll").evaluate(
                    "(el) => getComputedStyle(el).overflowX"
                )
                if overflow_x not in ("auto", "scroll"):
                    raise AssertionError(f"Mobile pedigree tree is not horizontally scrollable: {overflow_x}")
                compact_tree = pedigree_mobile.evaluate(
                    """() => {
                      const board = document.querySelector(".pedigree-board").getBoundingClientRect();
                      const columns = [...document.querySelectorAll(".pedigree-column")]
                        .filter((el) => getComputedStyle(el).display !== "none");
                      const nodes = [...document.querySelectorAll(".pedigree-node")]
                        .filter((el) => getComputedStyle(el).display !== "none");
                      return {
                        boardHeight: board.height,
                        visibleColumns: columns.length,
                        maxNodeHeight: Math.max(...nodes.map((el) => el.getBoundingClientRect().height)),
                      };
                    }"""
                )
                if compact_tree["boardHeight"] > 820:
                    raise AssertionError(f"Mobile pedigree is still vertically stretched: {compact_tree}")
                if compact_tree["visibleColumns"] > 5:
                    raise AssertionError(f"Mobile pedigree exposes too many deep columns at once: {compact_tree}")
                if compact_tree["maxNodeHeight"] > 50:
                    raise AssertionError(f"Mobile pedigree boxes are not compact: {compact_tree}")
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

    report["virtual_mating"] = live_virtual_mating_probe()
    report["concurrency"] = {
        "health": concurrent_health_probe(),
        "dog_profile": concurrent_profile_probe(dog_load_path),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
