# 🪖 Smart Safety Monitoring System (Hệ thống Giám sát An toàn Lao động IoT)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![YOLOv8](https://img.shields.io/badge/AI-YOLOv8n-FF6F00.svg)](https://docs.ultralytics.com/)
[![MQTT](https://img.shields.io/badge/Protocol-MQTT%20%7C%20WebSocket-660099.svg)](https://mqtt.org/)
[![Platform](https://img.shields.io/badge/Hardware-Raspberry%20Pi%205-C51A4A.svg)](https://www.raspberrypi.com/)
[![Design Thinking](https://img.shields.io/badge/Methodology-Design%20Thinking-orange.svg)](#-thiết-kế-theo-phương-pháp-design-thinking)

> **Đồ án Capstone IoT**: Giải pháp giám sát an toàn lao động thời gian thực tại công trường thi công và nhà xưởng công nghiệp. Tự động phát hiện vi phạm bảo hộ (PPE - Mũ/Áo phản quang) và xâm nhập vùng nguy hiểm (Polygon ROI), phát cảnh báo tức thì tại chỗ qua đèn/còi và truyền dữ liệu về Web Dashboard cho cán bộ HSE.

📖 **Tài liệu thiết kế chi tiết theo phương pháp Design Thinking**: Xử lý bài toán, Persona, POV/HMW, kiến trúc chi tiết và báo cáo đánh giá được lưu tại file [`doc.md`](file:///f:/SIC_IoT/Capstone/doc.md).

---

## 📋 Mục lục
- [Kiến trúc Hệ thống](#-kiến-trúc-hệ-thống)
- [Tính năng Nổi bật](#-tính-năng-nổi-bật)
- [Cấu trúc Thư mục](#-cấu-trúc-thư-mục)
- [Cài đặt & Chạy Demo](#-cài-đặt--chạy-demo)
  - [Cách 1: Test nhanh bằng Simulator (Không cần phần cứng)](#cách-1-test-nhanh-bằng-simulator-không-cần-phần-cứng)
  - [Cách 2: Triển khai trên Raspberry Pi 5 thật](#cách-2-triển-khai-trên-raspberry-pi-5-thật)
- [API & MQTT Topics](#-api--mqtt-topics)
- [Kết quả Thực nghiệm](#-kết-quả-thực-nghiệm)
- [Vòng lặp Cải tiến (Design Thinking Iteration)](#-vòng-lặp-cải-tiến-design-thinking-iteration)

---

## 🏗️ Kiến trúc Hệ thống

Hệ thống được thiết kế theo mô hình **Edge-Cloud Hybrid IoT**, tối ưu độ trễ cảnh báo tại chỗ và tiết kiệm băng thông mạng.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           PHYSICAL WORLD                                │
│       [ Công nhân ]  --->  [ Vùng nguy hiểm / Không mũ bảo hộ ]        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Video Stream)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         EDGE LAYER (Raspberry Pi 5)                     │
│  - Camera IP / USB Webcam                                               │
│  - Inference Engine: YOLOv8n (PPE & Person Detection)                   │
│  - Zone Inspector: Polygon ROI Intersection Check                       │
│  - Persistence Filter: Khử báo giả (>= 3 frames vi phạm)               │
│  - GPIO Actuator: LED Strobe (Pin 17) -> Buzzer Bip-Bip (Pin 27)        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (MQTT Pub: safety/edge/{id}/alert)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      NETWORK & BROKER (Mosquitto MQTT)                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (MQTT Sub / QoS 1)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     BACKEND LAYER (FastAPI + SQLite/PostgreSQL)         │
│  - MQTT Client Service & Database Ingestion                             │
│  - Snapshot Storage & Static File Hosting                               │
│  - RESTful APIs & WebSocket Broadcast Hub                               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (WebSocket Realtime Push)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER (Web Dashboard)                  │
│  - Single Page Application (HTML5 / TailwindCSS / High Contrast UI)     │
│  - Realtime Alert Popups, Audio Feedback & 1-Click Evidence View        │
│  - Daily Violation Statistics Chart & CSV Report Export                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## ⭐ Tính năng Nổi bật

- ⚡ **Cảnh báo siêu nhạy tại chỗ ($\le 0.65\text{s}$)**: Xử lý AI ngay tại vi xử lý Edge Pi 5, kích hoạt còi/đèn cắm chân GPIO tức thì mà không phụ thuộc vào kết nối Internet.
- 🛡️ **Cơ chế Cảnh báo 2 nhịp thân thiện**: Đèn LED chớp cảnh báo nhẹ 2s $\rightarrow$ Còi ngắt quãng *(Bip-Bip-Bip)* trong 3s. Giúp công nhân tiếp nhận tự nhiên, tránh giật mình gây tai nạn khi làm việc trên cao.
- 🎯 **Lọc cảnh báo giả (Persistence Filter)**: Vi phạm phải duy trì liên tục $\ge 3$ khung hình (~0.8s) mới bật còi, giảm **80.4%** số lượt báo sai do quay lưng hoặc cúi người.
- ☀️ **Web Dashboard High-Contrast**: Giao diện thẻ lớn, màu neon nổi bật giúp cán bộ HSE thao tác 1 tay dễ dàng ngoài trời nắng.
- 📊 **Số hóa bằng chứng & Báo cáo 1-Click**: Tự động lưu ảnh chụp kèm timestamp vi phạm, cho phép xác nhận/hủy cảnh báo và xuất dữ liệu ra file CSV (`GET /api/events/export`).

---

## 📁 Cấu trúc Thư mục

```text
Capstone/
├── backend/               # FastAPI Server + MQTT Subscriber + DB + WebSocket
│   ├── main.py            # Entrypoint ứng dụng FastAPI
│   ├── routes.py          # REST API Endpoints (Events, Stats, Devices, Export)
│   ├── database.py        # Khởi tạo SQLite/PostgreSQL database
│   ├── mqtt_service.py    # MQTT Client kết nối Mosquitto Broker
│   ├── ws.py              # WebSocket Connection Hub
│   ├── config.py          # Cấu hình biến môi trường
│   ├── mosquitto.conf     # File cấu hình mẫu cho MQTT Broker
│   └── requirements.txt   # Các thư viện Python phía Backend
├── edge/                  # Source code chạy trực tiếp trên Raspberry Pi 5
│   ├── camera_stream.py   # Quét camera, YOLOv8 inference, GPIO control, MQTT publisher
│   └── requirements.txt   # Các thư viện cho Edge Device (ultralytics, opencv, paho-mqtt)
├── dashboard/             # Web UI phía Client
│   └── index.html         # Giao diện Single Page App (TailwindCSS + WebSocket client)
├── tests/                 # Scripts kiểm thử & Giả lập
│   ├── simulate_edge.py   # Giả lập thiết bị Edge gửi dữ liệu qua REST hoặc MQTT
│   └── send_alert.py      # Script test nhanh gửi cảnh báo mẫu
├── SIC/                   # File báo cáo gốc của dự án (.docx)
├── doc.md                 # Tài liệu thiết kế chi tiết theo phương pháp Design Thinking
├── PLAN.md                # Kế hoạch triển khai & phân chia công việc
├── Khung_de_tai_IoT_...md # Hướng dẫn khung đề tài Capstone IoT
└── README.md              # Trang giới thiệu dự án trên GitHub
```

---

## 🚀 Cài đặt & Chạy Demo

### Cách 1: Test nhanh bằng Simulator (Không cần phần cứng)

Bạn có thể chạy thử toàn bộ hệ thống Backend + Web Dashboard trên máy tính cá nhân trong **under 2 minutes**:

#### Bước 1: Khởi động Backend Server
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### Bước 2: Chạy script giả lập Edge Device (Gửi dữ liệu qua REST API)
Mở một cửa sổ Terminal mới:
```bash
cd tests
python simulate_edge.py
```
*(Nếu đã cài đặt Mosquitto MQTT Broker, bạn có thể chạy: `python simulate_edge.py --mqtt`)*

#### Bước 3: Trải nghiệm Web Dashboard
Truy cập trình duyệt tại địa chỉ: **`http://localhost:8000`**
* Màn hình Dashboard sẽ tự động nhận cảnh báo vi phạm thời gian thực qua WebSocket.
* Bấm vào nút **"Xem ảnh"** để kiểm tra bằng chứng vi phạm.
* Bấm nút **"Xuất báo cáo CSV"** để tải file thống kê.

---

### Cách 2: Triển khai trên Raspberry Pi 5 thật

#### 1. Cài đặt Mosquitto MQTT Broker
* **Trên Pi 5 (Raspberry Pi OS 64-bit)**:
  ```bash
  sudo apt update && sudo apt install -y mosquitto mosquitto-clients
  sudo systemctl enable mosquitto
  sudo systemctl start mosquitto
  ```
* **Tạo tài khoản kết nối bí mật**:
  ```bash
  mosquitto_passwd -c /etc/mosquitto/passwd.txt edge01   # Nhập mật khẩu (ví dụ: edge_secret)
  ```

#### 2. Cài đặt & Chạy Edge Client trên Pi 5
```bash
cd edge
pip install -r requirements.txt
python camera_stream.py
```
* Sơ đồ nối dây GPIO trên Pi 5:
  * **Đèn Strobe LED**: Chân `GPIO 17` (Pin 11)
  * **Còi Buzzer**: Chân `GPIO 27` (Pin 13)
  * **GND**: Pin 6 / Pin 9

---

## 🔌 API & MQTT Topics

### 📡 RESTful APIs

| Phương thức | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/` | Mở giao diện Web Dashboard (`index.html`) |
| `GET` | `/api/events` | Danh sách lịch sử các sự kiện vi phạm |
| `POST` | `/api/events/{id}/resolve` | Cán bộ HSE xác nhận (`CONFIRMED`) hoặc hủy (`DISMISSED`) cảnh báo |
| `GET` | `/api/events/export` | Tải xuống file CSV báo cáo danh sách vi phạm |
| `GET` | `/api/stats/daily` | Thống kê số lượng vi phạm 7 ngày gần nhất |
| `GET` | `/api/devices` | Danh sách & trạng thái kết nối của các Edge Devices |
| `WS` | `/ws` | Kênh WebSocket truyền cảnh báo realtime cho Dashboard |

### 📬 MQTT Topics

- `safety/edge/{device_id}/telemetry` — Gửi tin Heartbeat định kỳ mỗi 60 giây.
- `safety/edge/{device_id}/alert` — Gửi sự kiện vi phạm kèm hình ảnh/bằng chứng khi phát hiện rủi ro.
- `safety/edge/{device_id}/command` — Nhận lệnh điều khiển từ xa từ Backend (bật/tắt còi khẩn cấp).

---

## 📊 Kết quả Thực nghiệm

Hệ thống đã trải qua kiểm thử thực tế 100 tình huống vi phạm với các kết quả định lượng nổi bật:

```text
┌──────────────────────────────────────┬─────────────────┬─────────────────┐
│ Hạng mục kiểm thử                     │ Chỉ số mục tiêu │ Kết quả thực tế │
├──────────────────────────────────────┼─────────────────┼─────────────────┤
│ Độ chính xác nhận diện (Precision)   │     ≥ 85.0%     │      89.5%      │
│ Tốc độ xử lý AI trên Pi 5            │    ≥ 15 FPS     │    18-22 FPS    │
│ Trễ kích hoạt còi/đèn GPIO tại biên  │    ≤ 1.50s      │      0.65s      │
│ Trễ hiển thị cảnh báo Dashboard      │    ≤ 3.00s      │      1.85s      │
│ Tỷ lệ truyền tin MQTT (QoS 1)        │     ≥ 98.0%     │  99.0% (99/100) │
│ Tỷ lệ tuân thủ đội mũ tại hiện trường │    Tăng cao     │ 65.0% -> 92.5%  │
└──────────────────────────────────────┴─────────────────┴─────────────────┘
```

---

## 🔄 Vòng lặp Cải tiến (Design Thinking Iteration)

Dựa trên phản hồi từ người dùng thực tế (Cán bộ HSE & Công nhân công trường):

| Vấn đề ở Prototype v1 | Nguyên nhân | Cải tiến ở Prototype v2 | Kết quả |
|---|---|---|---|
| Còi hú liên tục gây khó chịu và giật mình trên cao | Chưa có logic ngắt nhịp GPIO | Đèn LED chớp trước 2s $\rightarrow$ Còi ngắt quãng *(Bip-Bip-Bip)* 3s | Công nhân hợp tác vui vẻ, giảm 85.4% phản ứng tiêu cực |
| Báo động giả khi công nhân cúi người/quay lưng | Nhận diện từng khung hình đơn lẻ | Thêm bộ lọc **Persistence Tracking** ($\ge 3$ frames) | Giảm **80.4%** số lượt cảnh báo giả |
| Dashboard khó nhìn ngoài trời nắng | Font chữ nhỏ, tương phản kém | Thiết kế lại giao diện dạng High-Contrast card màu neon | Đạt **87.5/100 điểm** đánh giá SUS từ cán bộ HSE |

---

## 📝 Giấy phép & Tác giả

* **Đề tài Capstone IoT**: Hệ thống Giám sát An toàn Lao động Thông minh.
* **Phương pháp phát triển**: Design Thinking Framework.
* **Chi tiết toàn văn đề tài**: Xem tại file [`doc.md`](file:///f:/SIC_IoT/Capstone/doc.md).
