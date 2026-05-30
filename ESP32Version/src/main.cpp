#include <Arduino.h>
#include <BluetoothSerial.h>
#include <math.h>

#include "track_data.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled. Use a classic ESP32 board with Bluetooth enabled.
#endif

BluetoothSerial SerialBT;

constexpr char DEVICE_NAME[] = "ESP32_GPX_GPS";
constexpr uint32_t ONE_HZ_MS = 1000;
constexpr float KNOTS_PER_MPS = 1.94384449f;

uint16_t nextIndex = 0;
uint16_t displayIndex = 0;
bool previousClientState = false;
uint32_t lastTickMs = 0;
uint32_t nmeaSeconds = 0;

TrackPoint readTrackPoint(uint16_t index) {
  TrackPoint point;
  memcpy_P(&point, &TRACK_POINTS[index], sizeof(TrackPoint));
  return point;
}

String twoDigits(uint32_t value) {
  if (value < 10) {
    return "0" + String(value);
  }
  return String(value);
}

String utcTimeFromUptime(uint32_t seconds) {
  uint32_t daySeconds = seconds % 86400UL;
  uint32_t hours = daySeconds / 3600UL;
  uint32_t minutes = (daySeconds % 3600UL) / 60UL;
  uint32_t secs = daySeconds % 60UL;
  return twoDigits(hours) + twoDigits(minutes) + twoDigits(secs);
}

String utcDateFromUptime(uint32_t seconds) {
  uint32_t days = seconds / 86400UL;
  uint32_t day = (days % 28UL) + 1UL;
  return twoDigits(day) + "0126";
}

String decimalDegreesToNmea(int32_t valueE7, bool isLatitude, char &hemisphere) {
  double value = static_cast<double>(valueE7) / 10000000.0;

  if (isLatitude) {
    hemisphere = value >= 0 ? 'N' : 'S';
  } else {
    hemisphere = value >= 0 ? 'E' : 'W';
  }

  double absolute = fabs(value);
  int degrees = static_cast<int>(absolute);
  double minutes = (absolute - degrees) * 60.0;

  char buffer[18];
  if (isLatitude) {
    snprintf(buffer, sizeof(buffer), "%02d%07.4f", degrees, minutes);
  } else {
    snprintf(buffer, sizeof(buffer), "%03d%07.4f", degrees, minutes);
  }
  return String(buffer);
}

uint8_t nmeaChecksum(const String &body) {
  uint8_t checksum = 0;
  for (size_t index = 0; index < body.length(); index++) {
    checksum ^= static_cast<uint8_t>(body[index]);
  }
  return checksum;
}

String wrapNmea(const String &body) {
  char suffix[8];
  snprintf(suffix, sizeof(suffix), "*%02X\r\n", nmeaChecksum(body));
  return "$" + body + String(suffix);
}

String buildGga(const TrackPoint &point, const String &utcTime) {
  char latHemisphere;
  char lonHemisphere;
  String lat = decimalDegreesToNmea(point.latE7, true, latHemisphere);
  String lon = decimalDegreesToNmea(point.lonE7, false, lonHemisphere);
  float elevationM = static_cast<float>(point.eleDm) / 10.0f;

  String body = "GPGGA," + utcTime + "," + lat + "," + String(latHemisphere) + "," +
                lon + "," + String(lonHemisphere) + ",1,08,0.9," +
                String(elevationM, 1) + ",M,0.0,M,,";
  return wrapNmea(body);
}

String buildRmc(const TrackPoint &point, const String &utcTime, const String &utcDate) {
  char latHemisphere;
  char lonHemisphere;
  String lat = decimalDegreesToNmea(point.latE7, true, latHemisphere);
  String lon = decimalDegreesToNmea(point.lonE7, false, lonHemisphere);
  float speedKnots = (static_cast<float>(point.speedCms) / 100.0f) * KNOTS_PER_MPS;
  float courseDeg = static_cast<float>(point.courseCdeg) / 100.0f;

  String body = "GPRMC," + utcTime + ",A," + lat + "," + String(latHemisphere) + "," +
                lon + "," + String(lonHemisphere) + "," + String(speedKnots, 2) + "," +
                String(courseDeg, 1) + "," + utcDate + ",,,A";
  return wrapNmea(body);
}

bool sendPoint(uint16_t index) {
  TrackPoint point = readTrackPoint(index);
  String utcTime = utcTimeFromUptime(nmeaSeconds);
  String utcDate = utcDateFromUptime(nmeaSeconds);
  String payload = buildGga(point, utcTime) + buildRmc(point, utcTime, utcDate);

  SerialBT.print(payload);
  Serial.print(payload);
  return SerialBT.hasClient();
}

void resetTrack() {
  nextIndex = 0;
  displayIndex = 0;
  Serial.println("[playback] Reset to start.");
}

void tickOneHz() {
  bool hasClient = SerialBT.hasClient();

  if (hasClient && !previousClientState) {
    resetTrack();
    Serial.println("[bluetooth] Phone connected. Starting continuous GPX playback.");
  } else if (!hasClient && previousClientState) {
    Serial.println("[bluetooth] Phone disconnected. Waiting for next connection.");
  }
  previousClientState = hasClient;

  if (hasClient && nextIndex < TRACK_POINT_COUNT) {
    displayIndex = nextIndex;
    sendPoint(displayIndex);
    nextIndex++;
    Serial.printf("[playback] %u/%u\n", displayIndex + 1, TRACK_POINT_COUNT);
  } else if (hasClient) {
    sendPoint(displayIndex);
    Serial.println("[playback] Track finished. Holding last point.");
  } else {
    sendPoint(displayIndex);
  }

  nmeaSeconds++;
}

void setup() {
  Serial.begin(115200);

  Serial.println();
  Serial.println("ESP32 GPX Bluetooth GPS simulator");
  Serial.printf("Track points: %u\n", TRACK_POINT_COUNT);

  if (!SerialBT.begin(DEVICE_NAME)) {
    Serial.println("[bluetooth] Failed to start Bluetooth SPP.");
    while (true) {
      delay(1000);
    }
  }

  Serial.printf("[bluetooth] Bluetooth SPP started as %s\n", DEVICE_NAME);
  Serial.println("[control] Phone connection starts continuous 1Hz GPX playback automatically.");
}

void loop() {
  uint32_t now = millis();
  if (now - lastTickMs >= ONE_HZ_MS) {
    lastTickMs += ONE_HZ_MS;
    if (lastTickMs == 0 || now - lastTickMs >= ONE_HZ_MS) {
      lastTickMs = now;
    }
    tickOneHz();
  }
}
