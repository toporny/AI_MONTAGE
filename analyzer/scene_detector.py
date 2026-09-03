"""
Moduł detekcji scen i cięć kamerowych z wykorzystaniem PySceneDetect / OpenCV fallback.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple
import cv2

from utils.logger import logger

try:
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import AdaptiveDetector, ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False


class SceneDetector:
    def __init__(self, threshold: float = 27.0, min_scene_duration_sec: float = 0.8):
        self.threshold = threshold
        self.min_scene_duration_sec = min_scene_duration_sec

    def detect_scenes(self, video_path: Path, fps: float, duration: float) -> List[Dict[str, Any]]:
        """
        Wykrywa punkty cięcia i zwraca listę scen w postaci:
        [{"start_sec": 0.0, "end_sec": 2.5, "duration": 2.5}, ...]
        """
        scenes: List[Dict[str, Any]] = []

        if SCENEDETECT_AVAILABLE:
            try:
                scenes = self._detect_with_scenedetect(video_path)
            except Exception as e:
                logger.warning(f"PySceneDetect zgłosił błąd dla {video_path.name}: {e}. Używam fallbacku OpenCV.")
                scenes = self._detect_with_opencv_fallback(video_path, fps, duration)
        else:
            scenes = self._detect_with_opencv_fallback(video_path, fps, duration)

        # Jeśli nie wykryto żadnej sceny lub wideo jest jednolite, utwórz 1 scenę obejmującą całość
        if not scenes:
            scenes = [{
                "scene_idx": 0,
                "start_sec": 0.0,
                "end_sec": round(duration, 3),
                "duration": round(duration, 3)
            }]

        return scenes

    def _detect_with_scenedetect(self, video_path: Path) -> List[Dict[str, Any]]:
        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=self.threshold, min_scene_len=int(self.min_scene_duration_sec * video.frame_rate)))
        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()

        results = []
        for i, (start_time, end_time) in enumerate(scene_list):
            start_s = start_time.get_seconds()
            end_s = end_time.get_seconds()
            dur = end_s - start_s
            if dur >= self.min_scene_duration_sec:
                results.append({
                    "scene_idx": i,
                    "start_sec": round(start_s, 3),
                    "end_sec": round(end_s, 3),
                    "duration": round(dur, 3)
                })
        return results

    def _detect_with_opencv_fallback(self, video_path: Path, fps: float, duration: float) -> List[Dict[str, Any]]:
        """Prosty fallback oparty na różnicach histogramów klatek."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        cuts = [0.0]
        prev_hist = None
        frame_idx = 0
        min_frames = int(self.min_scene_duration_sec * fps)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Liczymy histogram co drugą klatkę dla wydajności
            if frame_idx % 2 == 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

                if prev_hist is not None:
                    diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    curr_time = frame_idx / fps
                    if diff < 0.45 and (frame_idx - int(cuts[-1] * fps)) >= min_frames:
                        cuts.append(curr_time)
                prev_hist = hist

            frame_idx += 1

        cap.release()
        cuts.append(duration)

        results = []
        for i in range(len(cuts) - 1):
            s_sec = cuts[i]
            e_sec = cuts[i+1]
            dur = e_sec - s_sec
            if dur >= self.min_scene_duration_sec:
                results.append({
                    "scene_idx": i,
                    "start_sec": round(s_sec, 3),
                    "end_sec": round(e_sec, 3),
                    "duration": round(dur, 3)
                })

        return results
