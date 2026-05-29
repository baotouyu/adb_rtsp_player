import threading
import time
import unittest
from unittest.mock import patch

from rtsp_tool.player import PlayerController, build_ffplay_command, build_rtsp_url


class BlockingProcess:
    started = threading.Event()
    release = threading.Event()
    terminated = False

    def __init__(self, _command):
        type(self).started.set()
        type(self).release.wait(timeout=2)
        self._running = True

    def poll(self):
        return None if self._running else 0

    def terminate(self):
        type(self).terminated = True
        self._running = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._running = False


class PlayerTests(unittest.TestCase):
    def test_build_rtsp_url_uses_default_port_and_channel(self):
        self.assertEqual(build_rtsp_url("192.168.2.2"), "rtsp://192.168.2.2:8554/ch0")

    def test_build_ffplay_command_uses_aggressive_low_latency_tcp_options(self):
        self.assertEqual(
            build_ffplay_command("/usr/local/bin/ffplay", "rtsp://192.168.2.2:8554/ch0"),
            [
                "/usr/local/bin/ffplay",
                "-rtsp_transport",
                "udp,tcp",
                "-allowed_media_types",
                "video",
                "-an",
                "-fast",
                "-fflags",
                "nobuffer+discardcorrupt",
                "-flags",
                "low_delay",
                "-flags2",
                "fast",
                "-drp",
                "0",
                "-probesize",
                "32",
                "-analyzeduration",
                "0",
                "-max_delay",
                "0",
                "-reorder_queue_size",
                "0",
                "-rtbufsize",
                "262144",
                "-sync",
                "ext",
                "-framedrop",
                "-noinfbuf",
                "rtsp://192.168.2.2:8554/ch0",
            ],
        )

    def test_stop_waits_for_concurrent_start_before_returning(self):
        BlockingProcess.started.clear()
        BlockingProcess.release.clear()
        BlockingProcess.terminated = False
        player = PlayerController("ffplay")
        with patch("rtsp_tool.player.subprocess.Popen", BlockingProcess):
            starter = threading.Thread(target=lambda: player.start("rtsp://camera"))
            starter.start()
            self.assertTrue(BlockingProcess.started.wait(timeout=1))

            stopped = threading.Event()
            stopper = threading.Thread(target=lambda: (player.stop(), stopped.set()))
            stopper.start()
            time.sleep(0.05)
            self.assertFalse(stopped.is_set())

            BlockingProcess.release.set()
            stopper.join(timeout=1)
            starter.join(timeout=1)

        self.assertTrue(stopped.is_set())
        self.assertTrue(BlockingProcess.terminated)
        self.assertFalse(player.is_running())


if __name__ == "__main__":
    unittest.main()
