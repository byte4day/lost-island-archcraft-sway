import unittest
from unittest.mock import patch

from lostisland.services.recorder import ScreenRecorder


class RecorderChoiceTest(unittest.TestCase):
    def test_requested_audio_never_silently_becomes_a_silent_recording(self):
        recorder = ScreenRecorder()
        with patch("lostisland.services.recorder.shutil.which",
                   return_value="/usr/bin/wf-recorder"), \
             patch("lostisland.services.recorder.system_audio_source",
                   return_value=None):
            self.assertFalse(recorder.start("HDMI-A-1", include_audio=True))
        self.assertFalse(recorder.running)
        self.assertIn("Without audio", recorder.message)


if __name__ == "__main__":
    unittest.main()
