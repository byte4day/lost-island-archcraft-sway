import unittest

from lostisland.ui import layout


class LayoutTests(unittest.TestCase):
    def test_normalize_drops_unknown_and_duplicates(self):
        self.assertEqual(
            layout.normalize(["wifi", "nope", "wifi", "mic"], ["wifi", "mic"]),
            ["wifi", "mic"])

    def test_normalize_survives_a_broken_config(self):
        self.assertEqual(layout.normalize("wifi", ["wifi"]), [])

    def test_hidden_keeps_catalog_order(self):
        self.assertEqual(layout.hidden(["mic"], ["wifi", "mic", "lock"]),
                         ["wifi", "lock"])

    def test_add_and_remove(self):
        self.assertEqual(layout.add(["wifi"], "mic"), ["wifi", "mic"])
        self.assertEqual(layout.add(["wifi"], "wifi"), ["wifi"])
        self.assertEqual(layout.remove(["wifi", "mic"], "wifi"), ["mic"])

    def test_move_backward_lands_before_target(self):
        self.assertEqual(layout.move(["a", "b", "c", "d"], "d", "b"),
                         ["a", "d", "b", "c"])

    def test_move_forward_lands_after_target(self):
        self.assertEqual(layout.move(["a", "b", "c", "d"], "a", "c"),
                         ["b", "c", "a", "d"])

    def test_move_to_end_and_onto_itself(self):
        self.assertEqual(layout.move(["a", "b", "c"], "a", None),
                         ["b", "c", "a"])
        self.assertEqual(layout.move(["a", "b"], "a", "a"), ["a", "b"])

    def test_defaults_are_known_controls(self):
        for key in layout.DEFAULT_CONTROLS:
            self.assertIn(key, layout.CONTROLS)
        self.assertEqual(len(layout.DEFAULT_CONTROLS), 2 * layout.COLUMNS)


if __name__ == "__main__":
    unittest.main()
