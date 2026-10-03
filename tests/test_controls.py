import unittest

from lostisland.services.controls import (
    parse_audio_state,
    parse_bluetooth_state,
    parse_wifi_state,
)


class ControlOutputTest(unittest.TestCase):
    def test_wifi_state(self):
        self.assertIs(parse_wifi_state("enabled\n"), True)
        self.assertIs(parse_wifi_state("disabled\n"), False)
        self.assertIsNone(parse_wifi_state("unknown\n"))

    def test_bluetooth_state_and_hardware_block(self):
        self.assertIs(parse_bluetooth_state("unblocked unblocked\n"), True)
        self.assertIs(parse_bluetooth_state("blocked unblocked\n"), False)
        self.assertIsNone(parse_bluetooth_state("blocked blocked\n"))
        self.assertIsNone(parse_bluetooth_state(""))
        self.assertIsNone(parse_bluetooth_state("No default controller available"))

    def test_audio_state(self):
        self.assertIs(parse_audio_state("Mute: no\n"), True)
        self.assertIs(parse_audio_state("Mute: yes\n"), False)
        self.assertIsNone(parse_audio_state("Failure: no sink"))


if __name__ == "__main__":
    unittest.main()
