from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from bluetooth_server import BluetoothRFCOMMServer
from gpx_parser import load_interpolated_track
from playback_controller import PlaybackController
from serial_bluetooth import BluetoothSerialPort
from web_server import generate_monitor_html, start_web_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于真实 GPX 轨迹的蓝牙运动模拟与可视化系统")
    parser.add_argument(
        "gpx",
        nargs="?",
        default="data/run.gpx",
        help="本地 GPX 文件路径；默认 data/run.gpx",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Flask 监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="Flask 端口，默认 5000")
    parser.add_argument(
        "--bluetooth-backend",
        choices=["serial", "rfcomm"],
        default="serial",
        help="蓝牙发送后端；Windows 默认 serial 虚拟串口",
    )
    parser.add_argument(
        "--serial-port",
        default="COM6,COM8",
        help="Windows 入站蓝牙虚拟串口，默认同时发送到 COM6,COM8；也可填 auto 或 COM6,8",
    )
    parser.add_argument("--serial-baudrate", type=int, default=9600, help="虚拟串口波特率，默认 9600")
    parser.add_argument("--rfcomm-channel", type=int, default=1, help="蓝牙 RFCOMM channel，默认 1")
    parser.add_argument("--bt-bind-address", default="", help="本机蓝牙地址，默认自动/任意地址")
    parser.add_argument(
        "--burst-seconds",
        type=int,
        default=600,
        help="手动按 w 模式下每次连续发送秒数，默认 600",
    )
    parser.add_argument(
        "--manual-trigger",
        action="store_true",
        help="恢复旧行为：启动后等待按 w，再发送一段数据",
    )
    parser.add_argument(
        "--pause-on-send-fail",
        action="store_true",
        help="手动按 w 模式下，蓝牙/串口发送失败时暂停本段播放且不推进游标",
    )
    parser.add_argument("--no-idle-heartbeat", action="store_true", help="手动模式暂停时不重复发送当前位置 NMEA")
    parser.add_argument("--generated-dir", default="generated", help="Folium HTML 输出目录")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--no-bluetooth", action="store_true", help="不启动蓝牙，仅运行轨迹看板和游标调度")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gpx_path = Path(args.gpx).expanduser().resolve()

    print(f"[main] 读取 GPX: {gpx_path}")
    raw_points, dense_points = load_interpolated_track(gpx_path)
    print(f"[main] 原始点数: {len(raw_points)}，1Hz 插值后点数: {len(dense_points)}")

    bluetooth_sender = None
    if not args.no_bluetooth:
        if args.bluetooth_backend == "serial":
            bluetooth_sender = BluetoothSerialPort(
                port=args.serial_port,
                baudrate=args.serial_baudrate,
            )
        else:
            bluetooth_sender = BluetoothRFCOMMServer(
                channel=args.rfcomm_channel,
                bind_address=args.bt_bind_address,
            )
        bluetooth_sender.start()
    else:
        print("[main] 已按 --no-bluetooth 跳过蓝牙服务。")

    controller = PlaybackController(
        points=dense_points,
        sender=bluetooth_sender,
        burst_seconds=args.burst_seconds,
        pause_on_send_fail=args.pause_on_send_fail,
        idle_heartbeat=not args.no_idle_heartbeat,
    )

    html_path = Path(args.generated_dir) / "index.html"
    resolved_html_path = generate_monitor_html(dense_points, html_path)
    start_web_server(
        controller=controller,
        html_path=resolved_html_path,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )

    if args.manual_trigger:
        controller.start_keyboard_listener()
        controller.start_idle_heartbeat()
        print(f"[main] Web 看板: http://{args.host}:{args.port}/")
        print("[main] 手动模式：按 w 发送一段 NMEA 数据；Ctrl+C 退出。")
    else:
        controller.start_continuous_playback(wait_for_success=bluetooth_sender is not None)
        print(f"[main] Web 看板: http://{args.host}:{args.port}/")
        print(
            "[main] 自动循环模式：手机蓝牙串口真正接收成功后开始推进轨迹，"
            "播到结尾会自动回到起点；Ctrl+C 退出。"
        )

    stop_requested = False

    def _request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        while not stop_requested:
            time.sleep(0.5)
    finally:
        print("[main] 正在退出...")
        controller.stop()
        if bluetooth_sender:
            bluetooth_sender.stop()


if __name__ == "__main__":
    main()
