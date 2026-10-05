import time


class ViolationTracker:
    def __init__(self, violation_seconds=5):
        self.violation_seconds = violation_seconds

        # Lưu thông tin từng worker
        self.workers = {}

    def update(self, worker_id, helmet, vest):
        now = time.time()

        # Worker mới
        if worker_id not in self.workers:
            self.workers[worker_id] = {
                "violation_start": None,
                "violation_count": 0,
                "violation_active": False,
            }

        worker = self.workers[worker_id]

        # Có đầy đủ PPE
        safe = helmet and vest

        if safe:
            # Reset thời gian vi phạm
            worker["violation_start"] = None
            worker["violation_active"] = False

        else:
            # Bắt đầu tính thời gian vi phạm
            if worker["violation_start"] is None:
                worker["violation_start"] = now

            violation_time = now - worker["violation_start"]

            # Đủ thời gian quy định
            if violation_time >= self.violation_seconds:

                # Chỉ tăng số lần vi phạm một lần
                if not worker["violation_active"]:
                    worker["violation_count"] += 1
                    worker["violation_active"] = True

        # Tính thời gian hiện tại
        if worker["violation_start"] is not None:
            duration = now - worker["violation_start"]
        else:
            duration = 0

        return {
            "safe": safe,
            "violation_active": worker["violation_active"],
            "violation_count": worker["violation_count"],
            "violation_duration": duration,
        }