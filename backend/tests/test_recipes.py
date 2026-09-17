import unittest

from backend.recipes import normalize


class RecipeTests(unittest.TestCase):
    def test_recipe_is_normalized_and_clamped(self):
        recipe = normalize({"crop": {"x": 2, "y": -1, "width": .8, "height": .7}, "adjustments": {"temperature": "0.5"}, "filter": "none"})
        self.assertAlmostEqual(recipe["crop"]["x"], .2)
        self.assertEqual(recipe["crop"]["y"], 0)
        self.assertAlmostEqual(recipe["adjustments"]["temperature"], .5)
        self.assertEqual(normalize({"rotate": 90})["rotate"], 90)
        self.assertEqual(recipe["schema_version"], 1)

    def test_unknown_filter_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize({"filter": "invalid"})

    def test_portrait_filters_are_supported(self):
        for selected in ("portrait_soft", "portrait_warm", "portrait_clear", "portrait_mono", "portrait_cinematic", "kindle_16gray"):
            self.assertEqual(normalize({"filter": selected})["filter"], selected)


if __name__ == "__main__":
    unittest.main()
