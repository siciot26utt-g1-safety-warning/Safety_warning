#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect.py — Nhận diện PPE (người / mũ vàng / áo phản quang) từ camera.

Bản viết lại của src/main.py. Khác biệt chính:

  1. Đường dẫn model tính theo vị trí file  -> chạy được từ BẤT KỲ thư mục nào.
  2. Mỗi mũ/áo chỉ gán cho ĐÚNG MỘT người  -> bản cũ một cái mũ làm cả nhóm SAFE.
  3. Worker cũ tự hết hạn                   -> không còn "cướp" ID của người mới.
  4. MQTT publish khi ĐỔI TRẠNG THÁI        -> bản cũ gửi mỗi người mỗi frame (~90 msg/s).
  5. Topic + payload theo đúng PLAN.md      -> backend FastAPI subscribe được.
  6. Ba chế độ xem: cửa sổ / stream HTTP / không hiển thị.
  7. Nguồn vào: camera, file video hoặc ảnh -> vẫn dev được khi camera hỏng.

Ví dụ:
    python src/detect.py                            # camera 0, hiện cửa sổ (cần VNC)
    python src/detect.py --view stream              # xem tại http://<ip-pi>:8090/
    python src/detect.py --view none --mqtt         # chạy nền, đẩy MQTT
    python src/detect.py --source demo.mp4 --imgsz 320
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
from ultralytics import YOLO

from violation import ViolationTracker  # module sẵn có, logic debounce 5s đã tốt

ROOT = Path(__file__).resolve().parent.parent      # .../workspace/AI
DEFAULT_MODEL = ROOT / "models" / "best.pt"
SNAPSHOT_DIR = ROOT / "snapshots"

CLS_PERSON, CLS_HELMET, CLS_VEST = 0, 1, 2

# Vùng tìm mũ: 40% trên của box người. Vùng tìm áo: 20%-80% chiều cao.
HEAD_BAND = (0.00, 0.40)
BODY_BAND = (0.20, 0.80)

WORKER_TTL = 3.0        # giây: quá lâu không thấy thì xoá, tránh ghép nhầm người mới
MATCH_DIST = 120        # px: bán kính ghép lại khi ByteTrack mất ID

COLORS = {"SAFE": (0, 255, 0), "WARNING": (0, 165, 255), "VIOLATION": (0, 0, 255)}

START_TIME = time.time()


# ---------------------------------------------------------------- nguồn vào

def open_source(source: str, width: int, height: int):
    """Mở camera (số) hoặc file (đường dẫn).

    Ép MJPG vì webcam USB thường chỉ cho 640x480 với YUYV; muốn 720p
    bắt buộc phải chuyển sang MJPG.
    """
    if source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # luôn lấy frame mới nhất
    else:
        cap = cv2.VideoCapture(source)
    return cap


def frames_are_alive(cap, n: int = 15) -> bool:
    """Đọc thử vài frame. Toàn số 0 nghĩa là camera enumerate được nhưng
    không đẩy dữ liệu — lỗi cáp/phần cứng, không phải lỗi code."""
    for _ in range(n):
        ok, frame = cap.read()
        if ok and frame is not None and frame.max() > 0:
            return True
    return False


# ---------------------------------------------------------------- ghép PPE

def match_gear(persons, gear, band):
    """Ghép mỗi món đồ cho đúng một người, ưu tiên cặp khớp nhất.

    Trả về dict {chỉ_số_người: chỉ_số_đồ}. Bản cũ chỉ ``break`` nên một cái
    mũ có thể được tính cho nhiều người cùng lúc — đông người chen nhau là
    cả nhóm thành SAFE.
    """
    lo, hi = band
    pairs = []

    for pi, person in enumerate(persons):
        x1, y1, x2, y2 = person["bbox"]
        height = y2 - y1
        top, bottom = y1 + height * lo, y1 + height * hi
        person_cx = (x1 + x2) / 2

        for gi, (gx1, gy1, gx2, gy2) in enumerate(gear):
            cx, cy = (gx1 + gx2) / 2, (gy1 + gy2) / 2
            if x1 <= cx <= x2 and top <= cy <= bottom:
                # lệch tâm ngang càng ít thì càng chắc là của người này
                pairs.append((abs(cx - person_cx) / max(1, x2 - x1), pi, gi))

    pairs.sort()
    taken_person, taken_gear, result = set(), set(), {}
    for _, pi, gi in pairs:
        if pi in taken_person or gi in taken_gear:
            continue
        taken_person.add(pi)
        taken_gear.add(gi)
        result[pi] = gi
    return result


# ---------------------------------------------------------------- worker ID

class WorkerRegistry:
    """ByteTrack ID -> Worker # ổn định, có dọn rác theo thời gian.

    Bản cũ giữ ``worker_positions`` mãi mãi, nên vị trí của người đã rời
    khung hình vẫn hút được người mới đi ngang qua.
    """

    def __init__(self, ttl=WORKER_TTL, max_dist=MATCH_DIST):
        self.ttl = ttl
        self.max_dist = max_dist
        self._by_track: dict[int, int] = {}
        self._seen: dict[int, tuple[float, float, float]] = {}   # wid -> (cx, cy, t)
        self._next = 1

    def _purge(self, now):
        dead = [w for w, (_, _, t) in self._seen.items() if now - t > self.ttl]
        for wid in dead:
            self._seen.pop(wid, None)
            for tid, mapped in list(self._by_track.items()):
                if mapped == wid:
                    self._by_track.pop(tid, None)

    def resolve(self, track_id, bbox):
        now = time.time()
        self._purge(now)

        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        if track_id is not None:
            worker_id = self._by_track.get(int(track_id))
            if worker_id is None:
                worker_id = self._next
                self._next += 1
                self._by_track[int(track_id)] = worker_id
                print(f"[TRACK] Worker #{worker_id} (ByteTrack {track_id})")
            self._seen[worker_id] = (cx, cy, now)
            return worker_id

        # ByteTrack mất ID -> ghép lại theo khoảng cách, chỉ với worker còn sống
        best, best_dist = None, self.max_dist
        for worker_id, (ox, oy, seen_at) in self._seen.items():
            if now - seen_at > self.ttl:
                continue
            dist = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
            if dist < best_dist:
                best, best_dist = worker_id, dist

        if best is None:
            best = self._next
            self._next += 1
        self._seen[best] = (cx, cy, now)
        return best


# ---------------------------------------------------------------- MQTT

class Publisher:
    """Gửi alert khi đổi trạng thái + telemetry định kỳ, theo PLAN.md muc 2."""

    ALERT = "safety/edge/{dev}/alert"
    TELEMETRY = "safety/edge/{dev}/telemetry"

    def __init__(self, host, port, device_id, username=None, password=None):
        import paho.mqtt.client as mqtt

        self.device_id = device_id
        self.ok = False
        self._last_status: dict[int, str] = {}
        self._last_telemetry = 0.0

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password or "")
        try:
            self.client.connect(host, port, 60)
            self.client.loop_start()
            self.ok = True
            print(f"[MQTT] Da noi {host}:{port} (device_id={device_id})")
        except Exception as exc:
            print(f"[MQTT] Khong noi duoc broker: {exc} - chay tiep, khong gui tin")

    @staticmethod
    def _violation_type(helmet, vest):
        if helmet and not vest:
            return "NO_VEST"
        if vest and not helmet:
            return "NO_HARDHAT"
        if not helmet and not vest:
            return "NO_PPE"
        return None

    def alert(self, worker_id, status, helmet, vest, info, snapshot=None):
        """Chỉ publish khi status của worker này khác lần trước."""
        if not self.ok or self._last_status.get(worker_id) == status:
            return
        self._last_status[worker_id] = status

        payload = {
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "worker_id": worker_id,
            "has_hardhat": helmet,
            "has_vest": vest,
            "status": status,
            "violation_type": self._violation_type(helmet, vest),
            "violation_count": info["violation_count"],
            "violation_duration": round(info["violation_duration"], 1),
            "image_snapshot": snapshot,
        }
        self.client.publish(
            self.ALERT.format(dev=self.device_id), json.dumps(payload), qos=1)
        print(f"[MQTT] alert Worker #{worker_id} -> {status}")

    def telemetry(self, fps, workers, every=60.0):
        now = time.time()
        if not self.ok or now - self._last_telemetry < every:
            return
        self._last_telemetry = now
        payload = {
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "fps": round(fps, 1),
            "workers_in_frame": workers,
            "uptime_s": int(now - START_TIME),
        }
        self.client.publish(
            self.TELEMETRY.format(dev=self.device_id), json.dumps(payload), qos=1)

    def close(self):
        if self.ok:
            self.client.loop_stop()
            self.client.disconnect()


# ---------------------------------------------------------------- xem từ xa

class MjpegServer:
    """Phát frame đã vẽ qua HTTP để xem từ máy khác — không cần VNC."""

    PAGE = (b"<!doctype html><meta charset=utf-8><title>Smart Safety</title>"
            b"<style>body{margin:0;background:#111;display:grid;"
            b"place-items:center;height:100vh}img{max-width:100%;max-height:100vh}"
            b"</style><img src=/stream.mjpg>")

    def __init__(self, port=8090):
        self.port = port
        self._jpg = None
        self._lock = threading.Lock()

    def update(self, frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self._lock:
                self._jpg = buf.tobytes()

    def latest(self):
        with self._lock:
            return self._jpg

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(server.PAGE)))
                    self.end_headers()
                    self.wfile.write(server.PAGE)
                    return

                self.send_response(200)
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        jpg = server.latest()
                        if jpg is None:
                            time.sleep(0.05)
                            continue
                        self.wfile.write(b"--frame\r\n")
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(jpg)))
                        self.end_headers()
                        self.wfile.write(jpg + b"\r\n")
                        time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print(f"[VIEW] Mo http://<ip-pi>:{self.port}/ de xem")


# ---------------------------------------------------------------- vẽ overlay

def draw(frame, bbox, worker_id, helmet, vest, status, info):
    x1, y1, x2, y2 = bbox
    color = COLORS[status]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    lines = [
        f"Worker {worker_id}  [{status}]",
        f"Helmet {'YES' if helmet else 'NO'}   Vest {'YES' if vest else 'NO'}",
    ]
    if not info["safe"]:
        lines.append(f"{info['violation_duration']:.1f}s"
                     f"   vi pham: {info['violation_count']}")

    y = max(18, y1 - 8 - 18 * (len(lines) - 1))
    for text in lines:
        cv2.putText(frame, text, (x1, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        y += 18


# ---------------------------------------------------------------- main

def parse_args():
    p = argparse.ArgumentParser(description="Nhan dien PPE tu camera")
    p.add_argument("--source", default="0",
                   help="0 = camera, hoac duong dan video/anh")
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--conf", type=float, default=0.4)
    p.add_argument("--imgsz", type=int, default=640,
                   help="320 nhanh gap ~3 lan tren Pi 5")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--view", choices=["window", "stream", "none"], default="window")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--violation-seconds", type=float, default=5.0)
    p.add_argument("--mqtt", action="store_true", help="bat gui MQTT")
    p.add_argument("--broker", default="localhost")
    p.add_argument("--broker-port", type=int, default=1883)
    p.add_argument("--device-id", default="EDGE_PI5_01")
    p.add_argument("--mqtt-user", default=None)
    p.add_argument("--mqtt-pass", default=None)
    p.add_argument("--save-snapshots", action="store_true")
    p.add_argument("--max-reconnect", type=int, default=10,
                   help="so lan thu mo lai khi camera rot khoi bus USB")
    return p.parse_args()


def main():
    args = parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        sys.exit(f"Khong thay model: {model_path}")

    print(f"[AI] Nap model {model_path}")
    model = YOLO(str(model_path))
    print(f"[AI] Classes: {model.names}")

    cap = open_source(args.source, args.width, args.height)
    if not cap.isOpened():
        sys.exit(f"Khong mo duoc nguon '{args.source}'. "
                 "Kiem tra: fuser /dev/video0 (tien trinh khac dang giu camera?)")

    if args.source.isdigit() and not frames_are_alive(cap):
        cap.release()
        sys.exit(
            "Camera mo duoc nhung chi tra ve frame DEN (toan so 0).\n"
            "  Day la loi phan cung, khong phai loi code. Thu:\n"
            "    1. Doi sang cong USB 3.0 (mau xanh)\n"
            "    2. Doi day USB khac\n"
            "    3. Kiem chung: v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=5\n"
            "  Trong luc cho, van dev duoc: --source demo.mp4")

    tracker = ViolationTracker(violation_seconds=args.violation_seconds)
    registry = WorkerRegistry()
    pub = (Publisher(args.broker, args.broker_port, args.device_id,
                     args.mqtt_user, args.mqtt_pass) if args.mqtt else None)

    viewer = None
    if args.view == "stream":
        viewer = MjpegServer(args.port)
        viewer.start()

    if args.save_snapshots:
        SNAPSHOT_DIR.mkdir(exist_ok=True)

    print("[RUN] Bat dau - Ctrl+C de dung"
          + (", hoac Q trong cua so" if args.view == "window" else ""))

    fps, counted, t_fps = 0.0, 0, time.time()
    last_status: dict[int, str] = {}   # để chỉ hành động khi trạng thái ĐỔI

    is_camera = args.source.isdigit()
    reconnects = 0

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                if not is_camera:
                    print("[RUN] Het nguon vao")
                    break

                # Webcam USB kem/day loi hay rot giua chung:
                #   "usb usb3-port2: Cannot enable. Maybe the USB cable is bad?"
                # Mo lai thay vi chet ca phien demo.
                reconnects += 1
                if reconnects > args.max_reconnect:
                    print(f"[CAM] Mat camera {reconnects} lan - dung. "
                          "Doi day USB hoac doi sang cong USB 3.0.")
                    break
                print(f"[CAM] Mat frame, mo lai lan {reconnects}/"
                      f"{args.max_reconnect}...")
                cap.release()
                time.sleep(2.0)
                cap = open_source(args.source, args.width, args.height)
                continue

            reconnects = 0

            result = model.track(frame, persist=True, tracker="bytetrack.yaml",
                                 conf=args.conf, imgsz=args.imgsz,
                                 verbose=False)[0]

            persons, helmets, vests = [], [], []
            for box in (result.boxes if result.boxes is not None else []):
                cls = int(box.cls[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                if cls == CLS_PERSON:
                    tid = int(box.id[0]) if box.id is not None else None
                    persons.append({"bbox": (x1, y1, x2, y2), "track_id": tid})
                elif cls == CLS_HELMET:
                    helmets.append((x1, y1, x2, y2))
                elif cls == CLS_VEST:
                    vests.append((x1, y1, x2, y2))

            helmet_of = match_gear(persons, helmets, HEAD_BAND)
            vest_of = match_gear(persons, vests, BODY_BAND)

            for pi, person in enumerate(persons):
                worker_id = registry.resolve(person["track_id"], person["bbox"])
                has_helmet = pi in helmet_of
                has_vest = pi in vest_of

                info = tracker.update(worker_id, has_helmet, has_vest)
                status = ("VIOLATION" if info["violation_active"]
                          else "SAFE" if info["safe"] else "WARNING")

                # Chỉ chụp bằng chứng / bắn tin khi trạng thái thực sự đổi.
                # Nếu không, mỗi frame sẽ ghi một ảnh ~800 KB và đầy thẻ SD.
                changed = last_status.get(worker_id) != status
                last_status[worker_id] = status

                snapshot = None
                if changed and status == "VIOLATION" and args.save_snapshots:
                    snapshot = (f"snapshot_{args.device_id}_"
                                f"{datetime.now():%Y%m%d_%H%M%S}_w{worker_id}.jpg")
                    cv2.imwrite(str(SNAPSHOT_DIR / snapshot), frame)

                if pub and changed:
                    pub.alert(worker_id, status, has_helmet, has_vest,
                              info, snapshot)

                draw(frame, person["bbox"], worker_id,
                     has_helmet, has_vest, status, info)

            counted += 1
            if time.time() - t_fps >= 1.0:
                fps = counted / (time.time() - t_fps)
                counted, t_fps = 0, time.time()

            cv2.putText(frame, f"{fps:.1f} FPS | {len(persons)} nguoi",
                        (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            if pub:
                pub.telemetry(fps, len(persons))

            if args.view == "window":
                cv2.imshow("Smart Safety", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            elif viewer:
                viewer.update(frame)

    except KeyboardInterrupt:
        print("\n[RUN] Dung theo yeu cau")
    finally:
        cap.release()
        if args.view == "window":
            cv2.destroyAllWindows()
        if pub:
            pub.close()
        print("[RUN] Da don dep xong")


if __name__ == "__main__":
    main()
