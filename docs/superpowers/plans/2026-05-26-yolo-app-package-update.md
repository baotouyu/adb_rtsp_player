# YOLO App Package Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI workflow that scans local `yolo_apps/yoloApp_*` folders and overwrites the board's single active `/usr/bin/sample_smart_camera` plus `/network_binary.nb` app/model pair over ADB.

**Architecture:** Keep package scanning, ADB command/install behavior, and Tkinter UI wiring separate. `rtsp_tool/yolo_package.py` owns local package discovery/validation, `rtsp_tool/adb_client.py` owns board update commands, and `rtsp_tool/gui.py` presents package selection and runs updates in the existing background-worker pattern.

**Tech Stack:** Python stdlib, Tkinter/ttk, unittest, existing ADB subprocess wrapper.

---

## Scope Check

This is one coherent feature: local YOLO app/model package selection plus overwrite installation to the board. It does not add remote package downloads, multiple package slots on the board, rollback, semantic versions, or manifest files.

## File Structure

- Create `rtsp_tool/yolo_package.py`: scan and validate local `yolo_apps/yoloApp_*` directories.
- Create `tests/test_yolo_package.py`: unit tests for package scanning and validation.
- Modify `rtsp_tool/adb_client.py`: add command builders and install flow for `/usr/bin/sample_smart_camera` and `/network_binary.nb`.
- Modify `tests/test_adb_client.py`: tests for update command construction and install sequencing.
- Modify `rtsp_tool/i18n.py`: add labels for the package-update UI.
- Modify `rtsp_tool/gui.py`: add package selection UI, refresh/update behavior, confirmation, and optional start-after-update flow.
- Modify `README.md`: document local `yolo_apps/` layout and board overwrite behavior.
- Modify `.gitignore`: ignore `yolo_apps/` so large model/app binaries are not committed.

---

### Task 1: Local YOLO Package Discovery

**Files:**
- Create: `rtsp_tool/yolo_package.py`
- Create: `tests/test_yolo_package.py`

- [ ] **Step 1: Write failing package discovery tests**

Create `tests/test_yolo_package.py` with this content:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rtsp_tool.yolo_package import (
    REQUIRED_APP_FILENAME,
    REQUIRED_MODEL_FILENAME,
    YoloPackage,
    package_display_name,
    scan_yolo_packages,
    validate_yolo_package,
    yolo_apps_dir,
)


class YoloPackageTests(unittest.TestCase):
    def _write(self, path: Path, content: str = "x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_yolo_apps_dir_is_next_to_app_dir(self):
        self.assertEqual(yolo_apps_dir(Path("/opt/tool")), Path("/opt/tool") / "yolo_apps")

    def test_package_display_name_strips_prefix_when_present(self):
        self.assertEqual(package_display_name("yoloApp_苹果"), "苹果")
        self.assertEqual(package_display_name("other"), "other")

    def test_validate_yolo_package_accepts_required_files(self):
        with TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "yoloApp_苹果"
            self._write(package_dir / REQUIRED_APP_FILENAME)
            self._write(package_dir / REQUIRED_MODEL_FILENAME)

            package = validate_yolo_package(package_dir)

        self.assertEqual(
            package,
            YoloPackage(
                name="yoloApp_苹果",
                display_name="苹果",
                path=package_dir,
                app_path=package_dir / REQUIRED_APP_FILENAME,
                model_path=package_dir / REQUIRED_MODEL_FILENAME,
            ),
        )

    def test_validate_yolo_package_reports_missing_required_files(self):
        with TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "yoloApp_苹果"
            package_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "sample_smart_camera, network_binary.nb"):
                validate_yolo_package(package_dir)

    def test_scan_yolo_packages_returns_only_valid_yolo_app_directories_sorted(self):
        with TemporaryDirectory() as tmpdir:
            apps_dir = Path(tmpdir) / "yolo_apps"
            valid_banana = apps_dir / "yoloApp_香蕉"
            valid_apple = apps_dir / "yoloApp_苹果"
            invalid = apps_dir / "yoloApp_缺文件"
            ignored = apps_dir / "other_苹果"
            for package_dir in (valid_banana, valid_apple):
                self._write(package_dir / REQUIRED_APP_FILENAME)
                self._write(package_dir / REQUIRED_MODEL_FILENAME)
            self._write(invalid / REQUIRED_APP_FILENAME)
            self._write(ignored / REQUIRED_APP_FILENAME)
            self._write(ignored / REQUIRED_MODEL_FILENAME)

            packages = scan_yolo_packages(apps_dir)

        self.assertEqual([package.name for package in packages], ["yoloApp_苹果", "yoloApp_香蕉"])
        self.assertEqual([package.display_name for package in packages], ["苹果", "香蕉"])

    def test_scan_yolo_packages_returns_empty_when_directory_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            self.assertEqual(scan_yolo_packages(Path(tmpdir) / "missing"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_yolo_package -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors because `rtsp_tool.yolo_package` does not exist.

- [ ] **Step 3: Implement package discovery**

Create `rtsp_tool/yolo_package.py` with this content:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PACKAGE_PREFIX = "yoloApp_"
REQUIRED_APP_FILENAME = "sample_smart_camera"
REQUIRED_MODEL_FILENAME = "network_binary.nb"


@dataclass(frozen=True)
class YoloPackage:
    name: str
    display_name: str
    path: Path
    app_path: Path
    model_path: Path


def yolo_apps_dir(app_dir: Path | str) -> Path:
    return Path(app_dir) / "yolo_apps"


def package_display_name(package_name: str) -> str:
    if package_name.startswith(PACKAGE_PREFIX):
        return package_name[len(PACKAGE_PREFIX) :] or package_name
    return package_name


def validate_yolo_package(package_dir: Path | str) -> YoloPackage:
    path = Path(package_dir)
    app_path = path / REQUIRED_APP_FILENAME
    model_path = path / REQUIRED_MODEL_FILENAME
    missing = [filename for filename, file_path in ((REQUIRED_APP_FILENAME, app_path), (REQUIRED_MODEL_FILENAME, model_path)) if not file_path.is_file()]
    if missing:
        raise ValueError(f"{path.name} 缺少必需文件：{', '.join(missing)}")
    return YoloPackage(
        name=path.name,
        display_name=package_display_name(path.name),
        path=path,
        app_path=app_path,
        model_path=model_path,
    )


def scan_yolo_packages(apps_dir: Path | str) -> list[YoloPackage]:
    root = Path(apps_dir)
    if not root.is_dir():
        return []
    packages: list[YoloPackage] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or not candidate.name.startswith(PACKAGE_PREFIX):
            continue
        try:
            packages.append(validate_yolo_package(candidate))
        except ValueError:
            continue
    return packages
```

- [ ] **Step 4: Run package tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_yolo_package -v
```

Expected: PASS with six tests.

- [ ] **Step 5: Run the full test suite**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add rtsp_tool/yolo_package.py tests/test_yolo_package.py
git commit -m "feat: discover local yolo app packages"
```

---

### Task 2: ADB YOLO Package Install Flow

**Files:**
- Modify: `rtsp_tool/adb_client.py`
- Modify: `tests/test_adb_client.py`

- [ ] **Step 1: Write failing ADB install tests**

Add these imports to the existing import block in `tests/test_adb_client.py`:

```python
    YOLO_APP_REMOTE_PATH,
    YOLO_MODEL_REMOTE_PATH,
    YOLO_UPDATE_DIR,
```

Add these tests inside `ADBClientTests`:

```python
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
            result = client.install_yolo_package(
                "abc123",
                app_path="/local/yoloApp_苹果/sample_smart_camera",
                model_path="/local/yoloApp_苹果/network_binary.nb",
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            calls,
            [
                ((["-s", "abc123", "shell", "pkill sample_smart_camera || true"]), None),
                ((["-s", "abc123", "shell", "rm -rf /tmp/yolo_app_update && mkdir -p /tmp/yolo_app_update"]), None),
                ((["-s", "abc123", "push", "/local/yoloApp_苹果/sample_smart_camera", "/tmp/yolo_app_update/sample_smart_camera"]), None),
                ((["-s", "abc123", "push", "/local/yoloApp_苹果/network_binary.nb", "/tmp/yolo_app_update/network_binary.nb"]), None),
                ((
                    [
                        "-s",
                        "abc123",
                        "shell",
                        "cp /tmp/yolo_app_update/sample_smart_camera /usr/bin/sample_smart_camera && "
                        "cp /tmp/yolo_app_update/network_binary.nb /network_binary.nb && "
                        "chmod +x /usr/bin/sample_smart_camera && sync && rm -rf /tmp/yolo_app_update",
                    ]
                ), None),
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
```

- [ ] **Step 2: Run ADB tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_adb_client -v
```

Expected: FAIL because YOLO constants and methods do not exist.

- [ ] **Step 3: Implement ADB install helpers**

In `rtsp_tool/adb_client.py`, add these constants after `SERVICE_LOG`:

```python
YOLO_UPDATE_DIR = "/tmp/yolo_app_update"
YOLO_APP_REMOTE_PATH = SERVICE_PATH
YOLO_MODEL_REMOTE_PATH = "/network_binary.nb"
```

Add these methods to `ADBClient` after `stop_service_command`:

```python
    def prepare_yolo_update_command(self, serial: str) -> list[str]:
        return build_shell_command(self.adb_path, serial, f"rm -rf {YOLO_UPDATE_DIR} && mkdir -p {YOLO_UPDATE_DIR}")

    def push_yolo_file_command(self, serial: str, local_path: str, remote_path: str) -> list[str]:
        return [self.adb_path, "-s", serial, "push", local_path, remote_path]

    def install_yolo_update_command(self, serial: str) -> list[str]:
        shell_command = (
            f"cp {YOLO_UPDATE_DIR}/sample_smart_camera {YOLO_APP_REMOTE_PATH} && "
            f"cp {YOLO_UPDATE_DIR}/network_binary.nb {YOLO_MODEL_REMOTE_PATH} && "
            f"chmod +x {YOLO_APP_REMOTE_PATH} && sync && rm -rf {YOLO_UPDATE_DIR}"
        )
        return build_shell_command(self.adb_path, serial, shell_command)
```

Add this method after `stop_service`:

```python
    def install_yolo_package(self, serial: str, app_path: str, model_path: str) -> CommandResult:
        steps = [
            ["-s", serial, "shell", f"pkill {SERVICE_NAME} || true"],
            ["-s", serial, "shell", f"rm -rf {YOLO_UPDATE_DIR} && mkdir -p {YOLO_UPDATE_DIR}"],
            ["-s", serial, "push", app_path, f"{YOLO_UPDATE_DIR}/sample_smart_camera"],
            ["-s", serial, "push", model_path, f"{YOLO_UPDATE_DIR}/network_binary.nb"],
            [
                "-s",
                serial,
                "shell",
                f"cp {YOLO_UPDATE_DIR}/sample_smart_camera {YOLO_APP_REMOTE_PATH} && "
                f"cp {YOLO_UPDATE_DIR}/network_binary.nb {YOLO_MODEL_REMOTE_PATH} && "
                f"chmod +x {YOLO_APP_REMOTE_PATH} && sync && rm -rf {YOLO_UPDATE_DIR}",
            ],
        ]
        last_result = CommandResult([], 0, "", "")
        for step in steps:
            last_result = self.run(step)
            if not last_result.ok:
                return last_result
        return last_result
```

- [ ] **Step 4: Run ADB tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_adb_client -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add rtsp_tool/adb_client.py tests/test_adb_client.py
git commit -m "feat: install yolo app package over adb"
```

---

### Task 3: GUI Package Selection And Update Controls

**Files:**
- Modify: `rtsp_tool/i18n.py`
- Modify: `rtsp_tool/gui.py`

- [ ] **Step 1: Add UI labels**

In `rtsp_tool/i18n.py`, add these keys to `TEXT`:

```python
    "yolo_package": "模型/App 组合",
    "refresh_yolo_packages": "刷新组合包",
    "update_yolo_package": "更新到板端",
    "start_after_update": "更新后启动推流",
```

- [ ] **Step 2: Wire package state and scanning into the GUI**

In `rtsp_tool/gui.py`, add imports:

```python
from .dependencies import DependencyStatus, check_dependencies, get_app_dir
from .yolo_package import YoloPackage, scan_yolo_packages, yolo_apps_dir
```

Replace the current dependency import line with the first line above.

In `RTSPToolApp.__init__`, after `self.dep_vars` initialization, add:

```python
        self.yolo_packages: dict[str, YoloPackage] = {}
        self.selected_yolo_package = tk.StringVar(value="")
        self.start_after_update = tk.BooleanVar(value=False)
        self.yolo_apps_path = yolo_apps_dir(get_app_dir())
```

- [ ] **Step 3: Add the UI section**

In `_build_ui`, after the stream frame and before `controls`, add:

```python
        package_frame = ttk.LabelFrame(self.root, text=TEXT["yolo_package"])
        package_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        package_frame.columnconfigure(1, weight=1)
        ttk.Label(package_frame, text=TEXT["yolo_package"]).grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.yolo_package_combo = ttk.Combobox(
            package_frame,
            textvariable=self.selected_yolo_package,
            values=[],
            state="readonly",
        )
        self.yolo_package_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.refresh_yolo_packages_button = ttk.Button(
            package_frame, text=TEXT["refresh_yolo_packages"], command=self.refresh_yolo_packages
        )
        self.refresh_yolo_packages_button.grid(row=0, column=2, sticky="ew", padx=6, pady=8)
        self.update_yolo_package_button = ttk.Button(
            package_frame, text=TEXT["update_yolo_package"], command=self.update_yolo_package
        )
        self.update_yolo_package_button.grid(row=0, column=3, sticky="ew", padx=6, pady=8)
        self.start_after_update_check = ttk.Checkbutton(
            package_frame, text=TEXT["start_after_update"], variable=self.start_after_update
        )
        self.start_after_update_check.grid(row=0, column=4, sticky="w", padx=6, pady=8)
```

Adjust the existing controls and log/status rows down by one:

```python
        controls.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        log_frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=(6, 12))
        status_bar.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 8))
```

Change `self.root.rowconfigure(4, weight=1)` to `self.root.rowconfigure(5, weight=1)`.

At the end of `__init__`, before the ADB refresh block, call:

```python
        self.refresh_yolo_packages()
```

- [ ] **Step 4: Update button state logic**

In `_update_button_states`, add:

```python
        has_yolo_package = bool(self.selected_yolo_package.get())
```

At the end of `_update_button_states`, add:

```python
        self.update_yolo_package_button.configure(state="normal" if has_adb and has_device and has_yolo_package else "disabled")
```

- [ ] **Step 5: Add package refresh and selected package helpers**

Add these methods to `RTSPToolApp` before `refresh_devices`:

```python
    def refresh_yolo_packages(self) -> None:
        packages = scan_yolo_packages(self.yolo_apps_path)
        self.yolo_packages = {package.name: package for package in packages}
        names = list(self.yolo_packages)
        self.yolo_package_combo.configure(values=names)
        if names and self.selected_yolo_package.get() not in self.yolo_packages:
            self.selected_yolo_package.set(names[0])
        elif not names:
            self.selected_yolo_package.set("")
        if names:
            self.log(f"找到 {len(names)} 个模型/App 组合包。")
        else:
            self.log(f"没有找到模型/App 组合包。请放到：{self.yolo_apps_path}")
        self._update_button_states()

    def _selected_yolo_package(self) -> YoloPackage | None:
        name = self.selected_yolo_package.get()
        if not name:
            messagebox.showwarning("未选择组合包", f"请先在 {self.yolo_apps_path} 放入 yoloApp_* 组合包。")
            return None
        package = self.yolo_packages.get(name)
        if not package:
            messagebox.showwarning("组合包不存在", "请刷新组合包列表后重新选择。")
            return None
        return package
```

- [ ] **Step 6: Add update behavior**

Add this method to `RTSPToolApp` before `start_board_service`:

```python
    def update_yolo_package(self) -> None:
        device = self._require_selected_device()
        if not device:
            return
        package = self._selected_yolo_package()
        if not package:
            return
        confirmed = messagebox.askyesno(
            "确认覆盖板端 App/模型",
            f"将用 {package.name} 覆盖板端当前文件：\n"
            "/usr/bin/sample_smart_camera\n"
            "/network_binary.nb\n\n"
            "板端只保留这一套 App 和模型。是否继续？",
        )
        if not confirmed:
            return

        def work() -> None:
            self._ui(self.log, f"正在更新模型/App 组合 {package.name}")
            result = self.adb.install_yolo_package(device.serial, str(package.app_path), str(package.model_path))
            if not result.ok:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "模型/App 更新失败。")
            self._ui(self.log, f"模型/App 组合 {package.name} 已更新到板端。")
            self._ui(self.service_status.set, state_text("stopped"))
            if self.start_after_update.get():
                url = self._inspect_device(device.serial, start_if_needed=True)
                command = self.player.start(url)
                self._ui(self.log, "已启动 ffplay：" + " ".join(command))
                self._ui(self._update_button_states)

        self._run_background("正在更新模型/App 组合中", work)
```

- [ ] **Step 7: Run syntax check**

Run:

```bash
python3 -m py_compile app.py rtsp_tool/*.py
```

Expected: no output.

- [ ] **Step 8: Run full tests**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add rtsp_tool/i18n.py rtsp_tool/gui.py
git commit -m "feat: add yolo package update controls"
```

---

### Task 4: Documentation And Git Ignore

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Ignore local package binaries**

Add this line to `.gitignore` near `tools/`:

```gitignore
yolo_apps/
```

- [ ] **Step 2: Document package layout and update behavior**

Add this section to `README.md` after `## 开发运行` and before `## 板端要求`:

```markdown
## 模型/App 组合包

本工具支持把板端 App 和模型作为一套组合包更新。组合包放在程序旁边的 `yolo_apps/` 目录中，目录名使用 `yoloApp_检测对象`：

```text
yolo_apps/
  yoloApp_苹果/
    sample_smart_camera
    network_binary.nb
  yoloApp_香蕉/
    sample_smart_camera
    network_binary.nb
```

第一版每个组合包必须包含：

```text
sample_smart_camera
network_binary.nb
```

板端 flash 较小，只保留一套当前 App 和模型。点击“更新到板端”会覆盖：

```text
/usr/bin/sample_smart_camera
/network_binary.nb
```

更新前会停止正在运行的 `sample_smart_camera`。更新后可以勾选“更新后启动推流”，让工具自动启动新的 App 并开始播放。

`yolo_apps/` 可能包含大模型和板端二进制文件，默认不会提交到 git，也不会内置进 Windows 主程序包。Windows 用户可以把 `yolo_apps/` 放到 `ADB_RTSP_Player.exe` 同级目录。
```

- [ ] **Step 3: Update feature list**

Add these bullets to the feature list in `README.md`:

```markdown
- 扫描本地 `yolo_apps/yoloApp_*` 模型/App 组合包
- 一键覆盖更新板端 `/usr/bin/sample_smart_camera` 和 `/network_binary.nb`
```

- [ ] **Step 4: Verify docs mention required paths**

Run:

```bash
rg -n "yolo_apps|yoloApp_|network_binary.nb|/network_binary.nb" README.md .gitignore
```

Expected: output includes README and `.gitignore` matches.

- [ ] **Step 5: Run tests and compile check**

Run:

```bash
python3 -m unittest discover -v
python3 -m py_compile app.py rtsp_tool/*.py
```

Expected: PASS and no compile output.

- [ ] **Step 6: Commit**

Run:

```bash
git add .gitignore README.md
git commit -m "docs: explain yolo app package layout"
```

---

### Task 5: Final Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
python3 -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 2: Run compile checks**

Run:

```bash
python3 -m py_compile app.py rtsp_tool/*.py
```

Expected: no output.

- [ ] **Step 3: Check git ignore behavior**

Run:

```bash
mkdir -p yolo_apps/yoloApp_测试
touch yolo_apps/yoloApp_测试/sample_smart_camera yolo_apps/yoloApp_测试/network_binary.nb
git check-ignore -v yolo_apps/yoloApp_测试/sample_smart_camera yolo_apps/yoloApp_测试/network_binary.nb
rm -rf yolo_apps
```

Expected: both files are ignored by `.gitignore`.

- [ ] **Step 4: Check package docs and UI strings**

Run:

```bash
rg -n "yolo_apps|yoloApp_|network_binary.nb|更新到板端|更新后启动推流" README.md rtsp_tool tests
```

Expected: matching docs, UI labels, and tests.

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short --branch
```

Expected: clean working tree, ahead of origin by new commits until pushed.

- [ ] **Step 6: Push when credentials are ready**

Run:

```bash
git push
```

Expected: remote `main` updated. If GitHub rejects the workflow file, ensure the token has both `Contents: Read and write` and `Workflows: Read and write`.
