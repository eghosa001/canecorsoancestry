from django.template.loader import get_template
from django.test import TestCase, override_settings


class ErrorPageTests(TestCase):
    @override_settings(DEBUG=False)
    def test_404_uses_branded_recovery_page(self):
        response = self.client.get("/this-route-does-not-exist-anywhere/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            "That page is not in the ancestry database.",
            status_code=404,
        )
        self.assertContains(response, "Search dogs", status_code=404)

    def test_500_template_is_available_and_branded(self):
        template = get_template("500.html")
        rendered = template.render({})
        self.assertIn("We could not complete that request.", rendered)
        self.assertIn("Return home", rendered)
