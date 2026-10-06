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


def assert_mobile_header(page, label):
    if page.evaluate("() => window.innerWidth > 760 || !document.querySelector('.site-header')"):
        return
    state = page.evaluate(
        """() => ({
          mainNav: getComputedStyle(document.querySelector(".main-nav")).display,
          actions: getComputedStyle(document.querySelector(".header-actions")).display,
          mobileNav: getComputedStyle(document.querySelector(".mobile-nav")).display,
        })"""
    )
    if state["mainNav"] != "none" or state["actions"] != "none" or state["mobileNav"] == "none":
        raise AssertionError(f"{label} mobile header visibility is wrong: {state}")


def assert_basic_accessibility(page, label):
    issues = page.evaluate(
        """() => {
          const issues = [];
          if (document.documentElement.lang !== "en") issues.push("document language missing");
          const ids = [...document.querySelectorAll("[id]")].map((el) => el.id);
          const duplicateIds = ids.filter((id, index) => ids.indexOf(id) !== index);
          if (duplicateIds.length) issues.push("duplicate ids: " + [...new Set(duplicateIds)].join(", "));
          const images = [...document.querySelectorAll("img:not([alt])")];
          if (images.length) issues.push(images.length + " image(s) missing alt attributes");
          const unnamed = [...document.querySelectorAll("button, a[href]")].filter((el) => {
            const name = (el.getAttribute("aria-label") || el.textContent || "").trim();
            return !name && !el.querySelector("img[alt]");
          });
          if (unnamed.length) issues.push(unnamed.length + " unnamed link/button control(s)");
          const controls = [...document.querySelectorAll("input:not([type=hidden]), select, textarea")];
          const unlabeled = controls.filter((el) => {
            if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby")) return false;
            if (!el.id) return true;
            return !document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
          });
          if (unlabeled.length) {
            issues.push(
              "unlabeled form controls: " +
              unlabeled.slice(0, 8).map((el) => el.outerHTML).join(" || ")
            );
          }
          return issues;
        }"""
    )
    if issues:
        raise AssertionError(f"{label} accessibility issues: {issues}")


def screenshot(page, label, overflow=True):
    page.locator("main").wait_for(state="visible")
    if overflow:
        assert_no_global_overflow(page, label)
    assert_basic_accessibility(page, label)
    assert_mobile_header(page, label)
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
    page.locator("#id_username").fill("ui-reviewer@example.com")
    page.locator("#id_password").fill("ui-reviewer-password")
    login_form = page.locator("form").filter(has=page.locator("#id_username"))
    login_form.locator("button[type=submit]").click()
    page.wait_for_url("**/dashboard/")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        capture(desktop, "/", "home-desktop")
        brand = desktop.locator(".brand-mark")
        logo_src = brand.get_attribute("src") or ""
        if "cane-corso-head-logo-right.webp" not in logo_src or logo_src.startswith("data:"):
            raise AssertionError(f"customer Cane Corso logo asset is wrong: {logo_src}")
        if brand.evaluate("(el) => !el.complete || el.naturalWidth < 32 || el.naturalHeight < 32"):
            raise AssertionError("customer Cane Corso logo did not render correctly")
        plaque = desktop.locator(".hero-mark")
        if plaque.evaluate("(el) => getComputedStyle(el).borderTopWidth") != "1px":
            raise AssertionError("CCA plaque is not visibly boxed")
        desktop.locator("[data-theme-toggle]").first.click()
        if desktop.locator("html").get_attribute("data-theme") != "light":
            raise AssertionError("desktop theme toggle did not switch to light mode")
        screenshot(desktop, "home-desktop-light")
        desktop.locator("[data-theme-toggle]").first.click()
        if desktop.locator("html").get_attribute("data-theme") != "dark":
            raise AssertionError("desktop theme toggle did not switch back to dark mode")
        capture(desktop, "/accounts/login/", "login-desktop")
        capture(desktop, "/member/signup/", "signup-desktop")
        capture(desktop, "/accounts/password_reset/", "password-reset-desktop")
        capture(desktop, "/dogs/?q=", "dogs-desktop")
        capture(desktop, "/kennels/", "kennels-desktop")
        capture(desktop, "/pedigrees/virtual-mating/", "virtual-mating-desktop")
        capture(desktop, "/statistics/", "statistics-desktop")

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
        kennel_edit = desktop.locator('a[href*="/member/kennels/"][href$="/edit/"]')
        if kennel_edit.count():
            kennel_edit.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "kennel-edit-desktop")
            desktop.goto(f"{BASE_URL}/dashboard/", wait_until="networkidle")

        capture(desktop, "/member/submissions/", "submissions-desktop")
        capture(desktop, "/member/notifications/", "notifications-desktop")
        capture(desktop, "/member/payments/new/?package=single_dog", "payment-new-desktop")
        capture(desktop, "/member/submit/kennel/", "submit-kennel-desktop")
        capture(desktop, "/member/pedigrees/", "my-pedigrees-desktop")
        member_pedigrees = desktop.locator(".pedigree-workspace-card .btn-gold")
        if member_pedigrees.count():
            member_pedigrees.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "member-pedigree-detail-desktop", overflow=False)

        capture(desktop, "/member/litters/", "my-litters-desktop")
        litter_edit = desktop.locator('a[href*="/member/litters/"][href$="/edit/"]')
        if litter_edit.count():
            litter_edit.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "litter-edit-desktop")

        capture(desktop, "/member/documents/", "documents-desktop")
        visibility = desktop.locator('a[href*="/member/documents/"][href$="/visibility/"]')
        if visibility.count():
            visibility.first.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "document-visibility-desktop")

        capture(desktop, "/member/moderation/", "moderation-desktop")
        review_link = desktop.locator('a[href*="/member/moderation/submissions/"]').first
        if review_link.count():
            review_link.click()
            desktop.wait_for_load_state("networkidle")
            screenshot(desktop, "moderation-submission-desktop")
        capture(desktop, "/member/moderation/audit/", "moderation-audit-desktop")
        capture(desktop, "/member/moderation/data-health/", "data-health-desktop")
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
        if mobile.locator(".hero h1 br").count():
            raise AssertionError("mobile hero title still contains a literal line break")
        title_stack = mobile.evaluate(
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
            raise AssertionError(f"mobile CORSO line is not stacked: {title_stack}")
        if title_stack["gap"] > 8:
            raise AssertionError(f"mobile hero title has an oversized line gap: {title_stack}")
        mobile.locator(".mobile-nav > summary").click()
        mobile_panel = mobile.locator(".mobile-nav-panel")
        mobile_panel.locator("[data-theme-toggle]").click()
        if mobile.locator("html").get_attribute("data-theme") != "light":
            raise AssertionError("mobile theme toggle did not switch to light mode")
        screenshot(mobile, "home-mobile-light-menu")
        mobile_panel.locator("[data-theme-toggle]").click()
        if mobile.locator("html").get_attribute("data-theme") != "dark":
            raise AssertionError("mobile theme toggle did not switch back to dark mode")
        if not mobile_panel.get_by_role("link", name="Sign in", exact=True).is_visible():
            raise AssertionError("home-mobile-menu does not expose Sign in")
        if not mobile_panel.get_by_role("link", name="Join", exact=True).is_visible():
            raise AssertionError("home-mobile-menu does not expose Join")
        screenshot(mobile, "home-mobile-menu")
        mobile.evaluate("window.scrollTo(0, 360)")
        mobile.wait_for_timeout(150)
        if mobile.locator(".mobile-nav").get_attribute("open") is not None:
            raise AssertionError("home-mobile-menu stays open after page scroll")
        mobile.evaluate("window.scrollTo(0, 0)")

        capture(mobile, "/accounts/login/", "login-mobile")
        capture(mobile, "/member/signup/", "signup-mobile")
        capture(mobile, "/accounts/password_reset/", "password-reset-mobile")

        capture(mobile, "/dogs/?q=", "dogs-mobile")
        dog_search = mobile.locator("#q")
        dog_search.focus()
        mobile.locator("h1").click()
        if mobile.evaluate("document.activeElement && document.activeElement.id") == "q":
            raise AssertionError("mobile dog search stays focused after outside tap")
        dog_search.focus()
        mobile.evaluate("window.scrollTo(0, 320)")
        mobile.wait_for_timeout(100)
        if mobile.evaluate("document.activeElement && document.activeElement.id") == "q":
            raise AssertionError("mobile dog search stays focused after upward page movement")
        mobile.evaluate("window.scrollTo(0, 0)")

        mobile_dogs = mobile.locator(".search-result-card")
        if mobile_dogs.count():
            mobile_dogs.first.click()
            mobile.wait_for_load_state("networkidle")
            screenshot(mobile, "dog-profile-mobile")

        capture(mobile, "/kennels/", "kennels-mobile")
        capture(mobile, "/pedigrees/", "pedigrees-mobile")
        mobile_pedigrees = mobile.locator(".pedigree-index-card")
        if mobile_pedigrees.count():
            mobile_pedigrees.first.click()
            mobile.wait_for_load_state("networkidle")
            mobile.locator(".analysis-mobile-summary").wait_for(state="visible")
            relationships = mobile.locator(".pedigree-relationship")
            if relationships.count() and not relationships.first.is_visible():
                raise AssertionError("mobile pedigree relationship labels are not visible")
            screenshot(mobile, "pedigree-detail-mobile", overflow=False)

        capture(mobile, "/pedigrees/virtual-mating/", "virtual-mating-mobile")
        sire_search = mobile.locator("#sire_q")
        sire_host = sire_search.locator("xpath=..")
        sire_suggestions = sire_host.locator(".dog-suggestions")
        sire_search.fill("Bran")
        sire_suggestions.wait_for(state="visible")
        if not sire_suggestions.locator(".dog-suggestion").count():
            raise AssertionError("virtual mating autocomplete returned no sire suggestions")
        sire_suggestions.locator(".dog-suggestion").first.click()
        if not mobile.locator("#sire").input_value():
            raise AssertionError("virtual mating autocomplete did not select a sire id")
        capture(mobile, "/statistics/", "statistics-mobile")

        login(mobile)
        screenshot(mobile, "dashboard-mobile")
        if mobile.locator(".dashboard-panel .verification-pill").count():
            raise AssertionError("dashboard dog cards still show verification badges")
        dashboard_menu = mobile.locator(".dashboard-mobile-nav > summary")
        if not dashboard_menu.is_visible():
            raise AssertionError("dashboard mobile navigation is not visible")
        dashboard_menu.click()
        screenshot(mobile, "dashboard-mobile-menu")
        capture(mobile, "/member/pedigrees/", "my-pedigrees-mobile")
        member_mobile = mobile.locator(".pedigree-workspace-card .btn-gold")
        if member_mobile.count():
            member_mobile.first.click()
            mobile.wait_for_load_state("networkidle")
            mobile.locator(".analysis-mobile-summary").wait_for(state="visible")
            screenshot(mobile, "member-pedigree-detail-mobile", overflow=False)
        capture(mobile, "/member/litters/", "my-litters-mobile")
        capture(mobile, "/member/documents/", "documents-mobile")
        capture(mobile, "/member/submissions/", "submissions-mobile")
        capture(mobile, "/member/notifications/", "notifications-mobile")
        capture(mobile, "/member/moderation/", "moderation-mobile")
        capture(mobile, "/member/moderation/data-health/", "data-health-mobile")
        capture(mobile, "/member/disputes/", "my-disputes-mobile")
        capture(mobile, "/member/submit/dog/", "submit-dog-mobile")

        browser.close()


if __name__ == "__main__":
    main()
