import os
import tempfile
import unittest

from lostisland.services import wallpaper as wp


class WallpaperLogicTest(unittest.TestCase):
    def test_scan_lists_images_sorted_and_skips_others(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.PNG", "a.jpg", "notes.txt", "c.webp"):
                open(os.path.join(d, name), "w").close()
            os.mkdir(os.path.join(d, "dir.jpg"))
            names = [os.path.basename(p) for p in wp.scan(d)]
        self.assertEqual(names, ["a.jpg", "b.PNG", "c.webp"])

    def test_scan_missing_folder_is_empty(self):
        self.assertEqual(wp.scan("/nonexistent/lost-island"), [])

    def test_search_matches_file_name_only(self):
        self.assertTrue(wp.matches("/x/Goku Black.png", "goku"))
        self.assertFalse(wp.matches("/goku/sunset.png", "goku"))
        self.assertTrue(wp.matches("/x/a.png", "  "))

    def test_bg_line_round_trip_with_spaces_and_quotes(self):
        path = '/home/u/My "Pics"/a b.png'
        text = wp.replace_bg_line("", path, "fit")
        self.assertEqual(wp.read_bg_line(text), path)
        self.assertTrue(text.endswith(" fit\n"))

    def test_replace_keeps_other_lines(self):
        text = "# mine\noutput * bg /old.png fill\nexec foo\n"
        new = wp.replace_bg_line(text, "/new.png")
        self.assertEqual(new, '# mine\noutput * bg "/new.png" fill\nexec foo\n')
        self.assertEqual(wp.read_bg_line(new), "/new.png")

    def test_unquoted_bg_line_is_read(self):
        self.assertEqual(wp.read_bg_line("output * bg /a/b.jpg fill"),
                         "/a/b.jpg")

    def test_settings_fall_back_on_bad_values(self):
        opts = wp.settings({"wallpaper": {"fill": "zoom", "transition": "x",
                                          "unknown": 1}})
        self.assertEqual(opts["fill"], "fill")
        self.assertEqual(opts["transition"], "grow")
        self.assertNotIn("unknown", opts)

    def test_backend_choice(self):
        opts = wp.settings({"wallpaper": {"command": "feh --bg-fill \"$1\""}})
        self.assertEqual(wp.pick_backend(opts), "command")
        opts = wp.settings({"wallpaper": {"backend": "command"}})
        self.assertEqual(wp.pick_backend(opts), "sway")  # empty command
        opts = wp.settings({"wallpaper": {"backend": "swww"}})
        self.assertEqual(wp.pick_backend(opts), "swww")

    def test_commands_per_backend(self):
        opts = wp.settings({})
        self.assertEqual(wp.commands("/a b.png", opts, "sway"),
                         [["swaymsg", 'output * bg "/a b.png" fill']])
        awww = wp.commands("/a.png", opts, "awww")[0]
        self.assertEqual(awww[:3], ["awww", "img", "/a.png"])
        self.assertIn("grow", awww)
        cmd = wp.commands("/a.png", {**opts, "command": "x"}, "command")[0]
        self.assertEqual(cmd[-1], "/a.png")

    def test_persist_backs_up_once_and_rewrites(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "wallpaper.conf")
            with open(conf, "w") as f:
                f.write("output * bg /old.png fill\n")
            opts = {**wp.settings({}), "persist": conf}
            wp.persist("/one.png", opts)
            wp.persist("/two.png", opts)
            with open(conf) as f:
                self.assertEqual(wp.read_bg_line(f.read()), "/two.png")
            with open(conf + ".pre-lost-island") as f:
                self.assertIn("/old.png", f.read())

    def test_thumb_path_changes_with_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            first = wp.thumb_path(f.name, "/c")
            f.write(b"x")
            f.flush()
            self.assertNotEqual(first, wp.thumb_path(f.name, "/c"))
        self.assertIsNone(wp.thumb_path("/nonexistent.png"))


class CarouselGeometryTest(unittest.TestCase):
    def test_centre_card_is_largest_and_opaque(self):
        from lostisland.ui.wallpapers import card_geometry
        x, _cy, w, _h, a = card_geometry(360, 0)
        self.assertAlmostEqual(x + w / 2, 180)
        self.assertEqual(a, 1)
        _x1, _cy, w1, _h, a1 = card_geometry(360, 1)
        _x2, _cy, w2, _h, a2 = card_geometry(360, 2)
        self.assertTrue(w > w1 > w2)
        self.assertTrue(1 > a1 > a2 >= 0)

    def test_sides_mirror(self):
        from lostisland.ui.wallpapers import card_geometry
        left = card_geometry(360, -1)
        right = card_geometry(360, 1)
        self.assertAlmostEqual(left[0] + left[2] / 2 - 180,
                               180 - (right[0] + right[2] / 2))


if __name__ == "__main__":
    unittest.main()
