"""Chinese UI text for the desktop app."""

TEXT = {
    "app_title": "ADB 摄像头推流播放器",
    "dependencies": "依赖检测",
    "devices": "ADB 设备",
    "stream": "推流信息",
    "yolo_package": "模型/App 组合",
    "controls": "操作",
    "log": "运行日志",
    "serial": "设备序列号",
    "state": "状态",
    "refresh_devices": "刷新设备",
    "selected_device": "已选设备",
    "device_ip": "设备 IP",
    "rtsp_url": "RTSP 地址",
    "board_service": "板端推流服务",
    "start_board_stream": "启动板端推流",
    "stop_board_stream": "停止板端推流",
    "start_playback": "开始播放",
    "stop_playback": "停止播放",
    "copy_rtsp_url": "复制 RTSP 地址",
    "refresh_yolo_packages": "刷新组合包",
    "update_yolo_package": "更新到板端",
    "start_after_update": "更新后启动推流",
    "enable_ai_detection": "启用 AI 检测",
    "usb_sharing": "USB 网络共享",
    "detect_network_adapters": "检测网络适配器",
    "configure_usb_sharing": "自动配置 USB 共享",
    "open_manual_network_settings": "打开手动设置",
    "detect_usb0_ip": "检测 usb0 IP",
    "internet_adapter": "上网网卡",
    "usb_adapter": "板子 USB 网卡",
}

STATE_TEXT = {
    "unknown": "未知",
    "running": "运行中",
    "stopped": "已停止",
    "missing": "未找到",
    "starting": "启动中",
    "start failed": "启动失败",
    "ready": "就绪",
    "checking": "检查中",
    "found": "已找到",
    "not_found": "未找到",
}

DEVICE_STATE_TEXT = {
    "device": "已连接",
    "unauthorized": "未授权",
    "offline": "离线",
}


def state_text(key: str) -> str:
    return STATE_TEXT.get(key, key)


def device_state_text(key: str) -> str:
    return DEVICE_STATE_TEXT.get(key, key)
