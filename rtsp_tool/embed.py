"""Embed a spawned ffplay window inside a tkinter widget's region on Windows.

Kept free of tkinter imports so the window-manager primitives are easy to
unit-test with injected fakes. The GUI passes the host widget's HWND
(``widget.winfo_id()``) down to this module.
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Callable
from uuid import uuid4


FFPLAY_TITLE_PREFIX = "ADB_RTSP_Player_Embedded_"

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000

SW_SHOW = 5


def embed_window_title() -> str:
    return f"{FFPLAY_TITLE_PREFIX}{uuid4().hex[:8]}"


def has_user32() -> bool:
    return os.name == "nt"


def _user32() -> "object | None":
    """Return the Windows user32 API object, or None where unavailable."""
    if os.name != "nt":
        return None
    return ctypes.windll.user32


def find_window(title: str) -> int | None:
    """Return the top-level window HWND whose title matches, or None."""
    user32 = _user32()
    if user32 is None:
        return None
    hwnd = user32.FindWindowW(None, title)
    return hwnd if hwnd else None


def attach_window(hwnd: int, host_hwnd: int, width: int, height: int) -> bool:
    """Reparent *hwnd* under *host_hwnd* and resize it to fill the region."""
    user32 = _user32()
    if user32 is None:
        return False
    old_style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    new_style = (old_style & ~(WS_CAPTION | WS_THICKFRAME | WS_POPUP)) | WS_CHILD
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, new_style)
    parent = user32.SetParent(hwnd, host_hwnd)
    if not parent:
        return False
    user32.MoveWindow(hwnd, 0, 0, width, height, True)
    user32.ShowWindow(hwnd, SW_SHOW)
    return True


class EmbedController:
    """Tracks the ffplay window being embedded and re-parents it asynchronously."""

    def __init__(self) -> None:
        self._hwnd: int | None = None
        self._title: str | None = None
        self._watch_thread: threading.Thread | None = None

    @property
    def embedded_hwnd(self) -> int | None:
        return self._hwnd

    @property
    def window_title(self) -> str | None:
        return self._title

    def host_is_hwnd(self) -> bool:
        """True only where SetParent embedding is supported (Windows)."""
        return os.name == "nt"

    def attach_async(
        self,
        host_hwnd: int,
        title: str,
        width: int,
        height: int,
        poll: float = 0.2,
        timeout: float = 10.0,
        on_attached: Callable[[], None] | None = None,
        on_failed: Callable[[], None] | None = None,
    ) -> None:
        self._title = title

        def watch() -> None:
            deadline = _now() + timeout
            hwnd = None
            while _now() < deadline:
                hwnd = find_window(title)
                if hwnd:
                    break
                _sleep(poll)
            if hwnd is None:
                if on_failed is not None:
                    on_failed()
                return
            self._hwnd = hwnd
            ok = attach_window(hwnd, host_hwnd, width, height)
            if ok and on_attached is not None:
                on_attached()
            elif not ok and on_failed is not None:
                self._hwnd = None
                on_failed()

        self._watch_thread = threading.Thread(target=watch, daemon=True)
        self._watch_thread.start()

    def resize(self, width: int, height: int) -> None:
        user32 = _user32()
        if user32 is None or self._hwnd is None:
            return
        user32.MoveWindow(self._hwnd, 0, 0, width, height, True)

    def detach(self) -> None:
        self._hwnd = None
        self._title = None

    def wait_thread(self, timeout: float = 10.0) -> None:
        thread = self._watch_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)


def _now() -> float:
    import time

    return time.monotonic()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)