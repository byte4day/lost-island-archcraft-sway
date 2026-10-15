import time
import unittest

from lostisland.services.focus_timer import clamp_minutes, fmt_left
from lostisland.services.indicators import brightness_percent
from lostisland.services.mpris import player_app
from lostisland.services.notify import find_mako_id, is_osd, parse_actions
from lostisland.services.transfers import final_name, human_size, parse_percent
from lostisland.services.weather import classify
from lostisland.ui.activity import rank
from lostisland.ui.pill import clock_markup


class ClockTests(unittest.TestCase):
    def test_twelve_hour_has_am_pm_and_no_leading_zero(self):
        tm = time.strptime("2026-10-15 20:56", "%Y-%m-%d %H:%M")
        text = clock_markup(tm, h24=False)
        self.assertTrue(text.startswith("8:56"))
        self.assertIn("PM", text)

    def test_midnight_is_twelve_am(self):
        tm = time.strptime("2026-10-15 00:05", "%Y-%m-%d %H:%M")
        self.assertTrue(clock_markup(tm, h24=False).startswith("12:05"))
        self.assertEqual(clock_markup(tm, h24=True), "00:05")


class WeatherTests(unittest.TestCase):
    def test_thunder_is_short(self):
        self.assertEqual(classify("200")[0], "Storm")

    def test_rain_showers_are_not_snow(self):
        self.assertEqual(classify("353")[0], "Rain")
        self.assertEqual(classify("338")[0], "Snow")

    def test_labels_fit(self):
        for code in range(100, 400):
            self.assertLessEqual(len(classify(code)[0]), 8)


class NotifyTests(unittest.TestCase):
    def test_actions_pair_up(self):
        self.assertEqual(parse_actions(["default", "", "reply", "Reply"]),
                         [("default", ""), ("reply", "Reply")])

    def test_osd_hint(self):
        self.assertTrue(is_osd({"x-canonical-private-synchronous":
                                "sys-notify-volume"}))
        self.assertFalse(is_osd({}))

    def test_mako_lookup_takes_newest_match(self):
        listing = ('[{"id": 3, "app_name": "Slack", "summary": "Hi"},'
                   ' {"id": 9, "app_name": "Slack", "summary": "Hi"},'
                   ' {"id": 12, "app_name": "Mail", "summary": "Hi"}]')
        self.assertEqual(find_mako_id(listing, "Slack", "Hi"), 9)
        self.assertIsNone(find_mako_id(listing, "Slack", "Bye"))
        self.assertIsNone(find_mako_id("nonsense", "Slack", "Hi"))

    def test_old_mako_format(self):
        listing = ('{"data": [[{"id": {"data": 4}, "app-name": {"data": "X"},'
                   ' "summary": {"data": "S"}}]]}')
        self.assertEqual(find_mako_id(listing, "X", "S"), 4)


class TransferTests(unittest.TestCase):
    def test_partial_names(self):
        self.assertEqual(final_name("movie.mkv.part"), "movie.mkv")
        self.assertEqual(final_name("setup.exe.crdownload"), "setup.exe")
        self.assertIsNone(final_name("notes.txt"))

    def test_percent_parsing(self):
        self.assertEqual(parse_percent("  1,234,567  45%  1.2MB/s  0:00:12"),
                         45.0)
        self.assertEqual(parse_percent("73"), 73.0)
        self.assertIsNone(parse_percent("sending incremental file list"))

    def test_sizes(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(12_400_000), "12.4 MB")


class MiscTests(unittest.TestCase):
    def test_timer_helpers(self):
        self.assertEqual(clamp_minutes(200), 90)
        self.assertEqual(clamp_minutes("x"), 25)
        self.assertEqual(fmt_left(61), "01:01")

    def test_brightness(self):
        self.assertEqual(brightness_percent(48, 96), 50)
        self.assertIsNone(brightness_percent(None, 96))

    def test_player_app(self):
        self.assertEqual(player_app("org.mpris.MediaPlayer2.spotify"), "spotify")
        self.assertEqual(
            player_app("org.mpris.MediaPlayer2.firefox.instance_1_42"),
            "firefox")

    def test_activity_rank(self):
        acts = [{"kind": "timer", "running": True},
                {"kind": "music"},
                {"kind": "claude", "state": "needs"},
                {"kind": "claude", "state": "tool"}]
        kinds = [(a["kind"], a.get("state")) for a in rank(acts)]
        self.assertEqual(kinds, [("claude", "needs"), ("music", None),
                                 ("claude", "tool"), ("timer", None)])


if __name__ == "__main__":
    unittest.main()
