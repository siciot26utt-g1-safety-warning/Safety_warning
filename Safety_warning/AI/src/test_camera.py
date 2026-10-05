import cv2
from ultralytics import YOLO

# Load model
model = YOLO("models/best.pt")

# Mở webcam
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Khong mo duoc webcam!")
    exit()

print("Webcam da mo.")
print("Nhan Q de thoat.")

while True:
    ret, frame = cap.read()

    if not ret:
        print("Khong doc duoc frame!")
        break

    # AI nhận diện
    results = model(frame, conf=0.4, verbose=False)

    # Vẽ bounding box + tên class
    annotated_frame = results[0].plot()

    # Hiển thị
    cv2.imshow("Smart Safety - YOLO", annotated_frame)

    # Nhấn Q để thoát
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()