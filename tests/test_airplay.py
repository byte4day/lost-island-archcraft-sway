import unittest
from unittest.mock import patch

from lostisland.services.airplay import AirPlayReceiver


class AirPlayReceiverTest(unittest.TestCase):
    def test_missing_uxplay_reports_installation_error(self):
        receiver = AirPlayReceiver()
        with patch("lostisland.services.airplay.shutil.which", return_value=None):
            self.assertFalse(receiver.start())
        self.assertFalse(receiver.running)
        self.assertEqual(receiver.message, "UxPlay is not installed")


if __name__ == "__main__":
    unittest.main()
