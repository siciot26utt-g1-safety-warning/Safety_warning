import time
import json
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

# Thay bằng IP máy tính của bạn
BROKER_IP = "10.50.1.232"
PORT = 1883
DEVICE_ID = "EDGE_PI5_01"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
print(f"[*] Đang kết nối tới PC ({BROKER_IP}:{PORT})...")
client.connect(BROKER_IP, PORT, 60)
client.loop_start()

try:
    print("[*] Bắt đầu gửi cảnh báo từ Raspberry Pi...")
    # 1. Gửi nhịp tim Telemetry
    telemetry = {
        "device_id": DEVICE_ID,
        "status": "online",
        "cpu_temp_c": 51.5,
        "fps": 8.0,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    client.publish(f"safety/edge/{DEVICE_ID}/telemetry", json.dumps(telemetry), qos=1)

    # 2. Gửi cảnh báo vi phạm Alert
    alert = {
        "device_id": DEVICE_ID,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "person_detected": True,
        "has_vest": False,
        "has_hardhat": True,
        "violation_type": "NO_VEST",
        "confidence": {"person": 0.96, "vest": 0.90, "hardhat": 0.94},
        "zone_name": "Khu_vuc_cong_chinh",
    }
    client.publish(f"safety/edge/{DEVICE_ID}/alert", json.dumps(alert), qos=1)
    print("[OK] Đã gửi cảnh báo NO_VEST thành công!")
    time.sleep(2)

finally:
    client.loop_stop()
    client.disconnect()
