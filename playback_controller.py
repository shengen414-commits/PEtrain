from __future__ import annotations

import threading
import time
from typing import Protocol

from gpx_parser import TrackPoint


class PointSender(Protocol):
    def send_point(self, point: TrackPoint) -> bool:
        ...


class PlaybackController:
    """Thread-safe cursor scheduler for manual bursts and continuous playback."""

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
        self._continuous_thread: threading.Thread | None = None
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

    def start_continuous_playback(self, *, wait_for_success: bool = True) -> None:
        """Start a 1Hz endless loop.

        When wait_for_success is true, the cursor does not advance until the
        sender reports at least one successful write. This matches Windows
        Bluetooth COM behavior: the COM handle can be open before the phone's
        SPP data channel is actually ready.
        """
        if self._continuous_thread and self._continuous_thread.is_alive():
            return
        self._continuous_thread = threading.Thread(
            target=self._run_continuous,
            kwargs={"wait_for_success": wait_for_success},
            name="NMEAContinuousPlayback",
            daemon=True,
        )
        self._continuous_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def trigger_burst(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_trigger_time < 0.5:
                return False
            self._last_trigger_time = now

            if self._is_playing:
                print("[playback] 正在播放数据段，忽略重复触发。")
                return False
            if self._next_index >= len(self.points):
                print("[playback] 游标已到末尾，重置回起点。")
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
                        print("[playback] 播放到底，自动回到起点继续。")
                        self._next_index = 0

                    point = self.points[self._next_index]
                    sent_index = self._next_index

                if self.sender:
                    sent = self.sender.send_point(point)
                    if not sent:
                        if self.pause_on_send_fail:
                            print("[playback] 发送失败，暂停本段播放；游标不前进。")
                            break
                        print("[playback] 蓝牙未送达，继续推进本地轨迹和看板。")

                with self._lock:
                    self._display_index = sent_index
                    self._next_index = sent_index + 1

                self._log_point(sent_index, point)
                self._sleep_until(start_monotonic + second + 1)
        finally:
            with self._lock:
                self._is_playing = False
            print("[playback] 数据段结束，等待下一次按 w。")

    def _run_continuous(self, *, wait_for_success: bool) -> None:
        print("[playback] 自动循环播放已启动，按 1Hz 连续发送 NMEA。")
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            with self._lock:
                if self._next_index >= len(self.points):
                    print("[playback] 轨迹已到结尾，自动回到起点循环。")
                    self._next_index = 0
                    self._display_index = 0

                point = self.points[self._next_index]
                sent_index = self._next_index
                self._is_playing = True

            sent = True
            if self.sender:
                sent = self.sender.send_point(point)

            if sent or not wait_for_success:
                with self._lock:
                    self._display_index = sent_index
                    self._next_index = sent_index + 1
                self._log_point(sent_index, point)
            else:
                with self._lock:
                    self._display_index = sent_index
                print("[playback] 等待手机蓝牙串口接收成功，当前游标暂不推进。")

            next_tick += 1.0
            sleep_seconds = next_tick - time.monotonic()
            if sleep_seconds <= 0:
                next_tick = time.monotonic()
                continue
            time.sleep(sleep_seconds)

        with self._lock:
            self._is_playing = False

    def _keyboard_loop(self) -> None:
        try:
            import keyboard
        except ImportError as exc:
            print(f"[keyboard] keyboard 库不可用: {exc}")
            return

        try:
            keyboard.on_press_key("w", lambda _event: self.trigger_burst(), suppress=False)
            print("[keyboard] 已监听按键 w：每次触发发送一段 NMEA 数据。")
            while not self._stop_event.is_set():
                time.sleep(0.2)
        except Exception as exc:
            print(f"[keyboard] 启动键盘监听失败: {exc}")
            print("[keyboard] Windows 可尝试管理员 PowerShell；Linux 通常需要 sudo。")
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

    def _log_point(self, index: int, point: TrackPoint) -> None:
        print(
            "[playback] "
            f"{index + 1}/{len(self.points)} "
            f"lat={point.lat:.7f}, lon={point.lon:.7f}, "
            f"speed={point.speed_mps * 3.6:.2f}km/h"
        )

    def _sleep_until(self, target_monotonic: float) -> None:
        sleep_seconds = target_monotonic - time.monotonic()
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
