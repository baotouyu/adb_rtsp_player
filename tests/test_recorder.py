from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from rtsp_tool.recorder import (
    RecorderController,
    build_ffmpeg_command,
    next_recording_path,
)
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


class RecorderTests(unittest.TestCase):
    def test_build_ffmpeg_command_is_streaming_copy_remux(self):
        output_path = Path("/tmp/recordings/20260923_153045.mp4")
        command = build_ffmpeg_command(
            "/usr/local/bin/ffmpeg",
            "rtsp://192.168.2.2:8554/ch0",
            output_path,
        )
        self.assertEqual(
            command,
            [
                "/usr/local/bin/ffmpeg",
                "-y",
                "-rtsp_transport",
                "tcp",
                "-i",
                "rtsp://192.168.2.2:8554/ch0",
                "-c",
                "copy",
                "-movflags",
                "frag_keyframe+empty_moov+default_base_moof",
                "-f",
                "mp4",
                str(output_path),
            ],
        )

    def test_next_recording_path_is_timestamped_under_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = next_recording_path(Path(tmpdir))

        self.assertEqual(path.parent, Path(tmpdir))
        self.assertEqual(path.suffix, ".mp4")
        self.assertEqual(len(path.stem), 15)  # YYYYmmdd_HHMMSS

    def test_start_mkdirs_output_dir_and_spawns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "recordings"
            with patch("rtsp_tool.recorder.subprocess.Popen") as popen:
                popen.return_value.poll.return_value = None
                recorder = RecorderController(ffmpeg_path="/usr/local/bin/ffmpeg")
                command = recorder.start("rtsp://192.168.2.2:8554/ch0", output_dir)
                output_path = recorder.recording.output_path

            self.assertTrue(output_dir.is_dir())
            self.assertTrue(recorder.is_recording())
            popen.assert_called_once()
            kwargs = popen.call_args.kwargs
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertEqual(kwargs["creationflags"], subprocess_flags())
            self.assertTrue(str(output_path).startswith(str(output_dir)))

    def test_start_while_recording_returns_same_command_without_second_process(self):
        BlockingProcess.started.clear()
        BlockingProcess.release.clear()
        recorder = RecorderController("/usr/local/bin/ffmpeg")
        with patch("rtsp_tool.recorder.subprocess.Popen", BlockingProcess):
            first = recorder.start("rtsp://192.168.2.2:8554/ch0", "/tmp/recordings")
            with tempfile.TemporaryDirectory() as tmpdir:
                second = recorder.start("rtsp://192.168.2.2:8554/ch0", Path(tmpdir))

        self.assertEqual(list(first), list(second))
        self.assertTrue(recorder.is_recording())
        BlockingProcess.release.set()
        recorder.close()

    def test_stop_finalizes_and_returns_path(self):
        recorder = RecorderController("/usr/local/bin/ffmpeg")
        with patch("rtsp_tool.recorder.subprocess.Popen", BlockingProcess):
            output_dir = "/tmp/recordings"
            partial_path = recorder.start("rtsp://x", output_dir)
            first_expected = Path(partial_path[-1])
            path = recorder.stop()

        self.assertEqual(path, first_expected)
        self.assertFalse(recorder.is_recording())
        self.assertIsNone(recorder.stop())

    def test_stop_kills_on_timeout(self):
        class StuckProcess:
            def __init__(self, _command, **kwargs):
                pass

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(["ffmpeg"], timeout)

            def kill(self):
                self.killed = True

        recorder = RecorderController("/usr/local/bin/ffmpeg")
        with patch("rtsp_tool.recorder.subprocess.Popen", StuckProcess):
            recorder.start("rtsp://x", "/tmp/recordings")
            path = recorder.stop()

        self.assertIsNotNone(path)
        self.assertFalse(recorder.is_recording())

    def test_start_oserror_raises_runtime_error(self):
        def raise_oserror(*_args, **_kwargs):
            raise OSError("ffmpeg not found")

        recorder = RecorderController("/does/not/exist/ffmpeg")
        with patch("rtsp_tool.recorder.subprocess.Popen", side_effect=raise_oserror):
            with self.assertRaisesRegex(RuntimeError, "无法启动 ffmpeg 录制"):
                recorder.start("rtsp://x", "/tmp/recordings")

        self.assertFalse(recorder.is_recording())


if __name__ == "__main__":
    unittest.main()