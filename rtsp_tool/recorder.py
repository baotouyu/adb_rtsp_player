from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
import threading
from typing import Sequence

from . import spawn


def next_recording_path(output_dir: Path | str) -> Path:
    output_dir = Path(output_dir)
    return output_dir / f"{datetime.now():%Y%m%d_%H%M%S}.mp4"


def _wait_terminated(process: subprocess.Popen[str]) -> None:
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def build_ffmpeg_command(
    ffmpeg_path: str,
    rtsp_url: str,
    output_path: Path | str,
) -> list[str]:
    return [
        ffmpeg_path,
        "-y",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-c",
        "copy",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "-f",
        "mp4",
        str(output_path),
    ]


@dataclass
class Recording:
    output_path: Path
    started_at: datetime


class RecorderController:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self.process: subprocess.Popen[str] | None = None
        self.recording: Recording | None = None
        self.command: Sequence[str] | None = None
        self._lock = threading.RLock()

    def is_recording(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def start(self, rtsp_url: str, output_dir: Path | str) -> Sequence[str]:
        with self._lock:
            if self.is_recording():
                if self.command is not None:
                    return self.command
                return build_ffmpeg_command(self.ffmpeg_path, rtsp_url, next_recording_path(output_dir))
            output_dir_path = Path(output_dir)
            try:
                output_dir_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RuntimeError(f"无法创建录制目录 {output_dir_path}：{exc}") from exc
            output_path = next_recording_path(output_dir_path)
            command = build_ffmpeg_command(self.ffmpeg_path, rtsp_url, output_path)
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=spawn.subprocess_flags(),
                )
            except OSError as exc:
                self.process = None
                self.recording = None
                self.command = None
                raise RuntimeError(f"无法启动 ffmpeg 录制：{exc}") from exc
            self.recording = Recording(output_path=output_path, started_at=datetime.now())
            self.command = command
            return command

    def stop(self) -> Path | None:
        with self._lock:
            process = self.process
            recording = self.recording
            self.process = None
            self.recording = None
            self.command = None
            if process is None:
                return None
            if process.poll() is None:
                process.terminate()
                _wait_terminated(process)
            if recording is None:
                return None
            return recording.output_path

    def close(self) -> None:
        self.stop()