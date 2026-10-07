import cv2
import time
import numpy as np
import onnxruntime as ort
from collections import deque


# =========================================================
# CONFIG
# =========================================================

MODEL_PATH = "/home/iot03/Pi5/AI/models/best.onnx"

PERSON_CLASS = 0
HELMET_CLASS = 1
VEST_CLASS = 2

PERSON_CONF = 0.25
HELMET_CONF = 0.25
VEST_CONF = 0.15

IMGSZ = 640

PERSON_MARGIN = 0.10
MIN_VEST_OVERLAP = 0.50

VEST_HISTORY_SIZE = 10
VEST_OK_MIN_FRAMES = 6

vest_history = deque(maxlen=VEST_HISTORY_SIZE)


# =========================================================
# BOX HELPERS
# =========================================================

def expand_box(box, margin=0.10):
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1

    return (
        x1 - w * margin,
        y1 - h * margin,
        x2 + w * margin,
        y2 + h * margin
    )


def box_center(box):
    x1, y1, x2, y2 = box

    return (
        (x1 + x2) / 2,
        (y1 + y2) / 2
    )


def overlap_ratio(person_box, vest_box):
    px1, py1, px2, py2 = person_box
    vx1, vy1, vx2, vy2 = vest_box

    ix1 = max(px1, vx1)
    iy1 = max(py1, vy1)
    ix2 = min(px2, vx2)
    iy2 = min(py2, vy2)

    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)

    intersection = iw * ih

    vest_area = max(
        1,
        (vx2 - vx1) * (vy2 - vy1)
    )

    return intersection / vest_area


def vest_belongs_to_person(person_box, vest_box):
    expanded = expand_box(
        person_box,
        PERSON_MARGIN
    )

    px1, py1, px2, py2 = expanded
    cx, cy = box_center(vest_box)

    center_inside = (
        px1 <= cx <= px2
        and py1 <= cy <= py2
    )

    overlap = overlap_ratio(
        person_box,
        vest_box
    )

    return (
        center_inside
        or overlap >= MIN_VEST_OVERLAP
    )


def match_vests(person_boxes, vest_boxes):
    person_has_vest = [
        False for _ in person_boxes
    ]

    for vest_box in vest_boxes:

        best_person = None
        best_score = -1

        for i, person_box in enumerate(person_boxes):

            if not vest_belongs_to_person(
                person_box,
                vest_box
            ):
                continue

            overlap = overlap_ratio(
                person_box,
                vest_box
            )

            pcx, pcy = box_center(person_box)
            vcx, vcy = box_center(vest_box)

            distance = (
                (pcx - vcx) ** 2
                + (pcy - vcy) ** 2
            ) ** 0.5

            score = overlap - distance * 0.0001

            if score > best_score:
                best_score = score
                best_person = i

        if best_person is not None:
            person_has_vest[best_person] = True

    return person_has_vest


# =========================================================
# NMS
# =========================================================

def nms(boxes, scores, iou_threshold=0.45):
    if len(boxes) == 0:
        return []

    boxes_xywh = []

    for box in boxes:
        x1, y1, x2, y2 = box

        boxes_xywh.append([
            int(x1),
            int(y1),
            int(x2 - x1),
            int(y2 - y1)
        ])

    indices = cv2.dnn.NMSBoxes(
        boxes_xywh,
        scores,
        0.01,
        iou_threshold
    )

    if len(indices) == 0:
        return []

    return [
        int(i)
        for i in np.array(indices).flatten()
    ]


# =========================================================
# PREPROCESS
# =========================================================

def preprocess(frame):
    resized = cv2.resize(
        frame,
        (IMGSZ, IMGSZ)
    )

    image = cv2.cvtColor(
        resized,
        cv2.COLOR_BGR2RGB
    )

    image = image.astype(
        np.float32
    ) / 255.0

    image = np.transpose(
        image,
        (2, 0, 1)
    )

    image = np.expand_dims(
        image,
        axis=0
    )

    return image


# =========================================================
# POSTPROCESS
# YOLO11/YOLOv8 detection ONNX:
# output thường dạng [1, 7, N]
# 4 bbox + 3 class
# =========================================================

def postprocess(output, frame_width, frame_height):
    pred = output[0]

    if pred.ndim == 3:
        pred = pred[0]

    # [7, N] -> [N, 7]
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T

    boxes = []
    scores = []
    class_ids = []

    scale_x = frame_width / IMGSZ
    scale_y = frame_height / IMGSZ

    for row in pred:

        if len(row) < 7:
            continue

        cx, cy, w, h = row[:4]

        class_scores = row[4:]

        class_id = int(
            np.argmax(class_scores)
        )

        confidence = float(
            class_scores[class_id]
        )

        if class_id == PERSON_CLASS:
            min_conf = PERSON_CONF

        elif class_id == HELMET_CLASS:
            min_conf = HELMET_CONF

        elif class_id == VEST_CLASS:
            min_conf = VEST_CONF

        else:
            continue

        if confidence < min_conf:
            continue

        x1 = (cx - w / 2) * scale_x
        y1 = (cy - h / 2) * scale_y
        x2 = (cx + w / 2) * scale_x
        y2 = (cy + h / 2) * scale_y

        boxes.append(
            (x1, y1, x2, y2)
        )

        scores.append(
            confidence
        )

        class_ids.append(
            class_id
        )

    keep = nms(
        boxes,
        scores,
        0.45
    )

    final = []

    for i in keep:
        final.append(
            (
                boxes[i],
                scores[i],
                class_ids[i]
            )
        )

    return final


# =========================================================
# DRAW
# =========================================================

def draw_box(frame, box, label, conf=None):
    x1, y1, x2, y2 = map(
        int,
        box
    )

    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (255, 255, 255),
        2
    )

    text = label

    if conf is not None:
        text += f" {conf:.2f}"

    cv2.putText(
        frame,
        text,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )


# =========================================================
# LOAD ONNX
# =========================================================

print("Loading ONNX model...")

session = ort.InferenceSession(
    MODEL_PATH,
    providers=[
        "CPUExecutionProvider"
    ]
)

input_name = session.get_inputs()[0].name

print("Model loaded.")
print("Input name:", input_name)

for inp in session.get_inputs():
    print(
        "Input:",
        inp.name,
        inp.shape,
        inp.type
    )

for out in session.get_outputs():
    print(
        "Output:",
        out.name,
        out.shape,
        out.type
    )


# =========================================================
# CAMERA
# =========================================================

cap = cv2.VideoCapture(0)

cap.set(
    cv2.CAP_PROP_FRAME_WIDTH,
    1280
)

cap.set(
    cv2.CAP_PROP_FRAME_HEIGHT,
    720
)

cap.set(
    cv2.CAP_PROP_FPS,
    30
)

if not cap.isOpened():
    print("Khong mo duoc camera USB")
    raise SystemExit

print("Camera USB da mo thanh cong")


# =========================================================
# MAIN LOOP
# =========================================================

prev_time = time.time()

while True:

    ret, frame = cap.read()

    if not ret:
        print("Khong doc duoc frame")
        break

    frame_h, frame_w = frame.shape[:2]


    # -----------------------------------------------------
    # PREPROCESS
    # -----------------------------------------------------

    input_tensor = preprocess(
        frame
    )


    # -----------------------------------------------------
    # INFERENCE
    # -----------------------------------------------------

    outputs = session.run(
        None,
        {
            input_name: input_tensor
        }
    )


    # -----------------------------------------------------
    # POSTPROCESS
    # -----------------------------------------------------

    detections = postprocess(
        outputs,
        frame_w,
        frame_h
    )

    person_boxes = []
    vest_boxes = []

    person_data = []
    helmet_data = []
    vest_data = []

    for bbox, conf, cls_id in detections:

        if cls_id == PERSON_CLASS:

            person_boxes.append(
                bbox
            )

            person_data.append(
                (bbox, conf)
            )

        elif cls_id == HELMET_CLASS:

            helmet_data.append(
                (bbox, conf)
            )

        elif cls_id == VEST_CLASS:

            vest_boxes.append(
                bbox
            )

            vest_data.append(
                (bbox, conf)
            )


    # -----------------------------------------------------
    # MATCH VEST
    # -----------------------------------------------------

    person_has_vest = match_vests(
        person_boxes,
        vest_boxes
    )


    # -----------------------------------------------------
    # TEMPORAL SMOOTHING
    # -----------------------------------------------------

    if len(person_boxes) > 0:

        frame_vest_ok = all(
            person_has_vest
        )

        vest_history.append(
            1 if frame_vest_ok else 0
        )

        if len(vest_history) < VEST_HISTORY_SIZE:

            vest_status = "CHECKING"

        else:

            good_frames = sum(
                vest_history
            )

            if good_frames >= VEST_OK_MIN_FRAMES:
                vest_status = "VEST_OK"

            else:
                vest_status = "NO_VEST"

    else:

        vest_history.clear()

        vest_status = "NO_PERSON"


    # -----------------------------------------------------
    # DRAW PERSON
    # -----------------------------------------------------

    for i, (bbox, conf) in enumerate(
        person_data
    ):

        if i < len(person_has_vest):

            if person_has_vest[i]:
                label = "person + vest"

            else:
                label = "person"

        else:
            label = "person"

        draw_box(
            frame,
            bbox,
            label,
            conf
        )


    # -----------------------------------------------------
    # DRAW HELMET
    # -----------------------------------------------------

    for bbox, conf in helmet_data:

        draw_box(
            frame,
            bbox,
            "yellow_helmet",
            conf
        )


    # -----------------------------------------------------
    # DRAW VEST
    # -----------------------------------------------------

    for bbox, conf in vest_data:

        draw_box(
            frame,
            bbox,
            "yellow_vest",
            conf
        )


    # -----------------------------------------------------
    # FPS
    # -----------------------------------------------------

    now = time.time()

    dt = now - prev_time
    prev_time = now

    fps = (
        1 / dt
        if dt > 0
        else 0
    )


    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    cv2.putText(
        frame,
        f"VEST: {vest_status}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )


    # -----------------------------------------------------
    # ALERT
    # -----------------------------------------------------

    if vest_status == "NO_VEST":

        cv2.putText(
            frame,
            "WARNING: NO_VEST",
            (20, 130),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (255, 255, 255),
            3
        )

        print(
            "WARNING: NO_VEST"
        )


    # -----------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------

    cv2.imshow(
        "PPE Detection",
        frame
    )

    key = (
        cv2.waitKey(1)
        & 0xFF
    )

    if key == ord("q"):
        break


# =========================================================
# CLEANUP
# =========================================================

cap.release()

cv2.destroyAllWindows()

print("Stopped.")
