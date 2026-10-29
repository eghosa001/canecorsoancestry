"""Playwright browser audit against a disposable local Django database.

Does not create accounts, approve records, or run payments in production.
"""
import json
import os
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE = os.getenv("CCA_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUT = Path("artifacts/role-browser-audit")
OUT.mkdir(parents=True, exist_ok=True)
DATA = json.loads(Path("/tmp/cca-playwright-audit-credentials.json").read_text())
passed, failed = [], []


def check(name, fn, page=None):
    try:
        fn()
        passed.append(name)
        print(f"PASS {name}", flush=True)
    except Exception as exc:
        failed.append({"case": name, "error": str(exc)})
        print(f"FAIL {name}: {exc}", flush=True)
        if page:
            try:
                page.screenshot(path=OUT / f"failure-{len(failed)}.png", full_page=True)
            except Exception:
                pass


def visit(page, path, expected=200):
    response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
    assert response is not None, f"{path}: no HTTP response"
    assert response.status == expected, (
        f"{path}: HTTP {response.status} (expected {expected}), final URL {page.url}"
    )
    if expected == 200 and not path.startswith(("/admin/", "/dogs/suggestions/")):
        assert page.locator("main").count(), f"{path}: main content missing"
    return response


def no_overflow(page, label):
    over = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
    assert over <= 4, f"{label}: {over}px horizontal overflow"


def assert_original_readable_type(page, label):
    """Catch tiny text regressions in both light and dark and on WebKit."""
    metrics = page.evaluate("""() => {
      const size = (selector) => {
        const node = document.querySelector(selector);
        return node ? parseFloat(getComputedStyle(node).fontSize) : null;
      };
      return {
        body: size('body'),
        hero: size('.hero h1'),
        lead: size('.hero-copy > p:not(.eyebrow)'),
        section: size('.home-actions .section-heading h2'),
        card: size('.home-actions .action-card strong'),
      };
    }""")
    expected = {
        "body": 17, "hero": 44, "lead": 17,
        "section": 26, "card": 20,
    }
    if page.viewport_size["width"] > 760:
        expected["hero"] = 56
        expected["section"] = 28
    for key, threshold in expected.items():
        value = metrics[key]
        assert value is not None and value >= threshold - 0.2, (
            f"{label}: {key} text {value}px smaller than agreed "
            f"{threshold}px restoration"
        )
    no_overflow(page, label + " restored typography")


def login(page, role):
    visit(page, "/accounts/login/")
    credentials = DATA["roles"][role]
    page.locator("#id_username").fill(credentials["email"])
    page.locator("#id_password").fill(credentials["password"])
    form = page.locator("form").filter(has=page.locator("#id_username")).first
    form.locator("button[type=submit]").click()
    page.wait_for_load_state("domcontentloaded")
    assert "/accounts/login/" not in page.url, (
        f"{role} could not log in: " + page.locator("body").inner_text()[-500:]
    )


def public_routes(page, label):
    for path in (
        "/", "/dogs/?q=Browser%20Audit", "/kennels/", "/pedigrees/",
        "/pedigrees/virtual-mating/", "/statistics/", "/member/signup/",
        "/accounts/login/", "/accounts/password_reset/",
        "/dogs/browser-audit-offspring/", "/pedigrees/browser-audit-offspring/",
    ):
        visit(page, path)
        no_overflow(page, label + path)
    visit(page, "/dogs/?q=Browser%20Audit%20Private")
    assert not any(
        "Browser Audit Private" in card
        for card in page.locator(".search-result-card").all_inner_texts()
    ), "Private unpublished dog appears in public result cards"
    visit(page, "/dogs/?q=Browser%20Audit%20Offspring")
    assert "Browser Audit Offspring" in page.locator("main").inner_text(), (
        "Published photo-less dog cannot be found by name"
    )
    response = visit(page, "/dogs/suggestions/?q=" + quote("Browser Audit Private"))
    assert "Browser Audit Private" not in response.text(), (
        "Private unpublished dog leaked through suggestions API"
    )
    response = visit(page, "/dogs/suggestions/?q=" + quote("Browser Audit Sire"))
    assert "Browser Audit Sire" in response.text(), "Published dog missing from autocomplete"
    visit(page, "/")
    assert_original_readable_type(page, label + "-light")
    if page.viewport_size["width"] <= 760:
        page.locator(".mobile-nav > summary").click()
        theme = page.locator(".mobile-nav-panel [data-theme-toggle]").first
    else:
        theme = page.locator("[data-theme-toggle]").first
    before = page.locator("html").get_attribute("data-theme")
    theme.click()
    after = page.locator("html").get_attribute("data-theme")
    assert before != after, f"Theme toggle inactive: {before} to {after}"
    assert_original_readable_type(page, label + "-dark")
    page.screenshot(path=OUT / f"{label}-home.png", full_page=True)


def guest_permissions(page):
    visit(page, "/member/profile/")
    assert "/accounts/login/" in page.url, "Anonymous profile did not require login"
    visit(page, "/member/moderation/")
    assert "/accounts/login/" in page.url, "Anonymous moderation did not require login"
    visit(page, "/member/moderation/change-center/")
    assert "/accounts/login/" in page.url, "Anonymous change center did not require login"
    visit(page, "/admin/")
    assert "/admin/login/" in page.url, "Anonymous Django admin did not require login"


def member_routes(page):
    login(page, "member")
    for path in (
        "/dashboard/", "/member/profile/", "/member/submissions/",
        "/member/notifications/", "/member/pedigrees/", "/member/litters/",
        "/member/documents/", "/member/disputes/",
        "/member/research/pairings/", "/member/submit/kennel/",
        "/member/submit/dog/", "/member/payments/new/?package=single_dog",
    ):
        visit(page, path)
    visit(page, "/member/moderation/", expected=403)
    visit(page, "/member/moderation/change-center/", expected=403)
    visit(page, "/member/moderation/merge-dogs/", expected=403)
    visit(page, "/admin/")
    assert "/admin/login/" in page.url, "Member accessed Django admin"
    visit(page, "/dashboard/")
    page.screenshot(path=OUT / "member-dashboard.png", full_page=True)


def moderator_routes(page, role):
    login(page, role)
    visit(page, "/member/moderation/change-center/")
    assert page.get_by_role("heading", name="Change & administration center").is_visible()
    assert not page.get_by_text("Permanently deregister a moderator").count(), (
        "Non-owner account can see permanent moderator removal"
    )
    search = page.locator("#staff-center-search")
    search.fill("health")
    assert page.locator("[data-change-action]:visible").count() > 0, "Health editor search returned no results"
    assert page.get_by_text("Enter or change verified health numbers").is_visible()
    search.fill("impossible-unmatched-admin-setting-abcdefgh")
    assert page.locator("#staff-center-empty").is_visible(), "No-result state is not functional"
    assert page.locator("#staff-center-result-count").inner_text() == "0 matching actions"
    assert page.locator(".staff-center-index a:visible").count() == 0
    page.locator("#staff-center-clear").click()
    assert search.input_value() == "", "Clear search did not reset the editing directory"
    assert page.locator("[data-change-action]:visible").count() > 5
    assert "editing actions available" in page.locator("#staff-center-result-count").inner_text()
    search.fill("health")
    page.locator("[data-change-action]").filter(
        has_text="Enter or change verified health numbers"
    ).get_by_role("link", name="Open this editor").click()
    page.wait_for_load_state("domcontentloaded")
    assert "/member/moderation/dogs/" in page.url, "Health editing destination is broken"
    no_overflow(page, role + "-change-center")
    for path in (
        "/member/moderation/", "/member/moderation/dogs/",
        "/member/moderation/audit/", "/member/moderation/data-health/",
        f"/member/moderation/submissions/{DATA['submission_id']}/",
    ):
        visit(page, path)
    visit(page, "/member/profile/", expected=403)
    visit(page, "/member/moderation/merge-dogs/", expected=403)
    visit(page, "/admin/")
    assert "/admin/login/" in page.url, f"{role} unexpectedly accessed Django admin"
    if role == "moderator":
        # Real POST through the moderator's visible button; the newly
        # published kennel must be visible on the NEXT public GET.
        visit(page, f"/member/moderation/submissions/{DATA['submission_id']}/")
        approve = page.get_by_role("button", name="Approve", exact=True)
        assert approve.is_visible(), "Clean kennel submission lacks approval action"
        approve.click()
        page.wait_for_load_state("domcontentloaded")
        visit(page, "/kennels/browser-pending-kennel/")
        assert "Browser Pending Kennel" in page.locator("main").inner_text(), (
            "Approved kennel not visible immediately on public site"
        )
    visit(page, "/member/moderation/")
    page.screenshot(path=OUT / f"{role}-moderation.png", full_page=True)


def super_admin_routes(page, do_merge=False):
    login(page, "owner")
    visit(page, "/member/moderation/change-center/")
    assert page.get_by_text("Permanently deregister a moderator").is_visible()
    page.locator("#staff-center-search").fill("deregister")
    assert page.locator("[data-change-action]:visible").count() == 1, "Staff search did not filter results"
    page.locator("[data-change-action]:visible").get_by_role("link", name="Open this editor").click()
    page.wait_for_load_state("domcontentloaded")
    assert page.url.endswith("#staff-accounts"), "Moderator deletion link misses the account section"
    assert page.locator("#staff-accounts").get_attribute("open") is not None, (
        "Deep-linked staff account form is not expanded"
    )
    visit(page, f"/member/moderation/dogs/{DATA['merge_canonical']}/edit/#revision-history")
    assert page.locator("#revision-history").get_attribute("open") is not None, (
        "Deep-linked dog revision history must expand on demand"
    )
    assert page.locator("[data-edit-clean]").is_visible(), "Saved-state feedback is hidden"
    bio = page.locator('[data-edit-form] [name="bio"]')
    bio.fill("Browser audit draft — not submitted")
    assert page.locator("[data-edit-dirty]").is_visible(), (
        "Staff cannot distinguish unsaved edits from the saved database state"
    )
    assert not page.locator("[data-edit-clean]").is_visible()
    page.screenshot(path=OUT / "super-admin-edit-draft.png", full_page=True)
    for path in (
        "/member/moderation/", "/member/moderation/dogs/",
        "/member/moderation/verification/",
        "/member/moderation/merge-dogs/", "/member/moderation/audit/",
        "/member/moderation/data-health/", "/admin/", "/admin/merge-dogs/",
        f"/member/moderation/submissions/{DATA['submission_id']}/",
    ):
        visit(page, path)
    visit(page, "/member/profile/", expected=403)
    visit(page, "/member/moderation/merge-dogs/")
    page.screenshot(path=OUT / "super-admin-merge.png", full_page=True)
    if do_merge:
        # Merge only records generated by this isolated CI fixture.
        page.locator("#id_canonical").fill(DATA["merge_canonical"])
        page.locator("#id_duplicate").fill(DATA["merge_duplicate"])
        page.locator("#id_confirm_merge").check()
        page.get_by_role("button", name="Confirm and merge pedigrees").click()
        page.wait_for_load_state("domcontentloaded")
        visit(page, "/dogs/browser-audit-sire-copy/")
        assert "/dogs/browser-audit-sire/" in page.url, (
            "Retired duplicate does not redirect to the canonical profile"
        )
        visit(page, "/dogs/browser-audit-offspring/")
        assert "Browser Audit Offspring" in page.locator("main").inner_text(), (
            "Canonical dog's offspring disappeared after merge"
        )


def main():
    with sync_playwright() as playwright:
        runs = (
            ("chromium", {"viewport": {"width": 1366, "height": 900}}),
            ("chromium", {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}),
            ("webkit", {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}),
        )
        for index, (name, options) in enumerate(runs):
            browser = getattr(playwright, name).launch()
            label = f"{name}-{'desktop' if index == 0 else 'mobile'}"
            context = browser.new_context(**options)
            page = context.new_page()
            check(label + " public routes and theme", lambda: public_routes(page, label), page)
            context.close()
            context = browser.new_context(**options)
            page = context.new_page()
            check(label + " guest authorization", lambda: guest_permissions(page), page)
            context.close()
            # Check all four identities in real browsers; no staff/member overlap.
            for role, fn in (
                ("member", member_routes),
                ("moderator", lambda p: moderator_routes(p, "moderator")),
                ("senior", lambda p: moderator_routes(p, "senior")),
                ("owner", lambda p: super_admin_routes(p, do_merge=index == 0)),
            ):
                # Six login attempts in total: don't trigger real IP throttle
                # simply by testing all 4 roles in every emulator context.
                if index == 1 and role != "member":
                    continue
                if index == 2 and role != "owner":
                    continue
                context = browser.new_context(**options)
                page = context.new_page()
                check(label + " " + role + " workflows", lambda fn=fn, page=page: fn(page), page)
                context.close()
            browser.close()
    (OUT / "summary.json").write_text(json.dumps({
        "passed": passed, "failed": failed, "passed_count": len(passed),
        "failed_count": len(failed),
        "database": "disposable SQLite test database",
    }, indent=2))
    print(f"Browser role audit: {len(passed)} passed, {len(failed)} failed", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
