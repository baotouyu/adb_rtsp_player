# Windows ICS USB 网络共享设计

## 背景

Windows 用户需要把电脑网络通过 USB/RNDIS 网卡共享给板端。板端通过 `usb0` DHCP 获取 IP 后，工具才能用该 IP 访问 RTSP。

当前手动流程是：用户打开 Windows 网络连接页面，给上网网卡启用 Internet Connection Sharing (ICS)，共享目标选择板子的 USB/RNDIS 网卡。这个流程难找、容易选错，所以需要放进 app 里。

## 目标

在桌面 app 中新增“USB 网络共享”能力：优先自动识别并配置 Windows ICS；如果自动配置失败，则打开系统网络设置并展示手动步骤。

成功标准：

- Windows 用户不需要自己搜索“网络共享在哪里”。
- app 能尽量自动识别 RNDIS/USB 网卡和上网网卡。
- app 能以管理员权限尝试启用 ICS。
- 自动失败时，app 能明确告诉用户怎么手动配置。
- 配置后 app 能帮助用户确认板端 `usb0` 是否拿到 IP。

## 非目标

- 不在 macOS/Linux 上配置 ICS；非 Windows 只显示不支持说明。
- 不静默修改系统网络设置；启用 ICS 前必须让用户确认。
- 不保证所有 Windows 版本/公司管控电脑都能自动配置；失败必须 fallback 到手动设置。
- 不实现永久后台服务或驱动安装。

## UI 设计

在主界面增加一个 `USB 网络共享` 区域，放在设备列表和推流信息之间，或放在推流信息附近，避免用户找不到。

控件：

- `检测网络适配器`：刷新 Windows 网络适配器信息。
- `自动配置 USB 共享`：尝试用管理员 PowerShell 配置 ICS。
- `打开手动设置`：打开 Windows 网络连接页面 `ncpa.cpl`。
- 上网网卡下拉框：显示候选 Wi-Fi/以太网网卡。
- 板子 USB 网卡下拉框：显示候选 RNDIS/USB 网卡。
- 状态文本：显示当前检测、配置、失败原因和下一步。

日志示例：

- `检测到上网网卡：Wi-Fi`
- `检测到板子 USB 网卡：Remote NDIS Compatible Device`
- `正在请求管理员权限配置 Windows 网络共享...`
- `ICS 配置完成。请等待板端 usb0 通过 DHCP 获取 IP。`
- `未能自动配置 ICS，已打开网络连接页面，请按提示手动启用共享。`

## 自动识别规则

### 板子 USB/RNDIS 网卡

优先匹配网卡名称、描述或接口别名中的关键词：

- `RNDIS`
- `Remote NDIS`
- `USB Ethernet`
- `USB Ethernet/RNDIS Gadget`
- `Ethernet Gadget`
- `USB` + `Ethernet`

如果只找到一个候选，自动选中。若找到多个，保留全部让用户从下拉框选择。

### 上网网卡

优先选择：

- 状态为 Up/Connected。
- 有默认路由或 IPv4 网关。
- 不是 RNDIS/USB 网卡。
- 名称常见为 `Wi-Fi`、`WLAN`、`Ethernet`、`以太网`。

如果只找到一个候选，自动选中。若找到多个，让用户选择。

## Windows ICS 自动配置

自动配置通过管理员 PowerShell 子进程执行，不在主进程里直接提升权限。

流程：

1. 用户点击 `自动配置 USB 共享`。
2. app 检查是否选中上网网卡和 USB/RNDIS 网卡。
3. app 弹确认框，说明会修改 Windows 网络共享设置，并可能弹出 UAC。
4. app 生成临时 PowerShell 脚本并用 `Start-Process PowerShell -Verb RunAs` 以管理员权限运行。
5. 脚本通过 Windows HNetCfg COM 接口配置 ICS：
   - Public/shared source：上网网卡。
   - Private/home target：板子 USB/RNDIS 网卡。
6. 脚本输出结果到临时 JSON/status 文件。
7. app 读取结果并更新日志。

如果自动配置失败：

- 记录失败原因。
- 自动打开 `ncpa.cpl`。
- 在 app 里展示手动步骤。

## 手动 fallback

`打开手动设置` 按钮执行：

```text
control.exe ncpa.cpl
```

app 同时显示中文步骤：

1. 右键当前上网网卡（例如 Wi-Fi/以太网）。
2. 点“属性”。
3. 进入“共享”页签。
4. 勾选“允许其他网络用户通过此计算机的 Internet 连接来连接”。
5. “家庭网络连接”选择板子的 RNDIS/USB 网卡。
6. 确认后等待板端 `usb0` 获取 IP。

## 板端 usb0 IP 检测

在 ADB 设备已连接时，app 提供 `检测 usb0 IP` 或在配置完成后自动尝试检测。

命令顺序：

1. `adb shell ip addr show usb0`
2. fallback: `adb shell ifconfig usb0`

解析 IPv4 地址，过滤：

- `127.*`
- `0.0.0.0`
- `169.254.*` 链路本地地址

检测到后：

- 更新设备 IP。
- 生成 RTSP URL：`rtsp://检测到的usb0地址:8554/ch0`。
- 日志提示 `板端 usb0 IP：...`。

## 错误处理

- 非 Windows：禁用自动配置按钮，显示“此功能仅适用于 Windows”。
- 未找到 RNDIS 网卡：提示检查 USB 线、驱动、设备是否已上电。
- 未找到上网网卡：提示连接 Wi-Fi/以太网后重新检测。
- 多个候选：让用户选择，不自动猜。
- UAC 被取消：提示用户取消了管理员授权，并提供手动设置入口。
- COM/ICS 配置失败：显示失败原因并打开 `ncpa.cpl`。
- ADB 未连接：ICS 仍可配置，但 usb0 IP 检测按钮禁用或提示先连接设备。

## 安全与权限

- 启用 ICS 前必须弹确认框。
- 自动配置需要管理员权限，预期会弹 UAC。
- 不保存管理员凭据。
- 临时 PowerShell 脚本和结果文件使用系统临时目录，并在读取后尽量清理。

## 测试策略

单元测试：

- RNDIS/USB 网卡识别规则。
- 上网网卡候选选择规则。
- 多候选时不自动选择错误网卡。
- `ip addr show usb0` 和 `ifconfig usb0` 输出解析。
- 非 Windows 时按钮/状态逻辑。
- PowerShell 命令生成，不直接在测试里修改系统 ICS。
- 自动配置失败时 fallback 到 `ncpa.cpl` 的 GUI 逻辑。

手动验证：

- Windows 真机连接板子 USB/RNDIS。
- 点击检测，确认能识别 Wi-Fi 和 RNDIS。
- 点击自动配置，确认 UAC 弹出。
- 板端 `ifconfig usb0` 能看到 DHCP 地址。
- app 能用 usb0 IP 生成 RTSP URL 并播放。
