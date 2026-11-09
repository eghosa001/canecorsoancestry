"""Classic pedigree layout regression: PDF replaces CSV without changing ancestry."""
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]


class ClassicPedigreeLayoutContractTests(SimpleTestCase):
    def test_public_and_private_pedigree_restore_simple_columns_with_pdf(self):
        for relative, pdf_route in (
            ("pedigrees/templates/pedigrees/pedigree_detail.html", "pedigrees:export-pdf"),
            ("accounts/templates/accounts/member_pedigree_detail.html", "accounts:member-pedigree-export-pdf"),
        ):
            with self.subTest(relative=relative):
                template = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn('class="pedigree-board"', template)
                self.assertIn('class="pedigree-column"', template)
                self.assertIn("layer.display_nodes", template)
                self.assertIn(pdf_route, template)
                self.assertIn("Download pedigree (PDF)", template)
                self.assertNotIn("Download pedigree data (CSV)", template)
                self.assertNotIn("Export data (CSV)", template)
                self.assertNotIn("cca-tree-tools", template)
                self.assertNotIn("cca-tree-legend", template)
                self.assertNotIn("heritage-pedigree.js", template)
                self.assertIn('{% include "pedigrees/_analysis_report.html" %}', template)
