from __future__ import annotations

import subprocess
import threading
from typing import Sequence


def build_rtsp_url(device_ip: str, port: int = 8554, channel: str = "ch0") -> str:
    return f"rtsp://{device_ip}:{port}/{channel}"


def build_ffplay_command(ffplay_path: str, rtsp_url: str) -> list[str]:
    return [
        ffplay_path,
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
        rtsp_url,
    ]


class PlayerController:
    def __init__(self, ffplay_path: str = "ffplay"):
        self.ffplay_path = ffplay_path
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    def is_running(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def start(self, rtsp_url: str) -> Sequence[str]:
        with self._lock:
            if self.is_running():
                self.stop()
            command = build_ffplay_command(self.ffplay_path, rtsp_url)
            self.process = subprocess.Popen(command)
            return command

    def stop(self) -> None:
        with self._lock:
            if not self.process:
                return
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.process = None
