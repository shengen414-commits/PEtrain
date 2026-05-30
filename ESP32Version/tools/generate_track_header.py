from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GPX = ROOT / "data" / "run.gpx"
OUTPUT = Path(__file__).resolve().parents[1] / "include" / "track_data.h"

NS = {"gpx": "http://www.topografix.com/GPX/1/1"}
EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1 = math.radians(a[0])
    lat2 = math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1 = math.radians(a[0])
    lat2 = math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def parse_points(path: Path) -> list[tuple[int, int, int, int, int]]:
    tree = ET.parse(path)
    points = []
    previous: tuple[float, float] | None = None
    previous_course = 0.0

    for trkpt in tree.findall(".//gpx:trkpt", NS):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_el = trkpt.find("gpx:ele", NS)
        elevation_m = float(ele_el.text) if ele_el is not None and ele_el.text else 0.0

        if previous is None:
            speed_cms = 0
            course_cd = 0
        else:
            distance = haversine_m(previous, (lat, lon))
            speed_cms = int(round(distance * 100.0))
            previous_course = bearing_deg(previous, (lat, lon)) if distance > 0.01 else previous_course
            course_cd = int(round(previous_course * 100.0))

        points.append(
            (
                int(round(lat * 10_000_000)),
                int(round(lon * 10_000_000)),
                int(round(elevation_m * 10.0)),
                speed_cms,
                course_cd,
            )
        )
        previous = (lat, lon)

    if not points:
        raise ValueError(f"No GPX track points found in {path}")

    return points


def write_header(points: list[tuple[int, int, int, int, int]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#pragma once",
        "",
        "#include <Arduino.h>",
        "",
        "struct TrackPoint {",
        "  int32_t latE7;",
        "  int32_t lonE7;",
        "  int16_t eleDm;",
        "  uint16_t speedCms;",
        "  uint16_t courseCdeg;",
        "};",
        "",
        f"constexpr uint16_t TRACK_POINT_COUNT = {len(points)};",
        "",
        "const TrackPoint TRACK_POINTS[] PROGMEM = {",
    ]

    for point in points:
        lines.append(f"  {{{point[0]}, {point[1]}, {point[2]}, {point[3]}, {point[4]}}},")

    lines.extend(["};", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    points = parse_points(DEFAULT_GPX)
    write_header(points, OUTPUT)
    print(f"Wrote {len(points)} points to {OUTPUT}")


if __name__ == "__main__":
    main()
