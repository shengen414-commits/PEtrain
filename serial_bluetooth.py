from __future__ import annotations

import re
import threading
import time
from contextlib import suppress
from typing import Any

from gpx_parser import TrackPoint
from nmea import build_nmea_sentences


SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


class BluetoothSerialPort:
    """NMEA sender for Windows Bluetooth SPP virtual COM ports.

    Windows owns the Bluetooth SPP/SDP handshake. Python opens the virtual COM
    port handles and writes ASCII NMEA sentences. When several incoming ports
    exist, we keep them all open because Android may choose any identical SPP
    service record exposed by Windows.
    """

    def __init__(
        self,
        port: str = "auto",
        baudrate: int = 9600,
        reconnect_delay: float = 2.0,
        write_timeout: float = 0.2,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.reconnect_delay = reconnect_delay
        self.write_timeout = write_timeout
        self._serials: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_missing_log = 0.0
        self._last_status_log = 0.0
        self._last_write_error_log: dict[str, float] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._connect_loop, name="BluetoothSerialCOM", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._close_all_locked()

    def send_point(self, point: TrackPoint) -> bool:
        return self.send_text(build_nmea_sentences(point))

    def send_text(self, payload: str) -> bool:
        data = payload.encode("ascii")
        with self._lock:
            serials = list(self._serials.items())

        if not serials:
            now = time.monotonic()
            if now - self._last_missing_log > 5.0:
                print("[bluetooth-serial] 没有已打开的蓝牙 COM 口，NMEA 数据仅推进本地游标。")
                self._last_missing_log = now
            return False

        success_ports: list[str] = []

        for port_name, serial_port in serials:
            try:
                serial_port.write(data)
                serial_port.flush()
                success_ports.append(port_name)
            except Exception as exc:
                self._log_write_error(port_name, exc)

        if success_ports:
            print(f"[bluetooth-serial] NMEA 已写入: {', '.join(success_ports)}")
            return True
        return False

    def _connect_loop(self) -> None:
        while not self._stop_event.is_set():
            target_ports = self._resolve_target_ports()

            if not target_ports:
                print(
                    "[bluetooth-serial] 没找到 Windows 入站蓝牙 SPP COM 口。"
                    "请在“更多蓝牙设置 -> COM 端口”中新建“传入”端口。"
                )
                time.sleep(self.reconnect_delay)
                continue

            with self._lock:
                open_ports = set(self._serials)

            for port_name in target_ports:
                if self._stop_event.is_set():
                    break
                if port_name in open_ports:
                    continue
                self._open_port(port_name)

            self._log_status(force=False)
            time.sleep(self.reconnect_delay)

    def _open_port(self, port_name: str) -> None:
        try:
            import serial
        except ImportError as exc:
            print(f"[bluetooth-serial] pyserial 未安装: {exc}")
            print("[bluetooth-serial] 请运行: pip install pyserial")
            self._stop_event.set()
            return

        try:
            serial_port = serial.Serial(
                port_name,
                self.baudrate,
                timeout=0,
                write_timeout=self.write_timeout,
                rtscts=False,
                dsrdtr=False,
            )
        except serial.SerialException as exc:
            print(f"[bluetooth-serial] 打开 {port_name} 失败: {exc}")
            return

        with self._lock:
            self._serials[port_name] = serial_port
        print(
            f"[bluetooth-serial] {port_name} 已打开，波特率 {self.baudrate}。"
            "Android App 可选择电脑并点击 Start。"
        )

    def _resolve_target_ports(self) -> list[str]:
        explicit = self._parse_explicit_ports()
        if explicit:
            return explicit

        try:
            from serial.tools import list_ports
        except ImportError:
            return []

        incoming_ports: list[str] = []
        bluetooth_spp_ports: list[str] = []

        for info in list_ports.comports():
            hwid = (info.hwid or "").upper()
            description = (info.description or "").upper()
            is_spp = SPP_UUID in hwid or SPP_UUID.replace("-", "") in hwid
            is_bluetooth = "BTHENUM" in hwid or "BLUETOOTH" in description or "蓝牙" in (info.description or "")

            if not (is_spp or is_bluetooth):
                continue

            bluetooth_spp_ports.append(info.device)

            # Windows incoming Bluetooth COM ports normally look like:
            # BTHENUM\{SPP_UUID}_LOCALMFG&0000\...\000000000000_...
            # Outgoing ports point at a real remote MAC and often use LOCALMFG&0002.
            if "LOCALMFG&0000" in hwid and "000000000000" in hwid:
                incoming_ports.append(info.device)

        ports = incoming_ports or bluetooth_spp_ports
        return sorted(set(ports), key=_com_sort_key)

    def _parse_explicit_ports(self) -> list[str]:
        value = self.port.strip()
        if not value or value.lower() == "auto":
            return []
        ports: list[str] = []
        for part in re.split(r"[,;]", value):
            normalized = part.strip().upper()
            if not normalized:
                continue
            if normalized.isdigit():
                normalized = f"COM{normalized}"
            ports.append(normalized)
        return sorted(set(ports), key=_com_sort_key)

    def _log_status(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_status_log < 10.0:
            return
        self._last_status_log = now

        with self._lock:
            serials = list(self._serials.items())

        if not serials:
            return

        parts = []
        for port_name, serial_port in serials:
            with suppress(Exception):
                parts.append(
                    f"{port_name}(CTS={bool(serial_port.cts)},"
                    f"DSR={bool(serial_port.dsr)},CD={bool(serial_port.cd)})"
                )

        print(
            "[bluetooth-serial] 已打开端口: "
            + ", ".join(parts)
            + "。如果手机未收到数据，请在 Android App 中选电脑并点 Start。"
        )

    def _log_write_error(self, port_name: str, exc: Exception) -> None:
        now = time.monotonic()
        last_log = self._last_write_error_log.get(port_name, 0.0)
        if now - last_log < 5.0:
            return
        self._last_write_error_log[port_name] = now
        print(f"[bluetooth-serial] {port_name} 暂无接收端或写入失败: {exc}")

    def _close_one_locked(self, port_name: str) -> None:
        serial_port = self._serials.pop(port_name, None)
        if serial_port:
            with suppress(Exception):
                serial_port.close()

    def _close_all_locked(self) -> None:
        for port_name in list(self._serials):
            self._close_one_locked(port_name)


def _com_sort_key(port_name: str) -> tuple[int, str]:
    match = re.fullmatch(r"COM(\d+)", port_name.upper())
    if match:
        return int(match.group(1)), port_name
    return 9999, port_name
