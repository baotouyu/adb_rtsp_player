# ADB 摄像头推流播放器

这是一个中文界面的 Python 桌面小工具，用来通过 ADB 选择板端设备，自动检查并启动板端推流服务，然后用本机 `ffplay` 播放 RTSP 流。

## 功能

- 启动时检查可用运行工具：`adb`、`ffplay`、`tkinter`
- 自动列出 `adb devices`
- 手动选择设备
- 检查板端是否能直接运行 `/usr/bin/sample_smart_camera --rtsp-only`
- 检查板端推流服务是否已运行
- 未运行时自动执行：`/usr/bin/sample_smart_camera --rtsp-only`
- 自动读取板端 IP
- 自动生成：`rtsp://<设备IP>:8554/ch0`
- 扫描本地 `yolo_apps/yoloApp_*` 应用和模型包
- 一键覆盖更新板端 app/model
- 用独立 `ffplay` 窗口播放
- 支持停止本机播放、停止板端推流服务、复制 RTSP 地址

## Windows 免安装使用

给 Windows 用户发布 `ADB_RTSP_Player_Windows.zip`。用户只需要：

1. 下载 `ADB_RTSP_Player_Windows.zip`。
2. 解压 zip。
3. 双击 `ADB_RTSP_Player.exe`。
4. 选择 ADB 设备并点击“开始播放”。

发布包会内置：

```text
ADB_RTSP_Player/
  ADB_RTSP_Player.exe
  tools/
    adb/
      adb.exe
      AdbWinApi.dll
      AdbWinUsbApi.dll
      其他 Android platform-tools 文件和 notices
    ffmpeg/
      ffplay.exe
      *.dll
      FFmpeg/Gyan README、LICENSE、doc/、licenses/ 等文件
```

用户不需要安装 Python、Android platform-tools、FFmpeg 或 Python 包。

注意事项：

- 请保持解压后的 `ADB_RTSP_Player/` 文件夹完整，不要把 `ADB_RTSP_Player.exe` 移离相邻的 `tools/` 文件夹，也不要删除随包附带的 DLL、文档或许可文件。
- 第一次连接板子时，仍然需要在板端确认 USB 调试授权。
- 某些 Windows 电脑可能需要设备厂商的 USB/ADB 驱动，这是系统驱动问题，不是 Python 依赖问题。
- 如果 Windows 防火墙或安全软件弹窗，请允许本程序或 `ffplay.exe` 访问局域网。
- 未签名的 PyInstaller 程序可能触发 Windows SmartScreen 或杀毒软件提示；如果 zip 来自你信任的发布来源，可以选择允许或仍要运行。

## 开发运行

```bash
python3 app.py
```

开发模式下，程序会优先查找项目目录里的内置工具：

```text
tools/adb/adb
tools/adb/adb.exe
tools/ffmpeg/ffplay
tools/ffmpeg/ffplay.exe
```

如果没有内置工具，会继续从系统 `PATH` 查找 `adb` 和 `ffplay`。

## YOLO App 和模型包更新

本工具可以扫描本地 `yolo_apps/yoloApp_*` 目录，把一组配套的 YOLO app 和模型更新到板端。源码运行时，把 `yolo_apps/` 放在项目根目录下；Windows 免安装版用户把它放在 `ADB_RTSP_Player.exe` 同一层目录下。

本地目录格式示例：

```text
yolo_apps/
  yoloApp_苹果/
    sample_smart_camera
    network_binary.nb
```

使用约定：

- 文件夹名使用 `yoloApp_xxx`，其中 `xxx` 用来描述检测目标，例如 `yoloApp_苹果`。
- `sample_smart_camera` 和 `network_binary.nb` 是一对 app/model，应放在同一个 `yoloApp_xxx` 文件夹内，并保持名称和路径匹配。
- 点击“更新到板端”会先停止正在运行的 `sample_smart_camera`，再覆盖板端文件：`/usr/bin/sample_smart_camera` 和 `/network_binary.nb`；工具只会在更新过程中做临时回滚备份，不会为用户长期保留旧文件。
- 板端需要允许 ADB 写入 `/usr/bin/sample_smart_camera` 和 `/network_binary.nb`。如果 rootfs 只读、权限不足或需要 remount，请先在板端处理好。
- 如果勾选“更新后启动推流”，更新完成后会自动重新启动板端推流服务；不勾选时只完成文件更新，板端推流服务会保持停止状态。
- `yolo_apps/` 已加入 `.gitignore`，默认不会被 git 跟踪/提交，也不会打进主 Windows 发布包；发布或交付时让用户自行把该目录放到 exe/应用文件夹内即可。

## 板端要求

板端需要能通过 ADB shell 直接执行：

```bash
sample_smart_camera --rtsp-only
```

也就是你已经放到 `/usr/bin` 并且有执行权限。

软件会通过 ADB 启动这个绝对路径命令：

```bash
cd /tmp && /usr/bin/sample_smart_camera --rtsp-only >/tmp/sample_smart_camera.log 2>&1
```

## 开发模式依赖

本节只适用于从源码运行或开发调试。Windows 免安装 zip 用户不需要安装 Python、`adb`、`ffplay` 或 Python 包。

源码开发运行需要 Python 3，并且程序需要能找到：

```bash
adb
ffplay
tkinter
```

如果项目目录里没有内置工具，请自行安装 Android platform-tools 和 FFmpeg，并确保 `adb`、`ffplay` 可以从系统 `PATH` 找到。

## 常见问题

- 设备显示 `unauthorized`：看板子屏幕，确认 USB 调试授权。
- 设备显示 `offline`：重插 USB，或执行 `adb kill-server && adb start-server`。
- 提示找不到 `sample_smart_camera`：确认板端 `/usr/bin/sample_smart_camera` 存在并可执行。
- 推流服务启动失败：在板端查看 `/tmp/sample_smart_camera.log`。
- 有 RTSP 地址但不能播放：先确认板端服务运行，再确认本机能访问该 IP。

## Windows 打包

推荐在 GitHub Actions 的 Windows runner 上打包。手动打包需要：

- Windows 开发机或 Windows runner。
- Python 3.12（推荐）和 pip。
- PowerShell。
- 运行 `python -m pip install -r requirements-build.txt`，这会安装固定版本的 PyInstaller 等打包依赖。
- 完整填充的 `tools/adb` 和 `tools/ffmpeg` 目录。

手动打包前需要准备好以下目录：

```text
tools/
  adb/
    adb.exe
    AdbWinApi.dll
    AdbWinUsbApi.dll
    其他 Android platform-tools 文件和 notices
  ffmpeg/
    ffplay.exe
    *.dll
    FFmpeg/Gyan README、LICENSE、doc/、licenses/ 等文件
```

构建脚本是 `scripts/build_windows.ps1`。然后执行：

```powershell
python -m pip install -r requirements-build.txt
.\scripts\build_windows.ps1
```

脚本会运行测试、执行 PyInstaller、复制 `tools` 目录，并生成：

```text
dist/ADB_RTSP_Player_Windows.zip
```

最简单的方式是使用 GitHub Actions：workflow 会自动下载并校验固定版本的 Android platform-tools r37.0.0 和 FFmpeg 8.1.1 essentials，然后上传可直接解压的 Windows artifact；下载该 artifact 后解压一次即可看到 `ADB_RTSP_Player/` 文件夹。

重新分发发布包时，不要删减 FFmpeg/Gyan 的 license、readme、doc 文件，Android platform-tools 的 notices，邻近 DLL，或其他随包文件。

## 测试

```bash
python3 -m unittest discover -v
python3 -m py_compile app.py rtsp_tool/*.py
```
