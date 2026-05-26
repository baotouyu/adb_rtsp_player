import unittest
from unittest.mock import patch

from rtsp_tool.adb_client import (
    ADBClient,
    ADBDevice,
    CommandResult,
    YOLO_APP_REMOTE_PATH,
    YOLO_INSTALL_TIMEOUT,
    YOLO_MODEL_REMOTE_PATH,
    YOLO_UPDATE_DIR,
    build_shell_command,
    parse_adb_devices,
    parse_ifconfig_ip,
    parse_ip_route_ip,
    parse_usb0_ip,
)


SAFE_YOLO_INSTALL_COMMAND = (
    "app=/usr/bin/sample_smart_camera; model=/network_binary.nb; dir=/tmp/yolo_app_update; "
    "backup_app=$dir/sample_smart_camera.previous; backup_model=$dir/network_binary.nb.previous; "
    "if cp $app $backup_app && cp $model $backup_model && "
    "cp $dir/sample_smart_camera $app && cp $dir/network_binary.nb $model && chmod +x $app && sync; "
    "then rm -rf $dir; "
    "else cp $backup_app $app; cp $backup_model $model; chmod +x $app; sync; rm -rf $dir; false; fi"
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

    def test_parse_ifconfig_ip_allows_link_local_for_generic_discovery(self):
        output = """
wlan0     Link encap:Ethernet
          inet addr:169.254.8.9  Bcast:169.254.255.255  Mask:255.255.0.0
"""

        self.assertEqual(parse_ifconfig_ip(output), "169.254.8.9")

    def test_parse_usb0_ip_accepts_ip_addr_output(self):
        output = """
4: usb0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether 1a:2b:3c:4d:5e:6f brd ff:ff:ff:ff:ff:ff
    inet 192.168.137.22/24 brd 192.168.137.255 scope global usb0
       valid_lft forever preferred_lft forever
"""

        self.assertEqual(parse_usb0_ip(output), "192.168.137.22")

    def test_parse_usb0_ip_accepts_ifconfig_output(self):
        output = """
usb0      Link encap:Ethernet  HWaddr 1A:2B:3C:4D:5E:6F
          inet addr:192.168.137.33  Bcast:192.168.137.255  Mask:255.255.255.0
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1
"""

        self.assertEqual(parse_usb0_ip(output), "192.168.137.33")

    def test_parse_usb0_ip_rejects_loopback_zero_and_link_local(self):
        self.assertIsNone(parse_usb0_ip("inet 127.0.0.2/8 scope host lo\n"))
        self.assertIsNone(parse_usb0_ip("inet 0.1.2.3/24 scope global usb0\n"))
        self.assertIsNone(parse_usb0_ip("inet 0.0.0.0/24 scope global usb0\n"))
        self.assertIsNone(parse_usb0_ip("inet 255.255.255.255/32 scope global usb0\n"))
        self.assertIsNone(parse_usb0_ip("inet 169.254.8.9/16 scope link usb0\n"))

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

    def test_start_service_command_omits_rtsp_only_when_ai_detection_is_enabled(self):
        client = ADBClient(adb_path="adb")

        self.assertEqual(
            client.start_service_command("abc123", ai_enabled=True),
            [
                "adb",
                "-s",
                "abc123",
                "shell",
                "cd /tmp && /usr/bin/sample_smart_camera >/tmp/sample_smart_camera.log 2>&1",
            ],
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
                SAFE_YOLO_INSTALL_COMMAND,
            ],
        )
        self.assertEqual(YOLO_APP_REMOTE_PATH, "/usr/bin/sample_smart_camera")
        self.assertEqual(YOLO_MODEL_REMOTE_PATH, "/network_binary.nb")

    def test_yolo_install_command_rolls_back_pair_on_install_failure(self):
        client = ADBClient(adb_path="adb")
        shell_command = client.install_yolo_update_command("abc123")[-1]

        self.assertIn("backup_app=$dir/sample_smart_camera.previous", shell_command)
        self.assertIn("backup_model=$dir/network_binary.nb.previous", shell_command)
        self.assertLess(
            shell_command.index("cp $app $backup_app"),
            shell_command.index("cp $dir/sample_smart_camera $app"),
        )
        self.assertIn(
            "else cp $backup_app $app; cp $backup_model $model; chmod +x $app; sync; rm -rf $dir; false; fi",
            shell_command,
        )

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
                        SAFE_YOLO_INSTALL_COMMAND,
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

    def test_start_service_launches_ai_detection_mode(self):
        client = ADBClient(adb_path="adb")

        with patch("rtsp_tool.adb_client.subprocess.Popen") as popen:
            result = client.start_service("abc123", ai_enabled=True)

        popen.assert_called_once_with(
            [
                "adb",
                "-s",
                "abc123",
                "shell",
                "cd /tmp && /usr/bin/sample_smart_camera >/tmp/sample_smart_camera.log 2>&1",
            ],
            stdout=-3,
            stderr=-3,
        )
        self.assertTrue(result.ok)

    def test_start_service_reuses_original_command_when_local_process_is_running(self):
        client = ADBClient(adb_path="adb")
        rtsp_only_command = [
            "adb",
            "-s",
            "abc123",
            "shell",
            "cd /tmp && /usr/bin/sample_smart_camera --rtsp-only >/tmp/sample_smart_camera.log 2>&1",
        ]

        with patch("rtsp_tool.adb_client.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            first = client.start_service("abc123")
            second = client.start_service("abc123", ai_enabled=True)

        self.assertEqual(popen.call_count, 1)
        self.assertEqual(first.command, rtsp_only_command)
        self.assertEqual(second.command, rtsp_only_command)
        self.assertEqual(second.stdout, "already running")
        self.assertIn("--rtsp-only", second.command[-1])

    def test_wait_for_service_polls_until_pid_appears(self):
        client = ADBClient(adb_path="adb")

        with patch.object(client, "service_pid", side_effect=[None, "1228"]) as service_pid:
            with patch("rtsp_tool.adb_client.time.sleep") as sleep:
                running = client.wait_for_service("abc123", timeout=5.0, interval=0.1)

        self.assertTrue(running)
        self.assertEqual(service_pid.call_count, 2)
        sleep.assert_called_once_with(0.1)

    def test_discover_usb0_ip_uses_ip_addr_then_ifconfig(self):
        client = ADBClient(adb_path="adb")
        ip_addr_result = CommandResult(["adb"], 1, "", "Device does not have ip")
        ifconfig_result = CommandResult(
            ["adb"],
            0,
            "usb0      Link encap:Ethernet\n          inet addr:192.168.137.33  Mask:255.255.255.0\n",
            "",
        )

        with patch.object(client, "get_usb0_ip_addr_output", return_value=ip_addr_result) as ip_addr:
            with patch.object(client, "get_usb0_ifconfig_output", return_value=ifconfig_result) as ifconfig:
                self.assertEqual(client.discover_usb0_ip("abc123"), "192.168.137.33")

        ip_addr.assert_called_once_with("abc123")
        ifconfig.assert_called_once_with("abc123")

    def test_discover_usb0_ip_falls_back_when_ip_addr_has_no_valid_ip(self):
        client = ADBClient(adb_path="adb")
        ip_addr_result = CommandResult(
            ["adb"],
            0,
            "4: usb0: <UP> mtu 1500\n    inet 169.254.8.9/16 scope link usb0\n",
            "",
        )
        ifconfig_result = CommandResult(
            ["adb"],
            0,
            "usb0      Link encap:Ethernet\n          inet addr:192.168.137.33  Mask:255.255.255.0\n",
            "",
        )

        with patch.object(client, "get_usb0_ip_addr_output", return_value=ip_addr_result) as ip_addr:
            with patch.object(client, "get_usb0_ifconfig_output", return_value=ifconfig_result) as ifconfig:
                self.assertEqual(client.discover_usb0_ip("abc123"), "192.168.137.33")

        ip_addr.assert_called_once_with("abc123")
        ifconfig.assert_called_once_with("abc123")

    def test_discover_usb0_ip_prefers_ip_addr_when_present(self):
        client = ADBClient(adb_path="adb")
        ip_addr_result = CommandResult(
            ["adb"],
            0,
            "4: usb0: <UP> mtu 1500\n    inet 192.168.137.22/24 scope global usb0\n",
            "",
        )

        with patch.object(client, "get_usb0_ip_addr_output", return_value=ip_addr_result) as ip_addr:
            with patch.object(client, "get_usb0_ifconfig_output") as ifconfig:
                self.assertEqual(client.discover_usb0_ip("abc123"), "192.168.137.22")

        ip_addr.assert_called_once_with("abc123")
        ifconfig.assert_not_called()

    def test_usb0_commands_are_exact(self):
        client = ADBClient(adb_path="adb")
        result = CommandResult(["adb"], 0, "", "")

        with patch.object(client, "run", return_value=result) as run:
            self.assertIs(client.get_usb0_ip_addr_output("abc123"), result)
        run.assert_called_once_with(["-s", "abc123", "shell", "ip addr show usb0"], timeout=None)

        with patch.object(client, "run", return_value=result) as run:
            self.assertIs(client.get_usb0_ifconfig_output("abc123"), result)
        run.assert_called_once_with(["-s", "abc123", "shell", "ifconfig usb0"], timeout=None)


if __name__ == "__main__":
    unittest.main()
