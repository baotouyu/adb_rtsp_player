from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import rtsp_tool.embed as embed
from rtsp_tool.embed import (
    FFPLAY_TITLE_PREFIX,
    EmbedController,
    attach_window,
    embed_window_title,
)


class EmbedTests(unittest.TestCase):
    def test_embed_window_title_is_unique_and_prefixed(self):
        first = embed_window_title()
        second = embed_window_title()

        self.assertTrue(first.startswith(FFPLAY_TITLE_PREFIX))
        self.assertNotEqual(first, second)
        self.assertEqual(len(first) - len(FFPLAY_TITLE_PREFIX), 8)

    def test_find_window_returns_hwnd_when_found(self):
        user32 = SimpleNamespace(FindWindowW=lambda _parent, _title: 42)
        with patch("rtsp_tool.embed._user32", return_value=user32):
            self.assertEqual(embed.find_window("some title"), 42)

    def test_find_window_returns_none_when_missing(self):
        user32 = SimpleNamespace(FindWindowW=lambda _parent, _title: 0)
        with patch("rtsp_tool.embed._user32", return_value=user32):
            self.assertIsNone(embed.find_window("some title"))

    def test_attach_window_sets_child_style_and_reparents(self):
        calls = []
        old_style = 0x00CF0000  # WS_CAPTION | WS_THICKFRAME | WS_POPUP plus something
        user32 = MagicMock()
        user32.GetWindowLongPtrW.return_value = old_style
        user32.SetParent.return_value = 5  # nonzero parent handle => success

        def record(name):
            calls.append(name)

        user32.SetWindowLongPtrW.side_effect = lambda *a, **k: record("SetWindowLongPtrW")
        user32.MoveWindow.side_effect = lambda *a, **k: record("MoveWindow")
        user32.ShowWindow.side_effect = lambda *a, **k: record("ShowWindow")

        with patch("rtsp_tool.embed._user32", return_value=user32):
            result = attach_window(100, 200, 640, 360)

        self.assertTrue(result)
        self.assertEqual(calls, ["SetWindowLongPtrW", "MoveWindow", "ShowWindow"])
        user32.SetParent.assert_called_once_with(100, 200)
        user32.MoveWindow.assert_called_once_with(100, 0, 0, 640, 360, True)
        user32.ShowWindow.assert_called_once_with(100, 5)
        new_style = user32.SetWindowLongPtrW.call_args[0][-1]
        self.assertEqual(new_style & 0x40000000, 0x40000000)  # WS_CHILD set

    def test_attach_window_returns_false_when_setparent_fails(self):
        user32 = MagicMock()
        user32.GetWindowLongPtrW.return_value = 0
        user32.SetParent.return_value = 0
        with patch("rtsp_tool.embed._user32", return_value=user32):
            self.assertFalse(attach_window(100, 200, 640, 360))

    def test_attach_async_polls_until_window_appears(self):
        user32 = SimpleNamespace(
            FindWindowW=lambda _parent, _title: 42,
            GetWindowLongPtrW=lambda *_: 0,
            SetWindowLongPtrW=lambda *_: None,
            SetParent=lambda *_: 5,
            MoveWindow=lambda *_: None,
            ShowWindow=lambda *_: None,
        )
        attached = []
        with patch("rtsp_tool.embed._user32", return_value=user32):
            controller = EmbedController()
            controller.attach_async(
                200, "title", 640, 360, poll=0.001, timeout=0.2,
                on_attached=lambda: attached.append(1),
            )
            controller.wait_thread(timeout=1)

        self.assertEqual(attached, [1])
        self.assertEqual(controller.embedded_hwnd, 42)

    def test_attach_async_timeout_calls_on_failed(self):
        failed = []
        with patch("rtsp_tool.embed.find_window", return_value=None):
            controller = EmbedController()
            controller.attach_async(
                200, "title", 640, 360, poll=0.001, timeout=0.05,
                on_failed=lambda: failed.append(1),
            )
            controller.wait_thread(timeout=1)

        self.assertEqual(failed, [1])
        self.assertIsNone(controller.embedded_hwnd)

    def test_resize_moves_embedded_window(self):
        user32 = MagicMock()
        with patch("rtsp_tool.embed._user32", return_value=user32):
            controller = EmbedController()
            controller._hwnd = 100
            controller.resize(800, 450)

        user32.MoveWindow.assert_called_once_with(100, 0, 0, 800, 450, True)

    def test_host_is_hwnd_requires_windows(self):
        with patch("rtsp_tool.embed.os.name", "nt"):
            self.assertTrue(EmbedController().host_is_hwnd())
        with patch("rtsp_tool.embed.os.name", "posix"):
            self.assertFalse(EmbedController().host_is_hwnd())


if __name__ == "__main__":
    unittest.main()