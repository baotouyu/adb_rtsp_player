# YOLO App Package Update Design

## Goal

Add a GUI workflow for updating the board-side camera application and model as one inseparable package. A local package directory named `yoloApp_<target>` represents one detection target, such as `yoloApp_苹果` or `yoloApp_安全帽`.

The board has limited flash and only keeps one active app/model pair at a time. Installing a package overwrites the previous board-side app and model.

## Package Convention

Local packages live under `yolo_apps/` next to the source project or next to the packaged Windows executable:

```text
yolo_apps/
  yoloApp_苹果/
    sample_smart_camera
    network_binary.nb
  yoloApp_香蕉/
    sample_smart_camera
    network_binary.nb
```

The first implementation supports exactly these required files:

```text
sample_smart_camera
network_binary.nb
```

The folder name is the user-facing package name. The suffix after `yoloApp_` describes what the package detects.

## Board Install Paths

Each update overwrites the single active board-side slot:

```text
sample_smart_camera -> /usr/bin/sample_smart_camera
network_binary.nb   -> /network_binary.nb
```

The app has the model path fixed internally, so the tool does not pass model paths as startup arguments. After installation, normal streaming still starts with:

```bash
/usr/bin/sample_smart_camera --rtsp-only
```

## User Flow

1. User places one or more package folders under `yolo_apps/`.
2. User opens the desktop tool.
3. Tool scans `yolo_apps/yoloApp_*` and lists valid packages.
4. User selects an ADB device.
5. User selects a package, for example `yoloApp_苹果`.
6. User clicks `更新 App/模型`.
7. Tool shows a confirmation dialog warning that the board's current app and model will be overwritten.
8. Tool stops the current board service if it is running.
9. Tool pushes the package files to a temporary board directory.
10. Tool copies files into their fixed board paths, sets execute permission on the app, runs `sync`, and removes temporary files.
11. Tool logs success and optionally lets the user start streaming with the newly installed package.

## ADB Update Flow

Use a temporary directory to avoid partially overwriting the active files before both uploads finish:

```text
/tmp/yolo_app_update/sample_smart_camera
/tmp/yolo_app_update/network_binary.nb
```

Installation steps:

```bash
pkill sample_smart_camera || true
rm -rf /tmp/yolo_app_update
mkdir -p /tmp/yolo_app_update
adb push <package>/sample_smart_camera /tmp/yolo_app_update/sample_smart_camera
adb push <package>/network_binary.nb /tmp/yolo_app_update/network_binary.nb
cp /tmp/yolo_app_update/sample_smart_camera /usr/bin/sample_smart_camera
cp /tmp/yolo_app_update/network_binary.nb /network_binary.nb
chmod +x /usr/bin/sample_smart_camera
sync
rm -rf /tmp/yolo_app_update
```

The GUI should run these steps in the existing background worker pattern so the window remains responsive.

## UI Changes

Add a new section near the existing controls:

```text
模型/App 组合
[ yoloApp_苹果 v ] [刷新组合包]
[更新到板端] [更新后启动推流]
```

Button behavior:

- `刷新组合包`: rescans `yolo_apps/`.
- `更新到板端`: installs the selected package to the selected board.
- `更新后启动推流`: optional checkbox. If enabled, after a successful install the tool starts the board service and starts playback using the existing flow.

If no package is found, disable update controls and log a clear message telling the user where to put package folders.

## Code Structure

Create a focused package module:

```text
rtsp_tool/yolo_package.py
```

Responsibilities:

- Locate `yolo_apps/` relative to the app directory.
- Scan folders matching `yoloApp_*`.
- Validate that each package contains `sample_smart_camera` and `network_binary.nb`.
- Return clear validation errors for missing files.

Suggested data model:

```python
@dataclass(frozen=True)
class YoloPackage:
    name: str
    path: Path
    app_path: Path
    model_path: Path
```

Extend `rtsp_tool/adb_client.py` with package installation helpers. Keep command construction testable and separate from GUI code.

Suggested constants:

```python
YOLO_UPDATE_DIR = "/tmp/yolo_app_update"
YOLO_APP_REMOTE_PATH = "/usr/bin/sample_smart_camera"
YOLO_MODEL_REMOTE_PATH = "/network_binary.nb"
```

## Packaging And Git Behavior

`yolo_apps/` can contain large binary app/model files and should not be committed to git by default. It should be ignored in `.gitignore`.

The Windows app package should not bundle detection packages by default. Users can copy `yolo_apps/` beside the executable:

```text
ADB_RTSP_Player/
  ADB_RTSP_Player.exe
  tools/
  yolo_apps/
    yoloApp_苹果/
      sample_smart_camera
      network_binary.nb
```

This keeps the main desktop tool small and lets model/app packages be distributed separately.

## Error Handling

Local validation errors:

- Missing `yolo_apps/`: log where to create it.
- Missing package files: show the package name and missing file.
- No valid packages: disable update button.

Device/update errors:

- No selected device: show existing warning pattern.
- Device not in `device` state: reuse existing device-state warning.
- `adb push` failure: stop and show stdout/stderr.
- Copy/chmod/sync failure: stop and show the failing command output.
- Cleanup failure: log it but keep the primary failure/success message clear.

Before overwrite, show a confirmation dialog because the board only keeps one active package.

## Testing Strategy

Unit tests:

- Scan only directories matching `yoloApp_*`.
- Valid package requires both `sample_smart_camera` and `network_binary.nb`.
- Missing files produce clear validation errors.
- Command builders produce the expected push/install commands.
- Install flow stops old service, uploads both files, copies to `/usr/bin/sample_smart_camera` and `/network_binary.nb`, chmods app, syncs, and cleans temp dir.

Manual tests:

1. Create `yolo_apps/yoloApp_测试/` with the two required files.
2. Launch the GUI and confirm the package appears.
3. Select a board and install the package.
4. Verify board files exist at `/usr/bin/sample_smart_camera` and `/network_binary.nb`.
5. Start streaming and confirm the new app/model pair runs.
6. Install a second package and confirm it overwrites the previous one.

## Acceptance Criteria

- User can place multiple local `yoloApp_*` folders under `yolo_apps/`.
- GUI lists valid local packages.
- GUI blocks installation when required files are missing.
- Installing a package overwrites the board's current `/usr/bin/sample_smart_camera` and `/network_binary.nb`.
- Existing RTSP start/stop/playback behavior still works after package update.
- `yolo_apps/` is ignored by git and not bundled into the default Windows package.
