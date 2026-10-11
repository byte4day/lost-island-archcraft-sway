import unittest

from lostisland.services.clipboard import MAX_CHARS, add_entry, preview


class ClipboardHistoryTest(unittest.TestCase):
    def test_newest_first_and_duplicates_move_up(self):
        history = []
        for text in ("one", "two", "one"):
            add_entry(history, text)
        self.assertEqual(history, ["one", "two"])

    def test_repeat_of_top_entry_is_ignored(self):
        history = ["same"]
        self.assertFalse(add_entry(history, "same"))

    def test_blank_and_huge_text_is_ignored(self):
        history = []
        self.assertFalse(add_entry(history, "  \n"))
        self.assertFalse(add_entry(history, "x" * (MAX_CHARS + 1)))
        self.assertEqual(history, [])

    def test_history_is_capped(self):
        history = []
        for i in range(30):
            add_entry(history, str(i), limit=5)
        self.assertEqual(history, ["29", "28", "27", "26", "25"])

    def test_preview_collapses_whitespace_and_cuts(self):
        self.assertEqual(preview("a\n  b\tc"), "a b c")
        self.assertEqual(preview("x" * 70, width=10), "x" * 9 + "…")


if __name__ == "__main__":
    unittest.main()
