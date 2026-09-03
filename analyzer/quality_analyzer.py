"""
Moduł oceny jakości technicznej klatki i wideo:
- ostrość (Laplacian variance, wskaźnik rozmycia / motion blur)
- naświetlenie (prześwietlenia, niedoświetlenia, kontrast, balans luma)
- stabilność kadru (analiza drgań kamery)
"""

from typing import Any, Dict, List, Tuple
import cv2
import numpy as np


class QualityAnalyzer:
    def __init__(self, blur_threshold: float = 80.0):
        self.blur_threshold = blur_threshold

    def analyze_frame(self, frame: np.ndarray) -> Dict[str, float]:
        """
        Ocenia pojedynczą klatkę pod kątem parametrów technicznych.
        Zwraca słownik z metrykami znormalizowanymi do 0.0 - 100.0.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        
        # 1. Ostrość (Laplacian Variance)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        # Normalizacja: np. 20 (bardzo rozmazane) -> 0, 150+ (bardzo ostre) -> 100
        sharpness_score = float(np.clip((laplacian_var - 20.0) / 1.5, 0.0, 100.0))
        is_blurred = laplacian_var < self.blur_threshold

        # 2. Ekspozycja i Luma
        mean_luma = float(np.mean(gray))
        std_luma = float(np.std(gray))
        
        # Procent pikseli prześwietlonych (> 245) i niedoświetlonych (< 15)
        overexposed_ratio = float(np.mean(gray > 245))
        underexposed_ratio = float(np.mean(gray < 15))

        # Ocena ekspozycji (idealna średnia w okolicach 110-150, wysoki std = dobry kontrast)
        exposure_penalty = (overexposed_ratio * 120.0) + (underexposed_ratio * 100.0)
        if mean_luma < 40:
            exposure_penalty += (40 - mean_luma) * 1.5
        elif mean_luma > 215:
            exposure_penalty += (mean_luma - 215) * 1.5

        exposure_score = float(np.clip(100.0 - exposure_penalty, 0.0, 100.0))
        contrast_score = float(np.clip(std_luma * 1.6, 0.0, 100.0))

        # Ogólna ocena jakości klatki
        frame_quality = (0.50 * sharpness_score) + (0.30 * exposure_score) + (0.20 * contrast_score)

        return {
            "sharpness": round(sharpness_score, 2),
            "laplacian_var": round(laplacian_var, 2),
            "is_blurred": bool(is_blurred),
            "mean_luma": round(mean_luma, 2),
            "exposure_score": round(exposure_score, 2),
            "contrast_score": round(contrast_score, 2),
            "overexposed_ratio": round(overexposed_ratio, 4),
            "underexposed_ratio": round(underexposed_ratio, 4),
            "frame_quality": round(float(frame_quality), 2)
        }

    def compute_stability_score(self, prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
        """
        Oblicza wskaźnik stabilności między dwiema klatkami (0 - bardzo niestabilne/szarpane, 100 - stabilne/statyczne).
        """
        try:
            # Szybkie punkty GoodFeaturesToTrack
            p0 = cv2.goodFeaturesToTrack(prev_gray, maxCorners=100, qualityLevel=0.01, minDistance=20)
            if p0 is None or len(p0) < 6:
                return 75.0

            p1, st, err = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, p0, None)
            good_p0 = p0[st == 1]
            good_p1 = p1[st == 1]

            if len(good_p0) < 6:
                return 70.0

            # Estymacja transformacji afinicznej / translacji
            dx = np.mean(good_p1[:, 0] - good_p0[:, 0])
            dy = np.mean(good_p1[:, 1] - good_p0[:, 1])
            jitter = float(np.std(good_p1[:, 0] - good_p0[:, 0]) + np.std(good_p1[:, 1] - good_p0[:, 1]))

            # Normalizacja jitteru: mały jitter = wysoka stabilność
            stability = float(np.clip(100.0 - (jitter * 8.0), 0.0, 100.0))
            return round(stability, 2)
        except Exception:
            return 75.0
