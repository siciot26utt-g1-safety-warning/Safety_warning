from ultralytics import YOLO


class SafetyAnalyzer:
    def __init__(self, model_path="models/best.pt"):
        self.model = YOLO(model_path)

    def analyze(self, frame, conf=0.4):
        results = self.model(frame, conf=conf, verbose=False)[0]

        persons = []
        helmets = []
        vests = []

        if results.boxes is None:
            return persons

        for box in results.boxes:
            cls = int(box.cls[0])
            confidence = float(box.conf[0])

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            detection = {
                "bbox": (x1, y1, x2, y2),
                "confidence": confidence
            }

            if cls == 0:
                persons.append(detection)

            elif cls == 1:
                helmets.append(detection)

            elif cls == 2:
                vests.append(detection)

        # Ghép helmet/vest vào từng person
        workers = []

        for i, person in enumerate(persons):
            px1, py1, px2, py2 = person["bbox"]

            person_width = px2 - px1
            person_height = py2 - py1

            # Vùng đầu: khoảng 40% phía trên người
            head_region = (
                px1,
                py1,
                px2,
                py1 + int(person_height * 0.4)
            )

            # Vùng thân: khoảng giữa người
            body_region = (
                px1,
                py1 + int(person_height * 0.2),
                px2,
                py1 + int(person_height * 0.8)
            )

            helmet_found = False
            vest_found = False

            # Kiểm tra helmet nằm trong vùng đầu
            for helmet in helmets:
                hx1, hy1, hx2, hy2 = helmet["bbox"]

                hc_x = (hx1 + hx2) / 2
                hc_y = (hy1 + hy2) / 2

                if (
                    head_region[0] <= hc_x <= head_region[2]
                    and head_region[1] <= hc_y <= head_region[3]
                ):
                    helmet_found = True
                    break

            # Kiểm tra vest nằm trong vùng thân
            for vest in vests:
                vx1, vy1, vx2, vy2 = vest["bbox"]

                vc_x = (vx1 + vx2) / 2
                vc_y = (vy1 + vy2) / 2

                if (
                    body_region[0] <= vc_x <= body_region[2]
                    and body_region[1] <= vc_y <= body_region[3]
                ):
                    vest_found = True
                    break

            workers.append({
                "id": i + 1,
                "bbox": person["bbox"],
                "helmet": helmet_found,
                "vest": vest_found,
                "safe": helmet_found and vest_found
            })

        return workers