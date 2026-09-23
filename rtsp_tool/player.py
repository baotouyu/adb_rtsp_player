from __future__ import annotations

import subprocess
import threading
from typing import Sequence

from . import spawn


def build_rtsp_url(device_ip: str, port: int = 8554, channel: str = "ch0") -> str:
    return f"rtsp://{device_ip}:{port}/{channel}"


def build_ffplay_command(
    ffplay_path: str,
    rtsp_url: str,
    *,
    window_title: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[str]:
    command = [
        ffplay_path,
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
        rtsp_url,
    ]
    if window_title is not None:
        command.extend(["-noborder", "-window_title", window_title])
        if width is not None:
            command.extend(["-x", str(width)])
        if height is not None:
            command.extend(["-y", str(height)])
    return command


class PlayerController:
    def __init__(self, ffplay_path: str = "ffplay"):
        self.ffplay_path = ffplay_path
        self.process: subprocess.Popen[str] | None = None
        self.process_url: str | None = None
        self.process_command: Sequence[str] | None = None
        self._lock = threading.RLock()

    def is_running(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def current_url(self) -> str | None:
        with self._lock:
            return self.process_url

    def start(
        self,
        rtsp_url: str,
        *,
        window_title: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> Sequence[str]:
        with self._lock:
            if self.is_running():
                if self.process_url == rtsp_url:
                    if self.process_command is not None:
                        return self.process_command
                    return self.start(rtsp_url, window_title=window_title, width=width, height=height)
                self.stop()
            command = build_ffplay_command(
                self.ffplay_path,
                rtsp_url,
                window_title=window_title,
                width=width,
                height=height,
            )
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=spawn.subprocess_flags(),
            )
            self.process_url = rtsp_url
            self.process_command = command
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
            self.process_url = None
            self.process_command = None