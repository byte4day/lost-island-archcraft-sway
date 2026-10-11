import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from lostisland.services import tools


class ToolsParsingTest(unittest.TestCase):
    def test_focused_output(self):
        outputs = ('[{"name": "eDP-1", "focused": false},'
                   ' {"name": "HDMI-A-1", "focused": true}]')
        self.assertEqual(tools.focused_output(outputs), "HDMI-A-1")
        self.assertIsNone(tools.focused_output('[{"name": "eDP-1"}]'))
        self.assertIsNone(tools.focused_output("not json"))
        self.assertIsNone(tools.focused_output('{"name": "x"}'))

    def test_parse_color(self):
        self.assertEqual(tools.parse_color("#1a2b3c\n"), "#1A2B3C")
        self.assertIsNone(tools.parse_color(""))
        self.assertIsNone(tools.parse_color("rgb(1, 2, 3)"))

    def test_parse_modes(self):
        self.assertEqual(tools.parse_modes("default\ndo-not-disturb\n"),
                         {"default", "do-not-disturb"})

    def test_screenshot_name_is_timestamped_png(self):
        path = tools.screenshot_path(datetime(2026, 10, 11, 9, 5, 7))
        self.assertEqual(path.name, "Screenshot_2026-10-11_09-05-07.png")
        self.assertEqual(path.parent.name, "Screenshots")

    def test_power_commands(self):
        self.assertEqual(tools.power_command("poweroff"),
                         ["systemctl", "poweroff"])
        self.assertEqual(tools.power_command("logout"), ["swaymsg", "exit"])
        with patch.object(tools, "SWAY_LOCK_SCRIPT", Path("/missing/lock")):
            self.assertEqual(tools.power_command("lock"), ["swaylock", "-f"])

    def test_session_ending_actions_require_confirmation(self):
        for name in ("logout", "suspend", "reboot", "poweroff"):
            self.assertTrue(tools.POWER_ACTIONS[name][3], name)
        self.assertFalse(tools.POWER_ACTIONS["lock"][3])


if __name__ == "__main__":
    unittest.main()
