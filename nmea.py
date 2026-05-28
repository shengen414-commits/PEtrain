from __future__ import annotations

from datetime import datetime, timezone

from gpx_parser import TrackPoint


KNOTS_PER_MPS = 1.9438444924406


def nmea_checksum(sentence_body: str) -> str:
    """Return the NMEA 0183 XOR checksum as two uppercase hex digits."""
    checksum = 0

    # NMEA 校验和只计算 "$" 和 "*" 中间的正文，不包含起始符、星号和 CRLF。
    # 算法是逐字符异或：第一个字符的 ASCII 值与第二个字符异或，再与第三个字符异或...
    # Android 端的蓝牙 GPS / Mock Location 工具通常会严格校验这个值，错 1 位就可能丢包。
    for char in sentence_body:
        checksum ^= ord(char)

    return f"{checksum:02X}"


def wrap_nmea(sentence_body: str) -> str:
    """Add '$', '*XX' checksum and CRLF terminator to a NMEA sentence body."""
    return f"${sentence_body}*{nmea_checksum(sentence_body)}\r\n"


def build_gga(point: TrackPoint, sentence_time: datetime | None = None) -> str:
    fix_time = sentence_time or datetime.now(timezone.utc)
    timestamp = _utc_time(fix_time)
    lat_value, lat_hemi = _decimal_degrees_to_nmea(point.lat, is_latitude=True)
    lon_value, lon_hemi = _decimal_degrees_to_nmea(point.lon, is_latitude=False)
    elevation = point.elevation if point.elevation is not None else 0.0

    # GGA: Global Positioning System Fix Data
    # 字段依次为：UTC 时间、纬度、南北半球、经度、东西半球、定位质量、卫星数、HDOP、
    # 海拔、海拔单位、大地水准面高度、单位、DGPS 年龄、DGPS 站点 ID。
    # 这里声明为普通 GPS fix（质量=1），并保持 GPX 原始 WGS-84 经纬度，不做 GCJ-02 转换。
    body = (
        f"GPGGA,{timestamp},{lat_value},{lat_hemi},{lon_value},{lon_hemi},"
        f"1,08,0.9,{elevation:.1f},M,0.0,M,,"
    )
    return wrap_nmea(body)


def build_rmc(point: TrackPoint, sentence_time: datetime | None = None) -> str:
    fix_time = sentence_time or datetime.now(timezone.utc)
    timestamp = _utc_time(fix_time)
    date_value = _utc_date(fix_time)
    lat_value, lat_hemi = _decimal_degrees_to_nmea(point.lat, is_latitude=True)
    lon_value, lon_hemi = _decimal_degrees_to_nmea(point.lon, is_latitude=False)
    speed_knots = point.speed_mps * KNOTS_PER_MPS

    # RMC: Recommended Minimum Navigation Information
    # Android 侧常用它读取速度和航向。速度单位必须是节（knots），不是 m/s 或 km/h。
    # mode indicator 使用 A，表示 Autonomous GNSS fix。
    body = (
        f"GPRMC,{timestamp},A,{lat_value},{lat_hemi},{lon_value},{lon_hemi},"
        f"{speed_knots:.2f},{point.course_deg:.1f},{date_value},,,A"
    )
    return wrap_nmea(body)


def build_nmea_sentences(point: TrackPoint) -> str:
    # 手机端收到的是“实时模拟定位”，因此 NMEA 的 UTC 时间使用当前系统时间。
    # GPX 原始时间仍保留在 Web API 中用于回放参考，但不直接写入 GGA/RMC，
    # 避免某些 GPS Provider 因日期过旧而判定定位无效。
    sentence_time = datetime.now(timezone.utc)
    return build_gga(point, sentence_time) + build_rmc(point, sentence_time)


def _decimal_degrees_to_nmea(value: float, *, is_latitude: bool) -> tuple[str, str]:
    # NMEA 不直接使用十进制度，而使用 ddmm.mmmm / dddmm.mmmm：
    #   纬度 31.2304167 -> 3113.8250,N
    #   经度 121.473701 -> 12128.4221,E
    # 度数部分纬度固定 2 位，经度固定 3 位；分钟部分保留 4 位小数即可满足手机端模拟定位。
    hemisphere = "N" if is_latitude and value >= 0 else "S" if is_latitude else "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0

    if is_latitude:
        return f"{degrees:02d}{minutes:07.4f}", hemisphere
    return f"{degrees:03d}{minutes:07.4f}", hemisphere


def _utc_time(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%H%M%S")


def _utc_date(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%d%m%y")
