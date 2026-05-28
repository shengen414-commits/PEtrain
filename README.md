### 🏃‍♂️ 蓝牙运动模拟与可视化系统 (Bluetooth GPX Simulator)
本项目是一个软硬结合的极客工具，旨在通过 PC 端代码解析真实的单次运动 GPX 轨迹，利用电脑蓝牙向 Android 手机底层注入高保真的 NMEA 0183 卫星报文。配合轻量级的本地 Web 可视化看板，实现运动轨迹的精确控制与沙盒级免 Root 环境模拟。(95%vibecoding得)

📝 开发者备注

免责声明：本项目仅供嵌入式蓝牙通信协议测试与地理数据分析学习使用。请勿用于违反第三方软件用户协议或破坏公平环境的违规操作。

最快安装方法打开当前文件夹后塞给诸如codex：根据这个readme和requirements.txt，安装一下需要的库,并告诉我电脑上和手机上要自己操作的部分，并根据README给出要注意的重点

分为两部分，windows端和手机端
##### windows端-蓝牙设置里开端口，脚本根据gpx发送模拟定位信息
    -配置 Windows 蓝牙入站端口，记住端口号
    -根据requirements.txt装用到的库
    -电脑端装好所有环境后运行python main.py data\run.gpx --serial-port COM6 --burst-seconds 600

##### 手机端-BluetoothGNSS接收，虚拟机内运行需要定位的软件，读取BluetoothGNSS软件传来的模拟定位
    -GooglePlay下载BluetoothGNSS、光速虚拟机
    -手机蓝牙连接电脑，已配对状态就可以
    -手机开开发者模式，模拟定位应用选BluetoothGNSS，此后打开这个软件，根据引导，最后右下角Settings-device选择电脑然后回到Connect连接上，显示出传来的数据即可
    -虚拟机内登陆需要定位的软件，开始使用即可

详见环境配置与安装


🎯 核心特性
真实运动学重现：支持读取导出的真实 .gpx 轨迹文件，保留真实的配速波动与自然转弯弧度。
将需要的轨迹.gpx导入到目前文件夹,命名为run.gpx即可

按键精准释放：通过监听键盘指令（默认 w 键），以 1Hz 频率连续释放设定时长（如 10 分钟）的连续数据段，支持无限循环闭环。

底层蓝牙穿透：通过 Windows 虚拟 SPP 串口或 Linux 原生 RFCOMM Socket，将 NMEA 数据直接注入安卓系统底层。

反作弊级沙盒降维：Android 沙盒/虚拟机环境，可洗白 Mock Location 标记，对抗高等级位置风控算法。

🏗️ 系统架构与数据流向
Plaintext
[本地 GPX 文件] 
      ↓ (解析与 1Hz 插值)
[Python 核心引擎] ← (触发指令) ← [键盘事件 (w键)]
      ↓ (NMEA 0183 报文封装)
[蓝牙 SPP/RFCOMM 发送端]
      ↓ (无线传输)
[Android 宿主机 - Bluetooth GPS Provider App] (接收并注入系统内核)
      ↓ (Mock Location 数据流)
[Android 沙盒机/虚拟机 (如 VMOS Pro)] (洗白 Mock 标记，接收真机物理传感器数据)
      ↓ (纯净 GPS + 真实加速度)
[目标应用 ]

### 💻 环境配置与安装
1. 软件依赖
本项目运行在 Python 3.10+ 环境下，主要依赖包如下：

Flask：用于驱动本地实时监控的大屏。

folium：用于生成交互式地图。

gpxpy：用于解析并处理 GPX 轨迹文件。

pyserial：用于 Windows 下的蓝牙串口通信。

keyboard：用于监听全局键盘按键。

2. 快速安装
在 Windows PowerShell 下：

PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

🚀 启动与使用指南
1. 准备轨迹文件
将你需要模拟的运动轨迹（.gpx 格式）放入项目的 data/ 目录中。强烈建议使用真实的运动记录文件，而非代码纯生成的完美轨迹。

2. 配置 Windows 蓝牙入站端口（关键）
如果你使用 Windows 系统，必须先让系统接管蓝牙 SDP 广播：

确保电脑蓝牙已与安卓手机完成配对。

进入 Windows 蓝牙和其他设备设置 -> 更多蓝牙设置 -> COM 端口。

点击 添加，选择 “传入(设备启动连接)”。

系统会自动生成一个端口号（如 COM6），记下它。

3. 运行 Python 引擎
打开管理员权限的终端，执行以下命令启动项目：

PowerShell

# 高级配置：指定 COM 端口，并设置按一次 w 键连发 600 秒（10分钟）
python main.py data\run.gpx --serial-port COM6 --burst-seconds 600
启动后，浏览器会自动打开 http://127.0.0.1:5000/ 显示 Web 预览看板。

4. 手机端接收与环境伪装
宿主机配置：下载并打开 BluetoothGNSS等桥接软件。在手机的“开发者选项”中将其设为“模拟位置信息应用”。在 App 内选择电脑蓝牙并点击 Start。

物理配合：将手机放置在摇步器上，制造持续的加速度计/陀螺仪数据。

沙盒洗白（对抗风控）：在宿主机上启动虚拟机 App（如 VMOS Pro/光速虚拟机）。在虚拟系统内赋予微信“位置”和“传感器”权限。不要在虚拟机内开启任何虚拟定位功能。

开始运动：在沙盒环境内的微信小程序中点击“开始”，并在电脑端按下 w 键触发模拟。

⚠️ 常见问题与风控排查
手机 App 接收不到定位：

检查 Windows 是否正确创建了“传入”COM 端口。

确保 Android App 中点击了 Start 进行主动连接。如果连接闪退，请尝试更换其他桥接 App，如 Bluetooth GNSS。

小程序显示真实位置或定位失败：

宿主机系统必须关闭“Wi-Fi 扫描”和“蓝牙扫描”。

虚拟机必须拥有“精确位置”权限。

