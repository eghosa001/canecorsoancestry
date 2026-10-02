from django.test import TestCase

from registry.models import Dog

from .forms import DogSubmissionForm


class ParentAutocompleteFormTests(TestCase):
    def setUp(self):
        self.sire = Dog.objects.create(
            name="Fast Sire",
            slug="fast-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Fast Dam",
            slug="fast-dam",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )

    def test_parent_fields_render_as_hidden_ids_with_search_inputs(self):
        form = DogSubmissionForm()

        self.assertEqual(form.fields["sire"].widget.input_type, "hidden")
        self.assertEqual(form.fields["dam"].widget.input_type, "hidden")
        self.assertEqual(
            form.fields["sire_q"].widget.attrs["data-dog-autocomplete-mode"],
            "fill",
        )
        with self.assertNumQueries(0):
            html = str(form["sire"])
        self.assertNotIn("<option", html)

    def test_exact_parent_names_resolve_without_loading_all_dogs(self):
        form = DogSubmissionForm(
            data={
                "name": "Fast Puppy",
                "sex": Dog.Sex.UNKNOWN,
                "sire": "",
                "sire_q": self.sire.name,
                "dam": "",
                "dam_q": self.dam.name,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sire"], self.sire)
        self.assertEqual(form.cleaned_data["dam"], self.dam)

    def test_ambiguous_name_requires_selecting_a_suggestion(self):
        Dog.objects.create(
            name=self.sire.name,
            slug="fast-sire-two",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        form = DogSubmissionForm(
            data={
                "name": "Fast Puppy",
                "sex": Dog.Sex.UNKNOWN,
                "sire": "",
                "sire_q": self.sire.name,
                "dam": "",
                "dam_q": self.dam.name,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("sire_q", form.errors)
