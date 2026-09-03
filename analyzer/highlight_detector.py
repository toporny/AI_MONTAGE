"""
Moduł wyszukiwania i oceny najlepszych fragmentów wideo (Highlight Detector).
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from utils.config_loader import Config


class HighlightDetector:
    def __init__(self, config: Config):
        self.config = config

    def extract_highlights(
        self,
        frame_data: List[Dict[str, Any]],
        scenes: List[Dict[str, Any]],
        video_duration: float
    ) -> List[Dict[str, Any]]:
        """
        Dla każdej sceny w wideo przeszukuje okna czasowe i wyłania najlepsze,
        niepokrywające się fragmenty o wysokiej wartości wizualnej (highlighty).
        """
        if not frame_data:
            return []

        all_candidates: List[Dict[str, Any]] = []
        window_sizes = self.config.highlight_window_sizes

        # Przeglądaj każdą scenę niezależnie (nie tnij w poprzek cięć sceny)
        for scene in scenes:
            scene_start = scene["start_sec"]
            scene_end = scene["end_sec"]
            scene_duration = scene_end - scene_start

            # Pobierz klatki należące do tej sceny
            scene_frames = [
                f for f in frame_data
                if scene_start <= f["timestamp"] <= scene_end
            ]

            if len(scene_frames) < 2:
                continue

            # Sprawdź różne rozmiary okien czasowych
            for win_size in window_sizes:
                if win_size > scene_duration:
                    continue

                # Krok przesuwania okna (np. 0.4s)
                step_sec = 0.4
                current_start = scene_start

                while current_start + win_size <= scene_end + 0.05:
                    current_end = current_start + win_size
                    
                    # Zbierz dane klatek w oknie
                    window_frames = [
                        f for f in scene_frames
                        if current_start <= f["timestamp"] <= current_end
                    ]

                    if not window_frames:
                        current_start += step_sec
                        continue

                    # Oblicz zagregowane metryki dla tego okna
                    cand = self._score_window(window_frames, current_start, current_end)
                    if cand is not None:
                        all_candidates.append(cand)

                    current_start += step_sec

        # Selekcja i deduplikacja (Non-Maximum Suppression) kandydatów
        selected_highlights = self._non_max_suppression(all_candidates)
        
        # Posortuj chronologicznie
        selected_highlights.sort(key=lambda x: x["start_sec"])
        return selected_highlights

    def _score_window(
        self,
        window_frames: List[Dict[str, Any]],
        start_sec: float,
        end_sec: float
    ) -> Optional[Dict[str, Any]]:
        """Oblicza skumulowany wynik atrakcyjności dla danego przedziału czasowego."""
        n = len(window_frames)
        if n == 0:
            return None

        # Średnie metryki
        avg_sharpness = float(np.mean([f.get("sharpness", 50.0) for f in window_frames]))
        avg_exposure = float(np.mean([f.get("exposure_score", 50.0) for f in window_frames]))
        avg_stability = float(np.mean([f.get("stability_score", 75.0) for f in window_frames]))
        avg_people_score = float(np.mean([f.get("people_score", 10.0) for f in window_frames]))
        avg_composition = float(np.mean([f.get("composition_score", 50.0) for f in window_frames]))
        avg_motion_score = float(np.mean([f.get("motion_score", 10.0) for f in window_frames]))
        
        # Informacje o osobach i planie
        shot_types = [f.get("shot_type", "no_people") for f in window_frames]
        # Wybierz dominujący shot_type
        dominant_shot_type = max(set(shot_types), key=shot_types.count)
        max_people = max([f.get("num_people", 0) for f in window_frames])

        # Kary
        blur_frames_ratio = float(np.mean([1.0 if f.get("is_blurred", False) else 0.0 for f in window_frames]))
        blur_pen = blur_frames_ratio * self.config.blur_penalty * 100.0

        exp_pen = (100.0 - avg_exposure) * self.config.exposure_penalty
        shake_pen = (100.0 - avg_stability) * self.config.camera_shake_penalty

        # Wynik ważony
        w_sharp = self.config.weight_sharpness
        w_ppl = self.config.weight_people
        w_mot = self.config.weight_motion
        w_comp = self.config.weight_composition

        raw_score = (
            (w_sharp * avg_sharpness) +
            (w_ppl * avg_people_score) +
            (w_mot * avg_motion_score) +
            (w_comp * avg_composition)
        )

        # Odjęcie kar
        final_score = raw_score - blur_pen - (exp_pen * 0.5) - (shake_pen * 0.5)
        final_score = float(np.clip(final_score, 0.0, 100.0))

        # Tagi opisowe
        tags = []
        if max_people > 0:
            tags.append(f"{max_people}_people")
            tags.append(dominant_shot_type)
        if avg_motion_score > 40:
            tags.append("dynamic_motion")
        if avg_sharpness > 75:
            tags.append("crisp_quality")

        return {
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "duration": round(end_sec - start_sec, 3),
            "score": round(final_score, 2),
            "shot_type": dominant_shot_type,
            "max_people": int(max_people),
            "motion_score": round(avg_motion_score, 2),
            "sharpness": round(avg_sharpness, 2),
            "stability": round(avg_stability, 2),
            "tags": tags
        }

    def _non_max_suppression(self, candidates: List[Dict[str, Any]], iou_threshold: float = 0.45) -> List[Dict[str, Any]]:
        """
        Usuwa silnie nakładające się okna, zachowując te o najwyższym wyniku (score).
        """
        if not candidates:
            return []

        # Sortuj malejąco po wyniku
        candidates.sort(key=lambda x: x["score"], reverse=True)
        selected: List[Dict[str, Any]] = []

        for cand in candidates:
            c_start = cand["start_sec"]
            c_end = cand["end_sec"]
            c_dur = cand["duration"]

            # Sprawdź nakładanie (IoU) z już wybranymi
            overlap = False
            for sel in selected:
                s_start = sel["start_sec"]
                s_end = sel["end_sec"]
                s_dur = sel["duration"]

                inter_start = max(c_start, s_start)
                inter_end = min(c_end, s_end)
                inter_dur = max(0.0, inter_end - inter_start)

                union_dur = c_dur + s_dur - inter_dur
                iou = inter_dur / union_dur if union_dur > 0 else 0.0

                if iou > iou_threshold or inter_dur > (0.6 * min(c_dur, s_dur)):
                    overlap = True
                    break

            if not overlap:
                selected.append(cand)

        return selected
