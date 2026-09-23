import unittest


try:
    import tkinter  # noqa: F401
    from rtsp_tool.gui import RTSPToolApp

    TKINTER_AVAILABLE = True
except Exception:  # tkinter missing on this box
    TKINTER_AVAILABLE = False

    class RTSPToolApp:  # stub so the module can be collected
        pass


@unittest.skipUnless(TKINTER_AVAILABLE, "tkinter is not available")
class GuiConsoleTests(unittest.TestCase):
    class FakeText:
        def __init__(self):
            self.lines = []
            self._state = "disabled"

        def configure(self, **kwargs):
            if "state" in kwargs:
                self._state = kwargs["state"]

        def insert(self, _index, text):
            self.lines.append(text)

        def see(self, _index):
            pass

    def _make_app(self):
        app = object.__new__(RTSPToolApp)  # bypass __init__ (no tkinter needed)
        app.log_text = self.FakeText()
        return app

    def test_command_writes_dollar_line_with_timestamp(self):
        app = self._make_app()

        app.command("ffplay -an rtsp://192.168.2.2:8554/ch0")

        self.assertEqual(len(app.log_text.lines), 1)
        line = app.log_text.lines[0]
        self.assertIn("$ ffplay -an rtsp://192.168.2.2:8554/ch0", line)
        self.assertRegex(line, r"^\[\d{2}:\d{2}:\d{2}\]")

    def test_log_goes_to_same_console_widget(self):
        app = self._make_app()

        app.log("hello")
        app.command("adb devices")

        self.assertEqual(len(app.log_text.lines), 2)
        self.assertIn("hello", app.log_text.lines[0])
        self.assertIn("$ adb devices", app.log_text.lines[1])


if __name__ == "__main__":
    unittest.main()