import time
import unittest

from lostisland.services.weather import WeatherService


class WeatherFaceLoopTest(unittest.TestCase):
    def test_changed_handler_that_requests_does_not_recurse(self):
        svc = WeatherService("")
        svc.temp, svc._stamp = "25°", time.time()
        calls = []

        def on_changed(*_):
            calls.append(1)
            svc.request(emit_cached=False)   # what the pill's render does
        svc.connect("changed", on_changed)
        svc.request()
        self.assertEqual(len(calls), 1)

    def test_cached_data_is_emitted_for_new_tiles(self):
        svc = WeatherService("")
        svc.temp, svc._stamp = "25°", time.time()
        got = []
        svc.connect("changed", lambda _s, t, _d, _i: got.append(t))
        svc.request()
        svc.request(emit_cached=False)
        self.assertEqual(got, ["25°"])


if __name__ == "__main__":
    unittest.main()
