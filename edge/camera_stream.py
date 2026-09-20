#!/usr/bin/env python3
"""
Camera Stream Server cho Raspberry Pi 5 (MJPEG over HTTP).
Phát luồng video trực tiếp từ camera/webcam tại cổng 8080 để hiển thị trên Web Dashboard.

Cách chạy trên Pi 5:
    python3 camera_stream.py
    python3 camera_stream.py --camera 0 --port 8080 --width 640 --height 480
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
except ImportError:
    print("[!] Loi: Chua cai thu vien OpenCV. Hay chay lenh sau:")
    print("    pip install opencv-python")
    print("    hoac tren Pi 5: sudo apt install python3-opencv -y")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("CameraStream")


class CameraCapture:
    """Thread đọc camera liên tục trong nền để chống trễ khung hình."""

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

    def start(self):
        log.info("Đang mở Camera index %s (%dx%d)...", self.camera_index, self.width, self.height)
        
        # Mở camera (hỗ trợ cả camera USB v4l2 và Pi Camera qua v4l2)
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            log.error("Không thể mở Camera index %s!", self.camera_index)
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        log.info("Camera Capture Thread đã khởi động thành công.")
        return True

    def _capture_loop(self):
        fps_counter = 0
        fps_start = time.time()

        while self.running:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Tính FPS thực tế
            fps_counter += 1
            now = time.time()
            if now - fps_start >= 1.0:
                self.current_fps = fps_counter / (now - fps_start)
                fps_counter = 0
                fps_start = now

            # Vẽ thông tin giám sát lên hình ảnh (OSD Overlay)
            if self.show_osd:
                self._draw_overlay(frame)

            # Nén sang định dạng JPEG (chất lượng 75% để vừa nét vừa mượt qua Wi-Fi)
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
            success, jpeg = cv2.imencode(".jpg", frame, encode_param)
            if success:
                with self.lock:
                    self.frame_bytes = jpeg.tobytes()

            # Giới hạn tần số đọc theo target_fps
            time.sleep(1.0 / max(self.target_fps, 10))

    def _draw_overlay(self, frame):
        """Vẽ thông số thời gian, thiết bị, FPS lên góc khung hình."""
        h, w = frame.shape[:2]
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        osd_text = f"Pi5-Gate-A | {time_str} | FPS: {self.current_fps:.1f}"

        # Vẽ dải nền đen mờ phía trên để chữ luôn dễ đọc
        cv2.rectangle(frame, (0, 0), (w, 28), (15, 23, 42), -1)
        # Chấm xanh LIVE
        cv2.circle(frame, (16, 14), 5, (0, 230, 115), -1)
        # Chữ OSD
        cv2.putText(
            frame,
            f"LIVE  |  {osd_text}",
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
        log.info("Đã đóng Camera.")


# Biến toàn cục chứa instance camera
camera_instance = None


class StreamHandler(BaseHTTPRequestHandler):
    """Xử lý các request HTTP stream video chuẩn MJPEG."""

    def log_message(self, format, *args):
        # Tắt log in từng frame để không làm rối terminal
        pass

    def do_GET(self):
        # 1. Endpoint luồng stream video chính: /video_feed
        if self.path in ("/", "/video_feed", "/stream"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")  # Cho phép CORS từ Dashboard
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            log.info("Client kết nối xem stream: %s", self.client_address[0])
            try:
                while True:
                    frame = camera_instance.get_frame() if camera_instance else None
                    if frame:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("utf-8"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)  # ~25 FPS
            except (BrokenPipeError, ConnectionResetError):
                log.info("Client ngắt kết nối stream: %s", self.client_address[0])

        # 2. Endpoint chụp 1 ảnh tĩnh: /snapshot
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

        # 3. Endpoint kiểm tra sức khỏe: /health
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "pi5-camera-stream"}')

        else:
            self.send_error(404, "Duong dan khong ton tai. Hay dung /video_feed")


def main():
    global camera_instance

    parser = argparse.ArgumentParser(description="Raspberry Pi 5 Camera Stream Server")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (mac dinh: 0)")
    parser.add_argument("--host", default="0.0.0.0", help="Dia chi IP lang nghe (mac dinh: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Cong HTTP stream (mac dinh: 8080)")
    parser.add_argument("--width", type=int, default=640, help="Chieu rong khung hinh (mac dinh: 640)")
    parser.add_argument("--height", type=int, default=480, help="Chieu cao khung hinh (mac dinh: 480)")
    parser.add_argument("--fps", type=int, default=25, help="Target FPS (mac dinh: 25)")
    parser.add_argument("--no-osd", action="store_true", help="Tat overlay thoi gian/FPS tren hinh")
    args = parser.parse_args()

    # Khởi động camera capture
    camera_instance = CameraCapture(
        camera_index=args.camera,
        width=args.width,
        height=args.height,
        fps=args.fps,
        show_osd=not args.no_osd,
    )

    if not camera_instance.start():
        log.error("Khong the bat camera. Vui long kiem tra lai ket noi camera tren Pi 5!")
        return

    # Khởi động HTTP Threading Server
    server_address = (args.host, args.port)
    server = ThreadingHTTPServer(server_address, StreamHandler)

    log.info("==================================================================")
    log.info("  LUỒNG CAMERA STREAM PI 5 ĐÃ SẴN SÀNG!")
    log.info("  URL xem trực tiếp: http://%s:%d/video_feed", args.host, args.port)
    log.info("  Chụp ảnh tĩnh:     http://%s:%d/snapshot", args.host, args.port)
    log.info("  Bấm Ctrl + C để dừng.")
    log.info("==================================================================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("\nĐang dừng server...")
    finally:
        server.server_close()
        camera_instance.stop()
        log.info("Hoàn tất dừng tiến trình.")


if __name__ == "__main__":
    main()
