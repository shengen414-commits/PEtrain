from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import folium
from flask import Flask, jsonify, send_file

from gpx_parser import TrackPoint
from playback_controller import PlaybackController


def generate_monitor_html(points: list[TrackPoint], output_path: str | Path) -> Path:
    if not points:
        raise ValueError("无法为零轨迹点生成地图")

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    route = [(point.lat, point.lon) for point in points]
    first = route[0]
    last = route[-1]

    monitor_map = folium.Map(location=first, zoom_start=16, control_scale=True, tiles="OpenStreetMap")
    folium.PolyLine(route, color="red", weight=4, opacity=0.85, tooltip="预定运动路线").add_to(monitor_map)
    folium.Marker(first, tooltip="起点", icon=folium.Icon(color="green", icon="play")).add_to(monitor_map)
    folium.Marker(last, tooltip="终点", icon=folium.Icon(color="red", icon="stop")).add_to(monitor_map)
    monitor_map.fit_bounds(route)

    map_name = monitor_map.get_name()
    monitor_map.get_root().script.add_child(folium.Element(_live_marker_script(map_name)))
    monitor_map.save(str(path))
    return path


def create_app(controller: PlaybackController, html_path: str | Path) -> Flask:
    app = Flask(__name__)
    resolved_html_path = Path(html_path).expanduser().resolve()

    @app.get("/")
    def index():
        return send_file(resolved_html_path)

    @app.get("/api/current_location")
    def current_location():
        return jsonify(controller.get_current_location())

    return app


def start_web_server(
    controller: PlaybackController,
    html_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 5000,
    open_browser: bool = True,
) -> threading.Thread:
    app = create_app(controller, html_path)
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True),
        name="FlaskMonitor",
        daemon=True,
    )
    thread.start()

    if open_browser:
        browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{browser_host}:{port}/")).start()

    return thread


def _live_marker_script(map_name: str) -> str:
    return f"""
(function () {{
  const mapName = "{map_name}";

  function boot(attempt) {{
    const map = window[mapName];
    if (!window.L || !map) {{
      if (attempt < 100) {{
        window.setTimeout(function () {{ boot(attempt + 1); }}, 100);
      }}
      return;
    }}

    let currentMarker = null;
    let currentTrail = null;
    const livePoints = [];

    const statusControl = L.control({{ position: "topright" }});
    statusControl.onAdd = function () {{
      const div = L.DomUtil.create("div", "live-status-panel");
      div.style.cssText = [
        "background:#ffffff",
        "border:1px solid #94a3b8",
        "border-radius:6px",
        "box-shadow:0 4px 14px rgba(15,23,42,.18)",
        "color:#0f172a",
        "font:13px/1.45 Arial,sans-serif",
        "min-width:170px",
        "padding:8px 10px"
      ].join(";");
      div.innerHTML = "Waiting for data";
      return div;
    }};
    statusControl.addTo(map);

    function formatNumber(value, digits) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) {{
        return "-";
      }}
      return Number(value).toFixed(digits);
    }}

    async function refreshCurrentLocation() {{
      try {{
        const response = await fetch("/api/current_location", {{ cache: "no-store" }});
        if (!response.ok) {{
          return;
        }}
        const data = await response.json();
        const latLng = [data.lat, data.lon];

        if (!currentMarker) {{
          currentMarker = L.circleMarker(latLng, {{
            radius: 8,
            color: "#0f172a",
            weight: 2,
            fillColor: "#38bdf8",
            fillOpacity: 0.95
          }}).addTo(map);
        }} else {{
          currentMarker.setLatLng(latLng);
        }}

        livePoints.push(latLng);
        if (!currentTrail) {{
          currentTrail = L.polyline(livePoints, {{
            color: "#2563eb",
            weight: 3,
            opacity: 0.9
          }}).addTo(map);
        }} else {{
          currentTrail.setLatLngs(livePoints);
        }}

        const panel = document.querySelector(".live-status-panel");
        if (panel) {{
          panel.innerHTML =
            "<b>Live position</b><br>" +
            "Index: " + data.index + " / " + Math.max(data.total - 1, 0) + "<br>" +
            "Speed: " + formatNumber(data.speed_kmh, 2) + " km/h<br>" +
            "Status: " + (data.is_playing ? "playing" : data.finished ? "finished" : "paused");
        }}

        currentMarker.bindPopup(
          "当前位置<br>" +
          "Index: " + data.index + " / " + Math.max(data.total - 1, 0) + "<br>" +
          "Speed: " + formatNumber(data.speed_kmh, 2) + " km/h<br>" +
          "Course: " + formatNumber(data.course_deg, 1) + "°"
        );
      }} catch (error) {{
        console.warn("location refresh failed", error);
      }}
    }}

    refreshCurrentLocation();
    window.setInterval(refreshCurrentLocation, 1000);
  }}

  window.setTimeout(function () {{ boot(0); }}, 0);
}})();
"""
