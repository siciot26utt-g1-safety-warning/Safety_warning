import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/safety_events",
)
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "edge01")
MQTT_PASS = os.getenv("MQTT_PASS", "edge_secret")
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "1") == "1"

BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = Path(os.getenv("SNAPSHOT_DIR", BASE_DIR / "snapshots"))
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
DASHBOARD_DIR = BASE_DIR.parent / "dashboard"
DEVICE_OFFLINE_AFTER_S = int(os.getenv("DEVICE_OFFLINE_AFTER_S", "120"))
