from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import suppress

from gpx_parser import TrackPoint
from nmea import build_nmea_sentences


class BluetoothRFCOMMServer:
    """Small RFCOMM server that accepts one Android client at a time."""

    def __init__(self, channel: int = 1, bind_address: str = "", backlog: int = 1) -> None:
        self.channel = channel
        self.bind_address = bind_address
        self.backlog = backlog
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._client_address: object | None = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.local_address: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._serve_forever, name="BluetoothRFCOMM", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._close_client_locked()
            if self._server_socket:
                with suppress(OSError):
                    self._server_socket.close()
                self._server_socket = None

    def send_point(self, point: TrackPoint) -> bool:
        return self.send_text(build_nmea_sentences(point))

    def send_text(self, payload: str) -> bool:
        data = payload.encode("ascii")
        with self._lock:
            client = self._client_socket

        if client is None:
            print("[bluetooth] 尚无手机连接，本次 NMEA 数据仅推进本地游标。")
            return False

        try:
            client.sendall(data)
            return True
        except OSError as exc:
            print(f"[bluetooth] 发送失败，关闭当前连接等待重连: {exc}")
            with self._lock:
                self._close_client_locked()
            return False

    def _serve_forever(self) -> None:
        try:
            server_socket = self._create_socket()
        except OSError as exc:
            print(f"[bluetooth] 无法创建 RFCOMM Socket: {exc}")
            print("[bluetooth] 可用 --no-bluetooth 只运行 Web 看板；Windows/Linux 蓝牙配置见 README。")
            return

        with self._lock:
            self._server_socket = server_socket

        next_wait_log = 0.0

        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                if now >= next_wait_log:
                    target = f"{self.local_address or '本机蓝牙'} channel {self.channel}"
                    print(f"[bluetooth] 等待 Android 手机连接 RFCOMM {target} ...")
                    next_wait_log = now + 30.0
                client_socket, client_address = server_socket.accept()
                client_socket.settimeout(3.0)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    print(f"[bluetooth] accept 失败: {exc}")
                    time.sleep(1)
                continue

            with self._lock:
                self._close_client_locked()
                self._client_socket = client_socket
                self._client_address = client_address
            print(f"[bluetooth] 手机已连接: {client_address}")

        with suppress(OSError):
            server_socket.close()

    def _create_socket(self) -> socket.socket:
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise OSError("当前 Python/系统没有 socket.AF_BLUETOOTH 支持")
        if not hasattr(socket, "BTPROTO_RFCOMM"):
            raise OSError("当前 Python/系统没有 socket.BTPROTO_RFCOMM 支持")

        address_candidates = self._address_candidates()
        channel_candidates = self._channel_candidates()

        last_error: OSError | None = None
        for address in address_candidates:
            for channel in channel_candidates:
                server_socket = socket.socket(
                    socket.AF_BLUETOOTH,
                    socket.SOCK_STREAM,
                    socket.BTPROTO_RFCOMM,
                )
                server_socket.settimeout(1.0)

                try:
                    server_socket.bind((address, channel))
                    server_socket.listen(self.backlog)
                    sockname = server_socket.getsockname()
                    self.local_address = sockname[0] if sockname else address
                    self.channel = sockname[1] if len(sockname) > 1 else channel

                    if channel != self.channel or channel != channel_candidates[0]:
                        print(f"[bluetooth] 已自动选择可用 RFCOMM channel {self.channel}。")
                    print(f"[bluetooth] 本机蓝牙地址: {self.local_address}, RFCOMM channel: {self.channel}")
                    return server_socket
                except OSError as exc:
                    last_error = exc
                    with suppress(OSError):
                        server_socket.close()

        raise last_error or OSError("无法绑定蓝牙 RFCOMM 地址")

    def _address_candidates(self) -> list[str]:
        if self.bind_address:
            return [self.bind_address]

        candidates: list[str] = []
        bdaddr_any = getattr(socket, "BDADDR_ANY", None)
        if bdaddr_any:
            candidates.append(bdaddr_any)
        candidates.append("00:00:00:00:00:00")

        # Windows rejects the empty string as a Bluetooth address; Linux usually
        # accepts BDADDR_ANY, but keeping "" as a final non-Windows fallback costs little.
        if sys.platform != "win32":
            candidates.append("")

        return list(dict.fromkeys(candidates))

    def _channel_candidates(self) -> list[int]:
        if self.channel <= 0:
            return list(range(3, 31))

        # Channel 1 is traditional SPP, but Windows commonly reserves or denies
        # low RFCOMM channels. Try the requested channel first, then scan usable
        # server channels so a command like "--rfcomm-channel 1" can still boot.
        fallback_channels = [channel for channel in range(3, 31) if channel != self.channel]
        return [self.channel, *fallback_channels]

    def _close_client_locked(self) -> None:
        if self._client_socket:
            with suppress(OSError):
                self._client_socket.close()
        self._client_socket = None
        self._client_address = None
