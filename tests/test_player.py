import unittest

from rtsp_tool.player import build_ffplay_command, build_rtsp_url


class PlayerTests(unittest.TestCase):
    def test_build_rtsp_url_uses_default_port_and_channel(self):
        self.assertEqual(build_rtsp_url("192.168.2.2"), "rtsp://192.168.2.2:8554/ch0")

    def test_build_ffplay_command_uses_low_latency_tcp_options(self):
        self.assertEqual(
            build_ffplay_command("/usr/local/bin/ffplay", "rtsp://192.168.2.2:8554/ch0"),
            [
                "/usr/local/bin/ffplay",
                "-rtsp_transport",
                "tcp",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "rtsp://192.168.2.2:8554/ch0",
            ],
        )


if __name__ == "__main__":
    unittest.main()
