import unittest
from unittest.mock import MagicMock, patch

from gi.repository import Gio

from lostisland.services.airplay import AirPlayReceiver


class AirPlayReceiverTest(unittest.TestCase):
    def test_start_uses_live_mirroring_options(self):
        receiver = AirPlayReceiver()
        process = MagicMock()
        with (patch("lostisland.services.airplay.shutil.which", return_value="/usr/bin/uxplay"),
              patch("lostisland.services.airplay.Gio.Subprocess.new", return_value=process) as spawn):
            self.assertTrue(receiver.start())

        spawn.assert_called_once_with(
            ["/usr/bin/uxplay", "-n", "Lost Island", "-nh", "-vsync", "no",
             "-avdec", "-srgb", "no", "-vs", "waylandsink"],
            Gio.SubprocessFlags.NONE)
        process.wait_async.assert_called_once()

    def test_missing_uxplay_reports_installation_error(self):
        receiver = AirPlayReceiver()
        with patch("lostisland.services.airplay.shutil.which", return_value=None):
            self.assertFalse(receiver.start())
        self.assertFalse(receiver.running)
        self.assertEqual(receiver.message, "UxPlay is not installed")


if __name__ == "__main__":
    unittest.main()
