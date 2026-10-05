"""Kết nối DB + mô hình bảng (PLAN.md phần C)."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    location = Column(Text)
    ip_address = Column(Text)
    firmware_version = Column(Text)
    status = Column(Text, default="offline")
    last_ping = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ZoneConfig(Base):
    __tablename__ = "zones_config"

    zone_id = Column(Text, primary_key=True)
    device_id = Column(Text, ForeignKey("devices.device_id"))
    name = Column(Text, nullable=False)
    polygon_coords_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SafetyEvent(Base):
    __tablename__ = "safety_events"
    __table_args__ = (
        UniqueConstraint("device_id", "timestamp", "violation_type", name="uidx_event_dedup"),
        Index("idx_events_timestamp", "timestamp"),
        Index("idx_events_status", "status"),
        Index("idx_events_device_time", "device_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    device_id = Column(Text, ForeignKey("devices.device_id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    person_detected = Column(Boolean, default=True)
    has_vest = Column(Boolean, nullable=False)
    has_hardhat = Column(Boolean, nullable=False)
    violation_type = Column(Text, nullable=False)
    confidence = Column(Float)
    zone_name = Column(Text)
    image_url = Column(Text)
    status = Column(Text, default="NEW")
    resolved_by = Column(Text)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Telemetry(Base):
    __tablename__ = "telemetry"
    __table_args__ = (Index("idx_telemetry_time", "timestamp"),)

    id = Column(Integer, primary_key=True)
    device_id = Column(Text, ForeignKey("devices.device_id"))
    timestamp = Column(DateTime, nullable=False)
    cpu_temp_c = Column(Float)
    fps = Column(Float)
    status = Column(Text)


_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
