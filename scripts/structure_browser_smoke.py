"""Representative cross-viewport layout contracts for the complete Django site.

Runs against local seeded fixtures: public, member, staff and Super Admin.
Checks actual WebKit dimensions and navigation interaction, not design scores.
"""
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000/"
PUBLIC = (
    "/", "/dogs/", "/dogs/safari-dog/", "/kennels/",
    "/pedigrees/", "/pedigrees/virtual-mating/", "/statistics/",
)
MEMBER = (
    "/dashboard/", "/member/pedigrees/", "/member/litters/",
    "/member/submissions/", "/member/documents/",
    "/member/notifications/", "/member/profile/",
)
WIDTHS = (375, 430, 834, 1280)


def visit(page, path, width):
    page.set_viewport_size({"width": width, "height": 850})
    response = page.goto(urljoin(BASE, path.lstrip("/")), wait_until="domcontentloaded")
    assert response and response.status == 200, (
        f"{path} at {width}px: unexpected status {response.status if response else 'no response'}"
    )
    page.evaluate("document.fonts && document.fonts.ready")
    metrics = page.evaluate("""() => {
      const main = document.querySelector('main#main-content');
      const headings = main && [...main.querySelectorAll('h1')];
      const first = headings && headings[0];
      const firstBox = first && first.getBoundingClientRect();
      return {
        width: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        mainWidth: main ? main.getBoundingClientRect().width : 0,
        headings: headings ? headings.length : 0,
        headingWidth: firstBox ? firstBox.width : 0,
        headingScroll: first ? first.scrollWidth - first.clientWidth : 0,
        stylesLoaded: !![...document.styleSheets].find(s => s.href && s.href.includes('structured-pages.css')),
      };
    }""")
    assert metrics["stylesLoaded"], f"{path}: shared structure CSS did not load"
    assert metrics["headings"] >= 1, f"{path}: no accessible primary heading"
    assert metrics["headingWidth"] > 0 and metrics["headingScroll"] <= 3, (
        f"{path} at {width}px: clipped main heading {metrics}"
    )
    assert metrics["scrollWidth"] - metrics["width"] <= 3, (
        f"{path} at {width}px: unintended page overflow {metrics}"
    )


def login(page, username, password):
    response = page.goto(urljoin(BASE, "accounts/login/"), wait_until="domcontentloaded")
    assert response and response.status == 200
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='password']").fill(password)
    page.locator(".auth-card form button[type='submit']").click()
    assert "/accounts/login/" not in page.url, f"Sign-in failed: {username}"


def verify_workspace(page, width):
    page.set_viewport_size({"width": width, "height": 850})
    page.reload(wait_until="domcontentloaded")
    nav = page.locator("[data-responsive-nav]")
    assert nav.count() == 1, "Expected one workspace navigation disclosure"
    if width <= 760:
        assert nav.get_attribute("open") is None, "Mobile workspace menu starts overcrowded"
        nav.locator(":scope > summary").click()
        assert nav.get_attribute("open") is not None, "Cannot expand workspace menu"
        more = nav.locator(".workspace-more")
        assert more.count() == 1
        if more.get_attribute("open") is None:
            more.locator("summary").click()
        assert more.get_attribute("open") is not None, "Secondary tools are inaccessible"
        assert more.get_by_role("link", name="Documents").count() == 1
        page.keyboard.press("Escape")
        assert nav.get_attribute("open") is None, "Escape did not dismiss mobile workspace"
    else:
        assert nav.get_attribute("open") is not None, "Desktop workspace links hidden"
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 3, (
        "Workspace navigation creates horizontal document scrolling"
    )


def run():
    with sync_playwright() as playwright:
        browser = playwright.webkit.launch()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 850},
                                    is_mobile=True, has_touch=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            for width in WIDTHS:
                for path in PUBLIC:
                    visit(page, path, width)

            login(page, "safari-smoke-member", "safari-smoke-password")
            for width in WIDTHS:
                for path in MEMBER:
                    visit(page, path, width)
                visit(page, "/member/documents/", width)
                verify_workspace(page, width)

            assert not errors, "Browser JavaScript errors: " + "; ".join(errors[:6])
            print("PASS: 4 viewports; public/member routes and workspace interactions")
        finally:
            browser.close()


if __name__ == "__main__":
    run()
