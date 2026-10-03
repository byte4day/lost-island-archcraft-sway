import unittest
from pathlib import Path
from unittest.mock import patch

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from lostisland.ui.launchers import launcher_command


class LauncherCommandTest(unittest.TestCase):
    def test_missing_archcraft_theme_uses_alacritty_defaults(self):
        with patch("lostisland.ui.launchers.ALACRITTY_CONFIG",
                   Path("/missing/alacritty.toml")):
            command = launcher_command("Codex", "/usr/bin/codex",
                                       "/usr/bin/alacritty")
        self.assertNotIn("--config-file", command)
        self.assertEqual(command[-2:], ["-e", "/usr/bin/codex"])


if __name__ == "__main__":
    unittest.main()
