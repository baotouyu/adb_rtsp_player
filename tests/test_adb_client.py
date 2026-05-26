import unittest
from unittest.mock import patch

from rtsp_tool.adb_client import (
    ADBClient,
    ADBDevice,
    YOLO_APP_REMOTE_PATH,
    YOLO_INSTALL_TIMEOUT,
    YOLO_MODEL_REMOTE_PATH,
    YOLO_UPDATE_DIR,
    build_shell_command,
    parse_adb_devices,
    parse_ifconfig_ip,
    parse_ip_route_ip,
)


class ADBClientTests(unittest.TestCase):
    def test_parse_adb_devices_keeps_serial_and_state(self):
        output = """List of devices attached
abc123	device
xyz999	unauthorized
off1	offline

"""

        devices = parse_adb_devices(output)

        self.assertEqual(
            devices,
            [
                ADBDevice(serial="abc123", state="device"),
                ADBDevice(serial="xyz999", state="unauthorized"),
                ADBDevice(serial="off1", state="offline"),
            ],
        )

    def test_parse_ip_route_ip_prefers_src_on_default_route(self):
        output = "default via 192.168.2.1 dev wlan0 src 192.168.2.2 metric 303\n"

        self.assertEqual(parse_ip_route_ip(output), "192.168.2.2")

    def test_parse_ifconfig_ip_ignores_loopback(self):
        output = """
lo        Link encap:Local Loopback
          inet addr:127.0.0.1  Mask:255.0.0.0
wlan0     Link encap:Ethernet
          inet addr:192.168.2.2  Bcast:192.168.2.255  Mask:255.255.255.0
"""

        self.assertEqual(parse_ifconfig_ip(output), "192.168.2.2")

    def test_build_shell_command_targets_selected_serial(self):
        self.assertEqual(
            build_shell_command("adb", "abc123", "pidof sample_smart_camera"),
            ["adb", "-s", "abc123", "shell", "pidof sample_smart_camera"],
        )

    def test_service_commands_are_exact(self):
        client = ADBClient(adb_path="adb")

        self.assertEqual(
            client.command_exists_command("abc123"),
            ["adb", "-s", "abc123", "shell", "test -x /usr/bin/sample_smart_camera"],
        )
        self.assertEqual(
            client.service_status_command("abc123"),
            ["adb", "-s", "abc123", "shell", "pidof sample_smart_camera"],
        )
        self.assertEqual(
            client.start_service_command("abc123"),
            [
                "adb",
                "-s",
                "abc123",
                "shell",
                "cd /tmp && /usr/bin/sample_smart_camera --rtsp-only >/tmp/sample_smart_camera.log 2>&1",
            ],
        )
        self.assertEqual(
            client.stop_service_command("abc123"),
            ["adb", "-s", "abc123", "shell", "pkill sample_smart_camera"],
        )
        self.assertEqual(
            client.stop_service_command("abc123", ignore_missing=True),
            ["adb", "-s", "abc123", "shell", "pkill sample_smart_camera || true"],
        )

    def test_yolo_install_commands_are_exact(self):
        client = ADBClient(adb_path="adb")

        self.assertEqual(
            client.prepare_yolo_update_command("abc123"),
            ["adb", "-s", "abc123", "shell", "rm -rf /tmp/yolo_app_update && mkdir -p /tmp/yolo_app_update"],
        )
        self.assertEqual(
            client.push_yolo_file_command("abc123", "/local/sample_smart_camera", f"{YOLO_UPDATE_DIR}/sample_smart_camera"),
            ["adb", "-s", "abc123", "push", "/local/sample_smart_camera", "/tmp/yolo_app_update/sample_smart_camera"],
        )
        self.assertEqual(
            client.install_yolo_update_command("abc123"),
            [
                "adb",
                "-s",
                "abc123",
                "shell",
                "cp /tmp/yolo_app_update/sample_smart_camera /usr/bin/sample_smart_camera && "
                "cp /tmp/yolo_app_update/network_binary.nb /network_binary.nb && "
                "chmod +x /usr/bin/sample_smart_camera && sync && rm -rf /tmp/yolo_app_update",
            ],
        )
        self.assertEqual(YOLO_APP_REMOTE_PATH, "/usr/bin/sample_smart_camera")
        self.assertEqual(YOLO_MODEL_REMOTE_PATH, "/network_binary.nb")

    def test_install_yolo_package_runs_stop_prepare_push_install_sequence(self):
        client = ADBClient(adb_path="adb")
        calls: list[tuple[list[str], float | None]] = []

        def fake_run(args, timeout=None):
            calls.append((list(args), timeout))
            return type("Result", (), {"ok": True, "stderr": "", "stdout": ""})()

        with patch.object(client, "run", side_effect=fake_run):
            with patch.object(client, "stop_service", wraps=client.stop_service) as stop_service:
                result = client.install_yolo_package(
                    "abc123",
                    app_path="/local/yoloApp_苹果/sample_smart_camera",
                    model_path="/local/yoloApp_苹果/network_binary.nb",
                )

        self.assertTrue(result.ok)
        stop_service.assert_called_once_with("abc123", ignore_missing=True)
        self.assertEqual(
            calls,
            [
                ((["-s", "abc123", "shell", "pkill sample_smart_camera || true"]), None),
                ((["-s", "abc123", "shell", "rm -rf /tmp/yolo_app_update && mkdir -p /tmp/yolo_app_update"]), None),
                ((["-s", "abc123", "push", "/local/yoloApp_苹果/sample_smart_camera", "/tmp/yolo_app_update/sample_smart_camera"]), YOLO_INSTALL_TIMEOUT),
                ((["-s", "abc123", "push", "/local/yoloApp_苹果/network_binary.nb", "/tmp/yolo_app_update/network_binary.nb"]), YOLO_INSTALL_TIMEOUT),
                ((
                    [
                        "-s",
                        "abc123",
                        "shell",
                        "cp /tmp/yolo_app_update/sample_smart_camera /usr/bin/sample_smart_camera && "
                        "cp /tmp/yolo_app_update/network_binary.nb /network_binary.nb && "
                        "chmod +x /usr/bin/sample_smart_camera && sync && rm -rf /tmp/yolo_app_update",
                    ]
                ), YOLO_INSTALL_TIMEOUT),
            ],
        )

    def test_install_yolo_package_cleans_up_local_service_before_prepare(self):
        client = ADBClient(adb_path="adb")
        events = []

        def fake_run(args, timeout=None):
            events.append(("run", list(args)))
            return type("Result", (), {"ok": True, "stderr": "", "stdout": ""})()

        def fake_stop_local_service_process(serial):
            events.append(("cleanup", serial))

        with patch.object(client, "run", side_effect=fake_run):
            with patch.object(client, "stop_local_service_process", side_effect=fake_stop_local_service_process) as cleanup:
                result = client.install_yolo_package("abc123", "/local/app", "/local/model")

        self.assertTrue(result.ok)
        cleanup.assert_called_once_with("abc123")
        self.assertEqual(
            events[:3],
            [
                ("run", ["-s", "abc123", "shell", "pkill sample_smart_camera || true"]),
                ("cleanup", "abc123"),
                ("run", ["-s", "abc123", "shell", "rm -rf /tmp/yolo_app_update && mkdir -p /tmp/yolo_app_update"]),
            ],
        )

    def test_install_yolo_package_stops_on_failed_push(self):
        client = ADBClient(adb_path="adb")
        results = [
            type("Result", (), {"ok": True, "stderr": "", "stdout": ""})(),
            type("Result", (), {"ok": True, "stderr": "", "stdout": ""})(),
            type("Result", (), {"ok": False, "stderr": "push failed", "stdout": ""})(),
        ]

        with patch.object(client, "run", side_effect=results) as run:
            result = client.install_yolo_package("abc123", "/local/app", "/local/model")

        self.assertFalse(result.ok)
        self.assertEqual(result.stderr, "push failed")
        self.assertEqual(run.call_count, 3)

    def test_start_service_uses_long_running_adb_process(self):
        client = ADBClient(adb_path="adb")

        with patch("rtsp_tool.adb_client.subprocess.Popen") as popen:
            result = client.start_service("abc123")

        popen.assert_called_once_with(
            [
                "adb",
                "-s",
                "abc123",
                "shell",
                "cd /tmp && /usr/bin/sample_smart_camera --rtsp-only >/tmp/sample_smart_camera.log 2>&1",
            ],
            stdout=-3,
            stderr=-3,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "started")

    def test_wait_for_service_polls_until_pid_appears(self):
        client = ADBClient(adb_path="adb")

        with patch.object(client, "service_pid", side_effect=[None, "1228"]) as service_pid:
            with patch("rtsp_tool.adb_client.time.sleep") as sleep:
                running = client.wait_for_service("abc123", timeout=5.0, interval=0.1)

        self.assertTrue(running)
        self.assertEqual(service_pid.call_count, 2)
        sleep.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
