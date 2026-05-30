# ESP32 蓝牙 GPS 版本

这个目录是 PC 版本的 ESP32 移植版。ESP32 上电后会广播经典蓝牙 SPP 设备 `ESP32_GPX_GPS`，手机端 BluetoothGNSS / Bluetooth GPS Provider 连接它后即可接收 `$GPGGA` 和 `$GPRMC` NMEA 数据。

## 功能

- 轨迹点从 `../data/run.gpx` 生成到 `include/track_data.h`。
- 经纬度保持 WGS-84，不做 GCJ-02 转换。
- NMEA 使用正确异或校验和。
- 手机连接到 ESP32 蓝牙后，自动从起点开始以 1Hz 连续播放 GPX 轨迹。
- 轨迹播放完后保持最后一个点继续发送，方便手机 App 保持定位。

## 硬件要求

必须使用支持经典蓝牙 SPP 的 ESP32，例如 ESP32-WROOM-32 / ESP32-DevKitC。ESP32-S2、ESP32-S3、ESP32-C3、ESP32-C6 通常不支持经典蓝牙 SPP，不能直接跑这个版本。

## 编译烧录

推荐 PlatformIO:

```powershell
cd ESP32Version
python ..\ESP32Version\tools\generate_track_header.py
pio run -t upload
pio device monitor
```

也可以先只生成头文件:

```powershell
python ESP32Version\tools\generate_track_header.py
```

## 手机端使用

1. ESP32 上电，串口日志应显示 `Bluetooth SPP started as ESP32_GPX_GPS`。
2. 手机蓝牙搜索并配对 `ESP32_GPX_GPS`。
3. 在 BluetoothGNSS / Bluetooth GPS Provider 中选择 `ESP32_GPX_GPS` 并连接。
4. App 连接后 ESP32 会自动从起点开始发送轨迹 NMEA，不需要串口输入或按键操作。
5. 断开后再次连接，会重新从起点播放。

## 重新生成轨迹

把新的 GPX 放到上级目录 `data/run.gpx` 后运行:

```powershell
python ESP32Version\tools\generate_track_header.py
```

然后重新烧录固件。

## 说明

ESP32 固件不包含 PC 版的 Flask/Folium Web 看板。普通 ESP32 的职责是稳定广播蓝牙 SPP 和发送 NMEA；如果需要可视化，仍建议用 PC 版看板或另写 Wi-Fi Web 页面。
