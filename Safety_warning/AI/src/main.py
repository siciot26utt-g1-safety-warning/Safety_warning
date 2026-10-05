import cv2
import json
import time
import paho.mqtt.client as mqtt
from ultralytics import YOLO
from violation import ViolationTracker


# =========================================================
# CONFIG
# =========================================================

MODEL_PATH = "models/best.pt"

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

CAMERA_SOURCE = 0

CONFIDENCE = 0.4

VIOLATION_SECONDS = 5

# Khoảng cách tối đa để ghép người chưa có Track ID
MAX_MATCH_DISTANCE = 120


# =========================================================
# MQTT
# =========================================================

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2
)

try:
    mqtt_client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        60
    )

    mqtt_client.loop_start()

    print("[MQTT] Connected to broker")

except Exception as e:

    print("[MQTT] Connection failed:", e)


# =========================================================
# YOLO
# =========================================================

model = YOLO(MODEL_PATH)

print("[AI] Model loaded")
print("[AI] Classes:", model.names)


# =========================================================
# VIOLATION TRACKER
# =========================================================

violation_tracker = ViolationTracker(
    violation_seconds=VIOLATION_SECONDS
)


# =========================================================
# WORKER TRACKING
# =========================================================

# ByteTrack ID -> Worker ID
track_to_worker = {}

# Worker ID -> thông tin vị trí gần nhất
worker_positions = {}

# Worker ID tiếp theo
next_worker_id = 1


def center_of_bbox(bbox):
    """
    Lấy tâm bounding box.
    """

    x1, y1, x2, y2 = bbox

    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    return cx, cy


def distance_between(p1, p2):
    """
    Khoảng cách giữa 2 điểm.
    """

    x1, y1 = p1
    x2, y2 = p2

    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def get_worker_id(track_id, bbox):
    """
    Lấy Worker ID.

    Ưu tiên ByteTrack ID.
    Nếu chưa có Track ID thì tìm Worker gần nhất.
    Nếu không tìm được thì tạo Worker mới.
    """

    global next_worker_id

    # -----------------------------------------------------
    # CASE 1: ByteTrack đã có ID
    # -----------------------------------------------------

    if track_id is not None:

        track_id = int(track_id)

        if track_id in track_to_worker:

            worker_id = track_to_worker[track_id]

        else:

            # Tạo Worker ID mới
            worker_id = next_worker_id

            next_worker_id += 1

            track_to_worker[track_id] = worker_id

            print(
                f"[TRACK] New Worker #{worker_id} "
                f"(Track ID: {track_id})"
            )

        worker_positions[worker_id] = center_of_bbox(bbox)

        return worker_id


    # -----------------------------------------------------
    # CASE 2: Không có ByteTrack ID
    # -----------------------------------------------------

    current_center = center_of_bbox(bbox)

    best_worker = None
    best_distance = MAX_MATCH_DISTANCE

    for worker_id, old_center in worker_positions.items():

        distance = distance_between(
            current_center,
            old_center
        )

        if distance < best_distance:

            best_distance = distance
            best_worker = worker_id


    if best_worker is not None:

        worker_positions[best_worker] = current_center

        print(
            f"[TRACK] Recovered Worker #{best_worker}"
        )

        return best_worker


    # -----------------------------------------------------
    # CASE 3: Người hoàn toàn mới
    # -----------------------------------------------------

    worker_id = next_worker_id

    next_worker_id += 1

    worker_positions[worker_id] = current_center

    print(
        f"[TRACK] New Worker #{worker_id} "
        f"(fallback)"
    )

    return worker_id


# =========================================================
# CAMERA
# =========================================================

cap = cv2.VideoCapture(CAMERA_SOURCE)

if not cap.isOpened():

    print("[ERROR] Cannot open camera")

    exit()


print("[CAMERA] Camera started")


# =========================================================
# MAIN LOOP
# =========================================================

while True:

    ret, frame = cap.read()

    if not ret:

        print("[ERROR] Cannot read frame")

        break


    # =====================================================
    # YOLO TRACKING
    # =====================================================

    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=CONFIDENCE,
        verbose=False
    )

    result = results[0]


    persons = []
    helmets = []
    vests = []


    # =====================================================
    # GET DETECTIONS
    # =====================================================

    if result.boxes is not None:

        for box in result.boxes:

            cls = int(box.cls[0])

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0].tolist()
            )


            # -------------------------------------------------
            # PERSON
            # -------------------------------------------------

            if cls == 0:

                track_id = None

                if box.id is not None:

                    track_id = int(box.id[0])


                # Debug
                print(
                    f"[PERSON] "
                    f"bbox=({x1},{y1},{x2},{y2}) "
                    f"TrackID={track_id}"
                )


                worker_id = get_worker_id(
                    track_id,
                    (x1, y1, x2, y2)
                )


                persons.append({
                    "id": worker_id,
                    "track_id": track_id,
                    "bbox": (x1, y1, x2, y2)
                })


            # -------------------------------------------------
            # YELLOW HELMET
            # -------------------------------------------------

            elif cls == 1:

                helmets.append(
                    (x1, y1, x2, y2)
                )


            # -------------------------------------------------
            # YELLOW VEST
            # -------------------------------------------------

            elif cls == 2:

                vests.append(
                    (x1, y1, x2, y2)
                )


    # =====================================================
    # ANALYZE EACH WORKER
    # =====================================================

    for person in persons:

        worker_id = person["id"]

        px1, py1, px2, py2 = person["bbox"]

        person_width = px2 - px1

        person_height = py2 - py1


        helmet_found = False
        vest_found = False


        # =================================================
        # HELMET
        # =================================================

        for hx1, hy1, hx2, hy2 in helmets:

            hx = (hx1 + hx2) / 2
            hy = (hy1 + hy2) / 2


            if (
                px1 <= hx <= px2
                and
                py1 <= hy <= py1 + person_height * 0.4
            ):

                helmet_found = True

                break


        # =================================================
        # VEST
        # =================================================

        for vx1, vy1, vx2, vy2 in vests:

            vx = (vx1 + vx2) / 2
            vy = (vy1 + vy2) / 2


            if (
                px1 <= vx <= px2
                and
                py1 + person_height * 0.2
                <= vy
                <= py1 + person_height * 0.8
            ):

                vest_found = True

                break


        # =================================================
        # VIOLATION
        # =================================================

        violation = violation_tracker.update(
            worker_id,
            helmet_found,
            vest_found
        )


        safe = violation["safe"]

        violation_active = violation[
            "violation_active"
        ]

        violation_count = violation[
            "violation_count"
        ]

        violation_duration = violation[
            "violation_duration"
        ]


        # =================================================
        # MQTT
        # =================================================

        mqtt_data = {

            "worker_id": worker_id,

            "helmet": helmet_found,

            "vest": vest_found,

            "safe": safe,

            "violation": violation_active,

            "violation_count": violation_count,

            "violation_duration": round(
                violation_duration,
                1
            ),

            "timestamp": time.time()
        }


        topic = (
            f"smart-safety/worker/{worker_id}"
        )


        mqtt_client.publish(
            topic,
            json.dumps(mqtt_data)
        )


        # =================================================
        # STATUS
        # =================================================

        if violation_active:

            status = "VIOLATION"

        elif not safe:

            status = "WARNING"

        else:

            status = "SAFE"


        # OpenCV color: BGR

        if violation_active:

            color = (0, 0, 255)

        elif not safe:

            color = (0, 165, 255)

        else:

            color = (0, 255, 0)


        # =================================================
        # DRAW PERSON
        # =================================================

        cv2.rectangle(
            frame,
            (px1, py1),
            (px2, py2),
            color,
            2
        )


        # =================================================
        # WORKER ID
        # =================================================

        cv2.putText(
            frame,
            f"Worker {worker_id}",
            (px1, max(25, py1 - 60)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2
        )


        # =================================================
        # HELMET
        # =================================================

        cv2.putText(
            frame,
            f"Helmet: {'YES' if helmet_found else 'NO'}",
            (px1, max(45, py1 - 40)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2
        )


        # =================================================
        # VEST
        # =================================================

        cv2.putText(
            frame,
            f"Vest: {'YES' if vest_found else 'NO'}",
            (px1, max(65, py1 - 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2
        )


        # =================================================
        # STATUS
        # =================================================

        cv2.putText(
            frame,
            status,
            (px1, py2 + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2
        )


        # =================================================
        # VIOLATION TIME
        # =================================================

        if not safe:

            cv2.putText(
                frame,
                f"Violation: {violation_duration:.1f}s",
                (px1, py2 + 45),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )


        # =================================================
        # VIOLATION COUNT
        # =================================================

        cv2.putText(
            frame,
            f"Violations: {violation_count}",
            (px1, py2 + 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2
        )


    # =====================================================
    # SHOW CAMERA
    # =====================================================

    cv2.imshow(
        "Smart Safety - YOLO + MQTT",
        frame
    )


    # =====================================================
    # QUIT
    # =====================================================

    if cv2.waitKey(1) & 0xFF == ord("q"):

        break


# =========================================================
# CLEANUP
# =========================================================

cap.release()

cv2.destroyAllWindows()

mqtt_client.loop_stop()

mqtt_client.disconnect()

print("[SYSTEM] Stopped")