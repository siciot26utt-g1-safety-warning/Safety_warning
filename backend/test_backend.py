"""Self-check backend: dedup QoS1 + telemetry + REST/WS. Chạy: python test_backend.py"""

import os
import pathlib
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.mkdtemp()
os.environ.update(  # phải đặt trước khi import main/database
    DATABASE_URL=f"sqlite:///{(pathlib.Path(_TMP) / 't.db').as_posix()}",
    SNAPSHOT_DIR=_TMP,
    MQTT_ENABLED="0",
)

import mqtt_service  # noqa: E402
from database import Device, SafetyEvent, SessionLocal, init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

init_db()

DEV = "EDGE_PI5_01"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert(**over):
    p = {
        "device_id": DEV,
        "timestamp": TS,
        "person_detected": True,
        "has_vest": False,
        "has_hardhat": True,
        "violation_type": "NO_VEST",
        "confidence": {"person": 0.95, "vest": 0.88, "hardhat": 0.92},
        "zone_name": "Khu_vuc_cau_thap_A",
    }
    p.update(over)
    return p


def test_alert_dedup_and_telemetry():
    db = SessionLocal()
    assert mqtt_service.handle_alert(db, _alert())["violation_type"] == "NO_VEST"
    assert mqtt_service.handle_alert(db, _alert()) is None  # QoS 1 gửi lại -> bỏ qua
    assert mqtt_service.handle_alert(db, _alert(violation_type="KHONG_HOP_LE")) is None

    mqtt_service.handle_telemetry(
        db, {"device_id": DEV, "status": "online", "cpu_temp_c": 52.4, "fps": 7.5, "timestamp": TS}
    )
    assert db.query(SafetyEvent).count() == 1
    assert db.get(Device, DEV).status == "online"
    db.close()


def test_api_flow():
    with TestClient(main.app) as c:
        body = c.get("/api/events").json()
        assert body["total"] == 1 and body["items"][0]["has_vest"] is False
        eid = body["items"][0]["id"]

        assert c.post(f"/api/events/{eid}/resolve", params={"action": "bogus"}).status_code == 400
        assert c.post("/api/events/99999/resolve", params={"action": "CONFIRMED"}).status_code == 404
        r = c.post(f"/api/events/{eid}/resolve", params={"action": "DISMISSED", "resolved_by": "HSE_01"}).json()
        assert (r["status"], r["resolved_by"]) == ("DISMISSED", "HSE_01")
        assert c.get("/api/events", params={"status": "NEW"}).json()["total"] == 0

        assert c.get("/api/devices").json()[0]["device_id"] == DEV
        stats = c.get("/api/stats/daily", params={"days": 7}).json()
        assert len(stats) == 7 and sum(d["total"] for d in stats) == 1
        assert stats[-1]["by_type"] == {"NO_VEST": 1}

        export = c.get("/api/events/export")
        assert "safety_report" in export.headers["content-disposition"] and "NO_VEST" in export.text
        assert c.get("/health").json()["status"] == "ok"
        with c.websocket_connect("/ws") as ws:
            ws.send_text("ping")
