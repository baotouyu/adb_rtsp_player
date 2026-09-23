import threading
import time
import unittest
from unittest.mock import patch

from rtsp_tool.player import PlayerController, build_ffplay_command, build_rtsp_url
from rtsp_tool.spawn import subprocess_flags


class BlockingProcess:
    started = threading.Event()
    release = threading.Event()
    terminated = False

    def __init__(self, _command, **kwargs):
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
                "tcp",
                "-allowed_media_types",
                "video",
                "-an",
                "-fflags",
                "nobuffer+discardcorrupt",
                "-flags",
                "low_delay",
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

    def test_start_passes_no_window_creation_flag_and_suppresses_output(self):
        player = PlayerController("ffplay")
        with patch("rtsp_tool.player.subprocess.Popen") as popen:
            command = player.start("rtsp://camera")

        popen.assert_called_once()
        popen.assert_called_once_with(
            build_ffplay_command("ffplay", "rtsp://camera"),
            stdout=-3,
            stderr=-3,
            creationflags=subprocess_flags(),
        )
        self.assertEqual(list(command), build_ffplay_command("ffplay", "rtsp://camera"))

    def test_start_is_idempotent_for_the_same_url(self):
        player = PlayerController("ffplay")
        with patch("rtsp_tool.player.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            first = player.start("rtsp://camera", window_title="T", width=640, height=360)
            second = player.start("rtsp://camera", window_title="T", width=640, height=360)
            third = player.start("rtsp://camera", window_title="OTHER", width=200, height=100)

        self.assertEqual(popen.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertTrue(player.is_running())

    def test_embed_params_append_noborder_title_and_size(self):
        command = build_ffplay_command(
            "/usr/local/bin/ffplay",
            "rtsp://192.168.2.2:8554/ch0",
            window_title="ADB_RTSP_Player_Embedded_abc123",
            width=640,
            height=360,
        )
        self.assertEqual(command[-7:], ["-noborder", "-window_title", "ADB_RTSP_Player_Embedded_abc123", "-x", "640", "-y", "360"])
        self.assertIn("rtsp://192.168.2.2:8554/ch0", command)

    def test_default_command_keeps_no_embed_params(self):
        command = build_ffplay_command("/usr/local/bin/ffplay", "rtsp://192.168.2.2:8554/ch0")
        self.assertNotIn("-noborder", command)

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
