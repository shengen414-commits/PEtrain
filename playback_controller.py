from __future__ import annotations

import threading
import time
from typing import Protocol

from gpx_parser import TrackPoint


class PointSender(Protocol):
    def send_point(self, point: TrackPoint) -> bool:
        ...


class PlaybackController:
    """Thread-safe cursor and 20-second burst scheduler."""

    def __init__(
        self,
        points: list[TrackPoint],
        sender: PointSender | None,
        burst_seconds: int = 20,
        pause_on_send_fail: bool = False,
        idle_heartbeat: bool = True,
    ) -> None:
        if not points:
            raise ValueError("轨迹点列表不能为空")

        self.points = points
        self.sender = sender
        self.burst_seconds = burst_seconds
        self.pause_on_send_fail = pause_on_send_fail
        self.idle_heartbeat = idle_heartbeat
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._is_playing = False
        self._next_index = 0
        self._display_index = 0
        self._last_trigger_time = 0.0
        self._keyboard_thread: threading.Thread | None = None
        self._burst_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None

    def start_keyboard_listener(self) -> None:
        if self._keyboard_thread and self._keyboard_thread.is_alive():
            return
        self._keyboard_thread = threading.Thread(target=self._keyboard_loop, name="KeyboardListener", daemon=True)
        self._keyboard_thread.start()

    def start_idle_heartbeat(self) -> None:
        if not self.idle_heartbeat or self.sender is None:
            return
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="NMEAHeartbeat", daemon=True)
        self._heartbeat_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def trigger_burst(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_trigger_time < 0.5:
                return False
            self._last_trigger_time = now

            if self._is_playing:
                print("[playback] 正在播放 20 秒数据段，忽略重复触发。")
                return False
            if self._next_index >= len(self.points):
                print("[playback] 游标已达末尾，触发无限循环，重置回起点。")
                self._next_index = 0
                self._display_index = 0

            self._is_playing = True

        self._burst_thread = threading.Thread(target=self._run_burst, name="NMEABurst", daemon=True)
        self._burst_thread.start()
        return True

    def get_current_location(self) -> dict[str, object]:
        with self._lock:
            index = min(self._display_index, len(self.points) - 1)
            point = self.points[index]
            next_index = self._next_index
            is_playing = self._is_playing

        return {
            "index": index,
            "next_index": next_index,
            "total": len(self.points),
            "lat": point.lat,
            "lon": point.lon,
            "elevation": point.elevation,
            "timestamp": point.timestamp.isoformat(),
            "speed_mps": point.speed_mps,
            "speed_kmh": point.speed_mps * 3.6,
            "course_deg": point.course_deg,
            "distance_from_start_m": point.distance_from_start_m,
            "is_playing": is_playing,
            "finished": next_index >= len(self.points),
        }

    def _run_burst(self) -> None:
        print(f"[playback] 开始发送 {self.burst_seconds} 秒数据流。")
        start_monotonic = time.monotonic()

        try:
            for second in range(self.burst_seconds):
                if self._stop_event.is_set():
                    break

                with self._lock:
                    if self._next_index >= len(self.points):
                        print("[playback] 播放到底，无缝衔接回起点。")
                        self._next_index = 0  # 核心修改：不 break，直接重置游标继续跑
                    
                    point = self.points[self._next_index]
                    sent_index = self._next_index

                if self.sender:
                    sent = self.sender.send_point(point)
                    if not sent:
                        if self.pause_on_send_fail:
                            print("[playback] 发送失败，暂停本段播放；游标不前进，连接恢复后可再次按 w。")
                            break
                        print("[playback] 蓝牙未送达，继续推进本地轨迹和看板。")

                with self._lock:
                    self._display_index = sent_index
                    self._next_index = sent_index + 1

                print(
                    "[playback] "
                    f"{sent_index + 1}/{len(self.points)} "
                    f"lat={point.lat:.7f}, lon={point.lon:.7f}, "
                    f"speed={point.speed_mps * 3.6:.2f}km/h"
                )

                next_tick = start_monotonic + second + 1
                sleep_seconds = next_tick - time.monotonic()
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        finally:
            with self._lock:
                self._is_playing = False
            print("[playback] 20 秒数据段结束，等待下一次按 w。")

    def _keyboard_loop(self) -> None:
        try:
            import keyboard
        except ImportError as exc:
            print(f"[keyboard] keyboard 库不可用: {exc}")
            return

        try:
            keyboard.on_press_key("w", lambda _event: self.trigger_burst(), suppress=False)
            print("[keyboard] 已监听按键 w：每次触发发送 20 秒 NMEA 数据。")
            while not self._stop_event.is_set():
                time.sleep(0.2)
        except Exception as exc:  # keyboard may need admin/root permissions.
            print(f"[keyboard] 启动键盘监听失败: {exc}")
            print("[keyboard] Windows 请尝试管理员 PowerShell；Linux 通常需要 sudo 运行。")
        finally:
            try:
                keyboard.unhook_all()
            except Exception:
                pass

    def _heartbeat_loop(self) -> None:
        print("[playback] 已启用暂停态 NMEA 心跳：未播放时每秒发送当前位置。")
        while not self._stop_event.is_set():
            with self._lock:
                is_playing = self._is_playing
                index = min(self._display_index, len(self.points) - 1)
                point = self.points[index]

            if not is_playing and self.sender:
                self.sender.send_point(point)

            time.sleep(1.0)
