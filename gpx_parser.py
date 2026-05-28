from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import gpxpy


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class TrackPoint:
    lat: float
    lon: float
    elevation: float | None
    timestamp: datetime
    speed_mps: float = 0.0
    course_deg: float = 0.0
    distance_from_start_m: float = 0.0


def load_gpx_points(gpx_path: str | Path) -> list[TrackPoint]:
    """Read raw GPX track points in file order."""
    path = Path(gpx_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"GPX 文件不存在: {path}")

    with path.open("r", encoding="utf-8") as file:
        gpx = gpxpy.parse(file)

    raw_points: list[TrackPoint] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                raw_points.append(
                    TrackPoint(
                        lat=float(point.latitude),
                        lon=float(point.longitude),
                        elevation=float(point.elevation) if point.elevation is not None else None,
                        timestamp=_normalize_time(point.time),
                    )
                )

    # Some GPX files store a planned route instead of a recorded track.
    # Route points are accepted as a fallback so the system remains usable.
    if not raw_points:
        for route in gpx.routes:
            for point in route.points:
                raw_points.append(
                    TrackPoint(
                        lat=float(point.latitude),
                        lon=float(point.longitude),
                        elevation=float(point.elevation) if point.elevation is not None else None,
                        timestamp=_normalize_time(point.time),
                    )
                )

    if len(raw_points) < 2:
        raise ValueError("GPX 至少需要包含 2 个轨迹点或路线点")

    return raw_points


def load_interpolated_track(gpx_path: str | Path) -> tuple[list[TrackPoint], list[TrackPoint]]:
    """Return both raw points and the strict 1Hz interpolated track."""
    raw_points = load_gpx_points(gpx_path)
    return raw_points, interpolate_to_1hz(raw_points)


def interpolate_to_1hz(raw_points: Iterable[TrackPoint]) -> list[TrackPoint]:
    """Linearly resample a GPX track into a strict one-point-per-second stream."""
    points = list(raw_points)
    if len(points) < 2:
        return _compute_motion_metrics(points)

    if not _has_strictly_increasing_times(points):
        synthetic = _synthesize_1hz_times(points)
        return _compute_motion_metrics(synthetic)

    start_time = points[0].timestamp
    end_time = points[-1].timestamp
    total_seconds = int(math.floor((end_time - start_time).total_seconds()))

    if total_seconds <= 0:
        return _compute_motion_metrics([points[0], points[-1]])

    # 插值核心思路：
    # 1. 先建立一条严格的时间轴：start、start+1s、start+2s ... end。
    #    这样最终列表天然就是 1Hz，不会被原始 GPX 中 3 秒、5 秒甚至更长的采样间隔影响。
    # 2. 对时间轴上的每个目标时刻，找到它落在哪两个原始 GPX 点之间。
    # 3. 使用 ratio = 已经过的时间 / 两个原始点的总时间，对纬度、经度、高程做线性插值。
    #    这不是地图投影上的最短路径插值，而是运动模拟中足够稳定、成本极低的经纬度线性补点。
    # 4. 最后再统一计算相邻插值点之间的速度、航向和累计距离，避免在插值时混入速度误差。
    dense_points: list[TrackPoint] = []
    segment_index = 0

    for offset_seconds in range(total_seconds + 1):
        target_time = start_time + timedelta(seconds=offset_seconds)

        while (
            segment_index < len(points) - 2
            and points[segment_index + 1].timestamp < target_time
        ):
            segment_index += 1

        start = points[segment_index]
        end = points[segment_index + 1]
        segment_seconds = (end.timestamp - start.timestamp).total_seconds()

        if segment_seconds <= 0:
            ratio = 0.0
        else:
            ratio = (target_time - start.timestamp).total_seconds() / segment_seconds
            ratio = max(0.0, min(1.0, ratio))

        dense_points.append(
            TrackPoint(
                lat=_lerp(start.lat, end.lat, ratio),
                lon=_lerp(start.lon, end.lon, ratio),
                elevation=_lerp_optional(start.elevation, end.elevation, ratio),
                timestamp=target_time,
            )
        )

    return _compute_motion_metrics(dense_points)


def haversine_distance_m(a: TrackPoint, b: TrackPoint) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)

    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def initial_bearing_deg(a: TrackPoint, b: TrackPoint) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lon = math.radians(b.lon - a.lon)

    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _compute_motion_metrics(points: list[TrackPoint]) -> list[TrackPoint]:
    if not points:
        return []

    enriched: list[TrackPoint] = [
        TrackPoint(
            lat=points[0].lat,
            lon=points[0].lon,
            elevation=points[0].elevation,
            timestamp=points[0].timestamp,
            speed_mps=0.0,
            course_deg=0.0,
            distance_from_start_m=0.0,
        )
    ]

    total_distance = 0.0
    for index in range(1, len(points)):
        previous = enriched[-1]
        current = points[index]
        distance = haversine_distance_m(previous, current)
        elapsed = max((current.timestamp - previous.timestamp).total_seconds(), 1.0)
        total_distance += distance

        enriched.append(
            TrackPoint(
                lat=current.lat,
                lon=current.lon,
                elevation=current.elevation,
                timestamp=current.timestamp,
                speed_mps=distance / elapsed,
                course_deg=initial_bearing_deg(previous, current) if distance > 0.01 else previous.course_deg,
                distance_from_start_m=total_distance,
            )
        )

    return enriched


def _synthesize_1hz_times(points: list[TrackPoint]) -> list[TrackPoint]:
    base_time = points[0].timestamp or datetime.now(timezone.utc).replace(microsecond=0)
    return [
        TrackPoint(
            lat=point.lat,
            lon=point.lon,
            elevation=point.elevation,
            timestamp=base_time + timedelta(seconds=index),
        )
        for index, point in enumerate(points)
    ]


def _has_strictly_increasing_times(points: list[TrackPoint]) -> bool:
    return all(points[index].timestamp > points[index - 1].timestamp for index in range(1, len(points)))


def _normalize_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lerp(start: float, end: float, ratio: float) -> float:
    return start + (end - start) * ratio


def _lerp_optional(start: float | None, end: float | None, ratio: float) -> float | None:
    if start is None and end is None:
        return None
    if start is None:
        return end
    if end is None:
        return start
    return _lerp(start, end, ratio)
