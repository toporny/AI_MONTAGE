"""
Moduł analizy dynamiki i wektorów ruchu (Optical Flow) w wideo.
"""

from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


class MotionAnalyzer:
    def __init__(self, flow_scale: float = 0.5):
        self.flow_scale = flow_scale

    def compute_motion(self, prev_frame: np.ndarray, curr_frame: np.ndarray) -> Dict[str, Any]:
        """
        Oblicza parametry ruchu między dwiema kolejnymi klatkami:
        - średnia wielkość wektora ruchu (motion_magnitude)
        - kierunek ruchu
        - spójność wektorów (ruch uporządkowany vs chaotyczny)
        - klasyfikacja dynamiki (static / smooth_motion / high_action / erratic)
        """
        # Konwersja do skali szarości i przeskalowanie dla super szybkiego obliczania Optical Flow
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY) if len(prev_frame.shape) == 3 else prev_frame
        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY) if len(curr_frame.shape) == 3 else curr_frame

        if self.flow_scale != 1.0:
            h, w = prev_gray.shape
            prev_small = cv2.resize(prev_gray, (int(w * self.flow_scale), int(h * self.flow_scale)), interpolation=cv2.INTER_AREA)
            curr_small = cv2.resize(curr_gray, (int(w * self.flow_scale), int(h * self.flow_scale)), interpolation=cv2.INTER_AREA)
        else:
            prev_small, curr_small = prev_gray, curr_gray

        # Farneback Optical Flow
        flow = cv2.calcOpticalFlowFarneback(
            prev_small, curr_small, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )

        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        mean_mag = float(np.mean(mag))
        max_mag = float(np.max(mag))
        p95_mag = float(np.percentile(mag, 95))

        # Obliczanie spójności kierunkowej (wariancja kątów dla aktywnych wektorów)
        active_mask = mag > 0.5
        if np.sum(active_mask) > 50:
            ang_active = ang[active_mask]
            # Spójność kierunku: używamy wektora wypadkowego jednostkowych wektorów kąta
            cos_mean = np.mean(np.cos(ang_active))
            sin_mean = np.mean(np.sin(ang_active))
            coherence = float(np.sqrt(cos_mean**2 + sin_mean**2))  # 0.0 (chaos) do 1.0 (idealny jeden kierunek)
        else:
            coherence = 1.0

        # Normalizacja wyniku ruchu do skali 0 - 100
        # mean_mag: 0.1 (statyczny) -> 0, 1.5 -> 50, 4.0+ -> 100
        motion_score = float(np.clip(mean_mag * 25.0, 0.0, 100.0))

        # Klasyfikacja ruchu
        if mean_mag < 0.25:
            motion_category = "static"
        elif mean_mag > 3.0 and coherence < 0.35:
            motion_category = "erratic_shake"
        elif mean_mag > 2.5:
            motion_category = "high_action"
        else:
            motion_category = "smooth_motion"

        return {
            "mean_motion_mag": round(mean_mag, 3),
            "p95_motion_mag": round(p95_mag, 3),
            "coherence": round(coherence, 3),
            "motion_score": round(motion_score, 2),
            "motion_category": motion_category
        }
