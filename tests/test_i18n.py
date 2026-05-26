import unittest

from rtsp_tool.i18n import STATE_TEXT, TEXT, device_state_text


class I18nTests(unittest.TestCase):
    def test_main_window_labels_are_chinese(self):
        self.assertEqual(TEXT["app_title"], "ADB 摄像头推流播放器")
        self.assertEqual(TEXT["dependencies"], "依赖检测")
        self.assertEqual(TEXT["devices"], "ADB 设备")
        self.assertEqual(TEXT["stream"], "推流信息")
        self.assertEqual(TEXT["controls"], "操作")
        self.assertEqual(TEXT["log"], "运行日志")

    def test_action_buttons_are_chinese(self):
        self.assertEqual(TEXT["refresh_devices"], "刷新设备")
        self.assertEqual(TEXT["start_board_stream"], "启动板端推流")
        self.assertEqual(TEXT["stop_board_stream"], "停止板端推流")
        self.assertEqual(TEXT["start_playback"], "开始播放")
        self.assertEqual(TEXT["stop_playback"], "停止播放")
        self.assertEqual(TEXT["copy_rtsp_url"], "复制 RTSP 地址")

    def test_runtime_state_text_is_chinese(self):
        self.assertEqual(STATE_TEXT["unknown"], "未知")
        self.assertEqual(STATE_TEXT["running"], "运行中")
        self.assertEqual(STATE_TEXT["stopped"], "已停止")
        self.assertEqual(STATE_TEXT["missing"], "未找到")
        self.assertEqual(STATE_TEXT["starting"], "启动中")
        self.assertEqual(STATE_TEXT["ready"], "就绪")

    def test_device_states_are_chinese(self):
        self.assertEqual(device_state_text("device"), "已连接")
        self.assertEqual(device_state_text("unauthorized"), "未授权")
        self.assertEqual(device_state_text("offline"), "离线")
        self.assertEqual(device_state_text("recovery"), "recovery")


if __name__ == "__main__":
    unittest.main()
