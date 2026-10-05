#!/usr/bin/env python3
"""Test nhan dien KHONG can man hinh (chay duoc qua SSH).
Chup 1 frame tu webcam, cho YOLO nhan dien, luu ket qua ra detect.jpg.

Chay tu ~/workspace/AI (vi duong dan model la tuong doi):
    cd ~/workspace/AI && source myven/bin/activate && python test_detect.py
"""

import sys
import time

import cv2
from ultralytics import YOLO

MODEL_PATH = "models/best.pt"
OUT = "detect.jpg"
CONF = 0.4

print("[1/4] Load model:", MODEL_PATH)
model = YOLO(MODEL_PATH)
print("      classes =", model.names)

print("[2/4] Mo camera /dev/video0 ...")
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit("LOI: khong mo duoc camera. Kiem tra 'fuser /dev/video0' "
             "xem co tien trinh nao dang giu khong.")

# Camera nay chi cho 640x480 voi YUYV; phai doi sang MJPG moi len duoc 1280x720
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Bo vai frame dau cho camera can sang / lay net
for _ in range(10):
    cap.read()

ok, frame = cap.read()
cap.release()
if not ok:
    sys.exit("LOI: doc frame that bai.")
print("      frame =", frame.shape)

print("[3/4] Nhan dien (conf >= %.2f) ..." % CONF)
t0 = time.time()
result = model(frame, conf=CONF, verbose=False)[0]
dt = time.time() - t0

n = 0 if result.boxes is None else len(result.boxes)
print("      xong sau %.2fs -> %d box" % (dt, n))

if n == 0:
    print("      (khong thay gi - dua nguoi/mu/ao vao truoc camera roi chay lai)")
else:
    for box in result.boxes:
        name = model.names[int(box.cls[0])]
        conf = float(box.conf[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        print("      %-14s conf=%.2f  bbox=(%d,%d,%d,%d)"
              % (name, conf, x1, y1, x2, y2))

print("[4/4] Luu anh da ve ->", OUT)
cv2.imwrite(OUT, result.plot())
print("Xong. Uoc luong toc doc thuc te: ~%.1f fps o 640px" % (1.0 / dt if dt else 0))
