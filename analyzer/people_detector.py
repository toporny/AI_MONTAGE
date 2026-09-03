"""
Moduł detekcji osób i twarzy przy użyciu YOLO (ultralytics) z klasyfikacją planów filmowych.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from utils.logger import logger

try:
    from ultralytics import YOLO
    import torch
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False


class PeopleDetector:
    def __init__(self, model_name: str = "yolov8n.pt", device: str = "cuda"):
        self.model_name = model_name
        self.device = device if (torch.cuda.is_available() and device == "cuda") else "cpu"
        self.model = None
        self._init_model()

    def _init_model(self):
        if not ULTRALYTICS_AVAILABLE:
            logger.warning("Pakiet ultralytics nie jest zainstalowany. Detekcja osób będzie wyłączona.")
            return

        try:
            logger.info(f"Ładowanie modelu YOLO ({self.model_name}) na urządzenie: {self.device}")
            self.model = YOLO(self.model_name)
        except Exception as e:
            logger.warning(f"Błąd inicjalizacji modelu YOLO {self.model_name}: {e}. Spróbuję pobrać yolov8n.pt.")
            try:
                self.model = YOLO("yolov8n.pt")
            except Exception as e2:
                logger.error(f"Nie udało się załadować żadnego modelu YOLO: {e2}")
                self.model = None

    def detect_batch(self, frames: List[np.ndarray]) -> List[Dict[str, Any]]:
        """
        Analizuje batch klatek i zwraca listę wyników detekcji dla każdej klatki.
        """
        if not frames:
            return []

        if self.model is None:
            # Fallback dla braku modelu YOLO
            return [self._empty_result() for _ in frames]

        try:
            # Klasa 0 w COCO to 'person'
            results = self.model(
                frames,
                classes=[0],
                device=self.device,
                verbose=False,
                conf=0.30
            )

            analyzed = []
            for i, res in enumerate(results):
                h, w = frames[i].shape[:2]
                frame_area = float(w * h)
                boxes = res.boxes

                if boxes is None or len(boxes) == 0:
                    analyzed.append(self._empty_result())
                    continue

                boxes_xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                num_people = len(boxes_xyxy)

                max_box_area = 0.0
                total_people_area = 0.0
                centered_scores = []

                for box in boxes_xyxy:
                    x1, y1, x2, y2 = box
                    bw = max(0.0, x2 - x1)
                    bh = max(0.0, y2 - y1)
                    area = bw * bh
                    area_ratio = area / frame_area
                    total_people_area += area_ratio
                    if area_ratio > max_box_area:
                        max_box_area = area_ratio

                    # Oblicz odległość środka postaci od środka kadru
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    dist_from_center_x = abs(cx - (w / 2.0)) / (w / 2.0)
                    dist_from_center_y = abs(cy - (h / 2.0)) / (h / 2.0)
                    
                    # Kara jeśli postać jest mocno ucięta przy krawędzi
                    edge_penalty = 0.0
                    if x1 <= 5 or x2 >= w - 5:
                        edge_penalty += 0.25
                    if y1 <= 5:
                        edge_penalty += 0.15

                    box_comp = max(0.0, 1.0 - (0.5 * dist_from_center_x + 0.3 * dist_from_center_y + edge_penalty))
                    centered_scores.append(box_comp)

                avg_comp = float(np.mean(centered_scores)) if centered_scores else 0.5
                composition_score = float(np.clip(avg_comp * 100.0, 0.0, 100.0))

                # Określenie typu planu (Shot Scale)
                if num_people >= 4 or (num_people >= 3 and total_people_area > 0.35):
                    shot_type = "crowd"
                elif max_box_area >= 0.28:
                    shot_type = "close_up"
                elif max_box_area >= 0.08:
                    shot_type = "medium"
                else:
                    shot_type = "wide"

                # Obliczenie ogólnego wyniku zainteresowania ludźmi (0 - 100)
                # Wyższy wynik dla wyrazistych postaci, grup i dobrej kompozycji
                base_score = min(num_people * 20.0, 60.0) + min(max_box_area * 100.0, 30.0) + (composition_score * 0.10)
                people_interest_score = float(np.clip(base_score, 0.0, 100.0))

                analyzed.append({
                    "has_people": True,
                    "num_people": int(num_people),
                    "max_person_area_ratio": round(float(max_box_area), 4),
                    "total_people_area_ratio": round(float(total_people_area), 4),
                    "shot_type": shot_type,
                    "composition_score": round(composition_score, 2),
                    "people_score": round(people_interest_score, 2)
                })

            return analyzed

        except Exception as e:
            logger.error(f"Błąd podczas batchowej detekcji YOLO: {e}")
            return [self._empty_result() for _ in frames]

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "has_people": False,
            "num_people": 0,
            "max_person_area_ratio": 0.0,
            "total_people_area_ratio": 0.0,
            "shot_type": "no_people",
            "composition_score": 50.0,
            "people_score": 10.0
        }
