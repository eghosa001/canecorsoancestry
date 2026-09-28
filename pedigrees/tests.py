from django.test import TestCase

from registry.models import Dog

from .services import repeated_ancestors


class PedigreeServiceTests(TestCase):
    def test_repeated_ancestor_uses_one_canonical_dog_record(self):
        common = Dog.objects.create(name="Common Ancestor", slug="common", sex=Dog.Sex.MALE)
        sire = Dog.objects.create(name="Sire", slug="sire", sire=common)
        dam = Dog.objects.create(name="Dam", slug="dam", sire=common)
        child = Dog.objects.create(name="Child", slug="child", sire=sire, dam=dam)

        repeated = repeated_ancestors(child, generations=3)

        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["dog"].pk, common.pk)
        self.assertEqual(repeated[0]["occurrences"], 2)
