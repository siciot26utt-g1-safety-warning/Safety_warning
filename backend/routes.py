"""REST API cho Dashboard (PLAN.md bước 1.5)."""

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import config
from database import Device, SafetyEvent, Telemetry, get_db

router = APIRouter(prefix="/api")

_csv_header = ["id", "device_id", "timestamp", "violation_type", "has_vest", "has_hardhat", "zone_name", "status", "resolved_by", "resolved_at"]


def _event_dict(e: SafetyEvent) -> dict:
    return {
        "id": e.id,
        "device_id": e.device_id,
        "timestamp": e.timestamp.isoformat(),
        "person_detected": e.person_detected,
        "has_vest": e.has_vest,
        "has_hardhat": e.has_hardhat,
        "violation_type": e.violation_type,
        "confidence": e.confidence,
        "zone_name": e.zone_name,
        "image_url": e.image_url,
        "status": e.status,
        "resolved_by": e.resolved_by,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
    }


@router.get("/events")
def list_events(
    status: str | None = None,
    device_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(SafetyEvent).order_by(SafetyEvent.timestamp.desc())
    if status:
        stmt = stmt.where(SafetyEvent.status == status.upper())
    if device_id:
        stmt = stmt.where(SafetyEvent.device_id == device_id)
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "items": [_event_dict(e) for e in rows]}


@router.get("/events/export")
def export_events(days: int = Query(7, ge=1, le=365), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.scalars(select(SafetyEvent).where(SafetyEvent.timestamp >= since).order_by(SafetyEvent.timestamp.desc())).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_csv_header)
    for e in rows:
        writer.writerow([e.id, e.device_id, e.timestamp.isoformat(), e.violation_type, e.has_vest, e.has_hardhat, e.zone_name or "", e.status, e.resolved_by or "", e.resolved_at or ""])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        content="﻿" + buf.getvalue(),  # BOM để Excel mở đúng tiếng Việt
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="safety_report_{stamp}.csv"'},
    )


@router.post("/events/{event_id}/resolve")
def resolve_event(event_id: int, action: str, resolved_by: str = "HSE", db: Session = Depends(get_db)):
    action = action.upper()
    if action not in ("CONFIRMED", "DISMISSED"):
        raise HTTPException(400, "action phải là CONFIRMED hoặc DISMISSED")
    event = db.get(SafetyEvent, event_id)
    if event is None:
        raise HTTPException(404, "Không tìm thấy sự kiện")
    event.status = action
    event.resolved_by = resolved_by
    event.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return _event_dict(event)


@router.get("/stats/daily")
def stats_daily(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days - 1)
    day = func.date(SafetyEvent.timestamp)
    rows = db.execute(
        select(day, SafetyEvent.violation_type, func.count())
        .where(SafetyEvent.timestamp >= since.replace(hour=0, minute=0, second=0, microsecond=0))
        .group_by(day, SafetyEvent.violation_type)
    ).all()

    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    buckets = {(today - timedelta(days=i)).isoformat(): {} for i in range(days)}
    for d, vtype, count in rows:
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        if key in buckets:
            buckets[key][vtype] = count
    return [{"date": k, "total": sum(v.values()), "by_type": v} for k, v in sorted(buckets.items())]


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for dev in db.scalars(select(Device).order_by(Device.device_id)).all():
        stale = dev.last_ping is None or (now - dev.last_ping) > timedelta(seconds=config.DEVICE_OFFLINE_AFTER_S)
        last_temp = db.scalar(select(Telemetry.cpu_temp_c).where(Telemetry.device_id == dev.device_id).order_by(Telemetry.timestamp.desc()).limit(1))
        out.append(
            {
                "device_id": dev.device_id,
                "name": dev.name,
                "location": dev.location,
                "status": "offline" if stale else (dev.status or "online"),
                "last_ping": dev.last_ping.isoformat() if dev.last_ping else None,
                "cpu_temp_c": last_temp,
            }
        )
    return out


@router.get("/stream")
async def stream_proxy(url: str = Query("http://localhost:8080/video_feed", description="URL luồng MJPEG từ camera Pi 5")):
    """Proxy luồng video MJPEG từ Raspberry Pi 5 để tránh lỗi CORS hoặc truy cập tập trung qua Backend."""
    async def frame_generator():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception:
            return

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
