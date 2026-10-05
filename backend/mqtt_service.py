"""Cầu nối MQTT -> PostgreSQL -> WebSocket (PLAN.md bước 1.3 & 1.4)."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlalchemy.exc import IntegrityError

import config
from database import Device, SafetyEvent, SessionLocal, Telemetry
from ws import hub

log = logging.getLogger("mqtt")

ALERT_TOPIC = "safety/edge/+/alert"
TELEMETRY_TOPIC = "safety/edge/+/telemetry"

VALID_VIOLATIONS = {"NO_VEST", "NO_HARDHAT", "NO_PPE", "DANGER_ZONE"}


def _parse_ts(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _ping_device(db, device_id: str, status: str, ts: datetime) -> None:
    dev = db.get(Device, device_id)
    if dev is None:
        db.add(Device(device_id=device_id, name=device_id, status=status, last_ping=ts))
    else:
        dev.status, dev.last_ping = status, ts


def _save_snapshot(payload: dict) -> str | None:
    b64 = payload.get("image_base64")
    if b64:
        name = payload.get("image_snapshot") or f"snap_{payload['device_id']}_{int(datetime.now().timestamp())}.jpg"
        try:
            (config.SNAPSHOT_DIR / name).write_bytes(base64.b64decode(b64))
            return f"/snapshots/{name}"
        except (ValueError, OSError) as exc:
            log.warning("Bỏ qua snapshot lỗi: %s", exc)
    # ponytail: edge tự ghi file vào SNAPSHOT_DIR và gửi kèm tên -> chỉ cần kiểm tra tồn tại.
    # Lên Pi 5 thật thì đổi sang topic nhị phân riêng nếu ảnh lớn.
    name = payload.get("image_snapshot")
    if name and (config.SNAPSHOT_DIR / name).exists():
        return f"/snapshots/{name}"
    return None


def handle_alert(db, payload: dict) -> dict | None:
    device_id = str(payload.get("device_id") or "").strip()
    status = str(payload.get("status") or "VIOLATION").upper()
    if status in ("WARNING", "SAFE"):
        log.info("Bỏ qua alert trạng thái tạm thời '%s' cho thiết bị %s", status, device_id)
        return None

    vtype = str(payload.get("violation_type") or "").upper()
    if not device_id or vtype not in VALID_VIOLATIONS:
        log.warning("Bỏ qua alert không hợp lệ: %s", payload)
        return None

    ts = _parse_ts(payload.get("timestamp"))
    conf = payload.get("confidence") or {}
    event = SafetyEvent(
        device_id=device_id,
        timestamp=ts,
        person_detected=bool(payload.get("person_detected", True)),
        has_vest=bool(payload.get("has_vest", False)),
        has_hardhat=bool(payload.get("has_hardhat", False)),
        violation_type=vtype,
        confidence=float(conf.get("person") or 0) if isinstance(conf, dict) else None,
        zone_name=payload.get("zone_name"),
        image_url=_save_snapshot({**payload, "device_id": device_id}),
    )
    _ping_device(db, device_id, "online", ts)
    db.add(event)
    try:
        db.commit()
    except IntegrityError:  # MQTT QoS 1 gửi lại -> đã có bản ghi
        db.rollback()
        log.info("Bỏ qua alert trùng: %s %s", device_id, ts)
        return None
    return {
        "id": event.id,
        "device_id": device_id,
        "timestamp": ts.isoformat(),
        "violation_type": vtype,
        "has_vest": event.has_vest,
        "has_hardhat": event.has_hardhat,
        "zone_name": event.zone_name,
        "image_url": event.image_url,
        "status": "NEW",
    }


def handle_telemetry(db, payload: dict) -> None:
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        return
    ts = _parse_ts(payload.get("timestamp"))
    db.add(
        Telemetry(
            device_id=device_id,
            timestamp=ts,
            cpu_temp_c=payload.get("cpu_temp_c"),
            fps=payload.get("fps"),
            status=payload.get("status"),
        )
    )
    _ping_device(db, device_id, payload.get("status") or "online", ts)
    db.commit()
    hub.broadcast({"type": "telemetry", "device_id": device_id, "cpu_temp_c": payload.get("cpu_temp_c"), "fps": payload.get("fps")})


def _on_message(_client, _userdata, msg):
    try:
        payload = json.loads(msg.payload)
        if not isinstance(payload, dict):
            raise ValueError("payload không phải object")
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("JSON lỗi trên %s: %s", msg.topic, exc)
        return

    db = SessionLocal()
    try:
        if msg.topic.endswith("/alert"):
            event = handle_alert(db, payload)
            if event:
                log.info("[ALERT] %s %s vest=%s hardhat=%s", event["device_id"], event["violation_type"], event["has_vest"], event["has_hardhat"])
                hub.broadcast({"type": "alert", "event": event})
        else:
            handle_telemetry(db, payload)
    except Exception:  # một bản tin hỏng không được làm chết subscriber
        db.rollback()
        log.exception("Lỗi xử lý bản tin MQTT")
    finally:
        db.close()


def _on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code == 0:
        client.subscribe([(ALERT_TOPIC, 1), (TELEMETRY_TOPIC, 1)])
        log.info("Đã kết nối MQTT %s:%s", config.MQTT_HOST, config.MQTT_PORT)
    else:
        log.error("MQTT từ chối kết nối: %s", reason_code)


def start(loop: asyncio.AbstractEventLoop) -> mqtt.Client | None:
    """Chạy subscriber trong thread riêng; broadcast đẩy về event loop chính."""
    hub.bind(loop)
    if not config.MQTT_ENABLED:
        log.warning("MQTT_ENABLED=0 — chạy không có broker (chỉ dùng cho test)")
        return None
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
    client.on_connect, client.on_message = _on_connect, _on_message
    client.reconnect_delay_set(1, 30)  # QoS 1 + auto-reconnect khi mất Wi-Fi
    try:
        client.connect_async(config.MQTT_HOST, config.MQTT_PORT, 60)
        client.loop_start()
    except OSError as exc:
        log.error("Không kết nối được broker: %s", exc)
    return client
