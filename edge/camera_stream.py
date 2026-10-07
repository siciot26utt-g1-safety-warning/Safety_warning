#!/usr/bin/env python3
"""
Camera Stream Server cho Raspberry Pi 5 (MJPEG over HTTP).
"""

import argparse
import logging
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import cv2
    import numpy as np
except ImportError:
    print("[!] Loi: Chua cai OpenCV hoac Numpy. Chay: sudo apt install python3-opencv python3-numpy -y")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("CameraStream")


class CameraCapture:
    def __init__(self, camera_index=0, width=640, height=480, fps=25, show_osd=True):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.target_fps = fps
        self.show_osd = show_osd

        self.cap = None
        self.frame_bytes = None
        self.lock = threading.Lock()
        self.running = False
        self.current_fps = 0.0
        self.is_synthetic = False

    def _open_camera(self, idx):
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.target_fps)
                for _ in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        return cap
                    time.sleep(0.05)
                cap.release()
        except Exception as e:
            log.debug("Loi test index %d: %s", idx, e)
        return None

    def start(self):
        log.info("Dang kiem tra Camera index %s (%dx%d)...", self.camera_index, self.width, self.height)
        self.cap = self._open_camera(self.camera_index)

        # Tu dong quet index khac neu index chi dinh loi
        if not self.cap:
            log.warning("Khong doc duoc frame tu camera index %s. Dang quet index 0 -> 4...", self.camera_index)
            for test_idx in [0, 1, 2, 3, 4]:
                if test_idx == self.camera_index:
                    continue
                c = self._open_camera(test_idx)
                if c:
                    self.camera_index = test_idx
                    self.cap = c
                    log.info(">> TIM THAY CAMERA HOAT DONG TAI INDEX %d! Chuyen sang index %d.", test_idx, test_idx)
                    break

        if self.cap:
            log.info("Camera Capture (Index %d) khoi dong thanh cong.", self.camera_index)
            self.is_synthetic = False
        else:
            log.warning("==================================================================")
            log.warning("  [!] CHUA DOC DUOC HINH ANH TU CAMERA VAT LY!")
            log.warning("  Server se phat TEST PATTERN de Web Dashboard van ket noi duoc.")
            log.warning("==================================================================")
            self.is_synthetic = True

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True

    def _create_placeholder_frame(self):
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (20, 27, 45)
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for y in range(0, self.height, 40):
            cv2.line(frame, (0, y), (self.width, y), (28, 38, 60), 1)
        for x in range(0, self.width, 40):
            cv2.line(frame, (x, 0), (x, self.height), (28, 38, 60), 1)

        cv2.putText(frame, "RASPBERRY PI 5 - STREAM SERVER", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 245, 255), 2)
        cv2.putText(frame, "[!] CAMERA HARDWARE NOT READY", (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50, 100, 255), 2)
        cv2.putText(frame, "Ket noi mang: OK | Cong: 8080 (LIVE)", (30, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 230, 150), 1)
        cv2.putText(frame, f"Server Time: {time_str}", (30, 225), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 200, 230), 1)
        cv2.putText(frame, "Huong dan xu ly:", (30, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 80), 1)
        cv2.putText(frame, "- Neu dung USB: cam lai webcam hoac chay: python3 camera_stream.py --camera 1", (40, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 210, 225), 1)
        cv2.putText(frame, "- Dang tu dong thu lai camera moi 3 giay...", (40, 335), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 160, 180), 1)

        if self.show_osd:
            self._draw_overlay(frame, is_test=True)

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
        success, jpeg = cv2.imencode(".jpg", frame, encode_param)
        return jpeg.tobytes() if success else None

    def _capture_loop(self):
        fps_counter = 0
        fps_start = time.time()
        last_reconnect_attempt = time.time()
        fail_count = 0

        while self.running:
            frame = None

            if self.cap and not self.is_synthetic:
                ret, raw_frame = self.cap.read()
                if ret and raw_frame is not None:
                    fail_count = 0
                    frame = raw_frame
                else:
                    fail_count += 1
                    if fail_count > 30:
                        log.warning("Mất tín hiệu camera thật! Chuyển sang khung hình chờ...")
                        self.is_synthetic = True
                        if self.cap:
                            self.cap.release()
                            self.cap = None

            if self.is_synthetic:
                now = time.time()
                if now - last_reconnect_attempt >= 3.0:
                    last_reconnect_attempt = now
                    for idx in [self.camera_index, 0, 1, 2]:
                        c = self._open_camera(idx)
                        if c:
                            self.camera_index = idx
                            self.cap = c
                            self.is_synthetic = False
                            log.info(">> DA KET NOI LAI THANH CONG VOI CAMERA INDEX %d!", idx)
                            break

                jpeg_bytes = self._create_placeholder_frame()
                if jpeg_bytes:
                    with self.lock:
                        self.frame_bytes = jpeg_bytes
                time.sleep(1.0 / max(self.target_fps, 10))
                continue

            fps_counter += 1
            now = time.time()
            if now - fps_start >= 1.0:
                self.current_fps = fps_counter / (now - fps_start)
                fps_counter = 0
                fps_start = now

            if self.show_osd:
                self._draw_overlay(frame, is_test=False)

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
            success, jpeg = cv2.imencode(".jpg", frame, encode_param)
            if success:
                with self.lock:
                    self.frame_bytes = jpeg.tobytes()

            time.sleep(1.0 / max(self.target_fps, 10))

    def _draw_overlay(self, frame, is_test=False):
        h, w = frame.shape[:2]
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_label = "TEST PATTERN" if is_test else f"LIVE | FPS: {self.current_fps:.1f}"
        osd_text = f"Pi5-Gate-A | {time_str} | {status_label}"

        cv2.rectangle(frame, (0, 0), (w, 28), (15, 23, 42), -1)
        dot_color = (0, 140, 255) if is_test else (0, 230, 115)
        cv2.circle(frame, (16, 14), 5, dot_color, -1)
        cv2.putText(
            frame,
            osd_text,
            (28, 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (240, 245, 255),
            1,
            cv2.LINE_AA,
        )

    def get_frame(self):
        with self.lock:
            return self.frame_bytes

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
        log.info("Da dong Camera.")


camera_instance = None


class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/video_feed", "/stream"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            log.info("Client ket noi xem stream: %s", self.client_address[0])
            try:
                while True:
                    frame = camera_instance.get_frame() if camera_instance else None
                    if frame:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("utf-8"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                log.info("Client ngat ket noi stream: %s", self.client_address[0])

        elif self.path == "/snapshot":
            frame = camera_instance.get_frame() if camera_instance else None
            if frame:
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_error(503, "Camera chua san sang")

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "pi5-camera-stream"}')

        else:
            self.send_error(404, "Duong dan khong ton tai. Hay dung /video_feed")


def main():
    global camera_instance

    parser = argparse.ArgumentParser(description="Raspberry Pi 5 Camera Stream Server")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (mac dinh: 0)")
    parser.add_argument("--host", default="0.0.0.0", help="IP lang nghe (mac dinh: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Cong stream (mac dinh: 8080)")
    parser.add_argument("--width", type=int, default=640, help="Chieu rong (mac dinh: 640)")
    parser.add_argument("--height", type=int, default=480, help="Chieu cao (mac dinh: 480)")
    parser.add_argument("--fps", type=int, default=25, help="Target FPS (mac dinh: 25)")
    parser.add_argument("--no-osd", action="store_true", help="Tat overlay thoi gian/FPS")
    args = parser.parse_args()

    camera_instance = CameraCapture(
        camera_index=args.camera,
        width=args.width,
        height=args.height,
        fps=args.fps,
        show_osd=not args.no_osd,
    )

    camera_instance.start()

    server_address = (args.host, args.port)
    server = ThreadingHTTPServer(server_address, StreamHandler)

    log.info("==================================================================")
    log.info("  LUONG CAMERA STREAM PI 5 DA SAN SANG!")
    log.info("  URL xem truc tiep: http://%s:%d/video_feed", args.host, args.port)
    log.info("  Bấm Ctrl + C để dừng.")
    log.info("==================================================================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("\nDang dung server...")
    finally:
        server.server_close()
        camera_instance.stop()
        log.info("Hoan tat dung tien trinh.")


if __name__ == "__main__":
    main()
