"""
Moduł detekcji BPM, beatów, downbeatów, taktów i fraz muzycznych.
"""

from typing import Any, Dict, List, Tuple
import numpy as np

from utils.logger import logger

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


class BeatDetector:
    def __init__(self, beats_per_bar: int = 4):
        self.beats_per_bar = beats_per_bar

    def analyze_beats(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
        """
        Wykrywa BPM, czasy wszystkich beatów, takty i frazy muzyczne.
        """
        if not LIBROSA_AVAILABLE:
            raise RuntimeError("Biblioteka librosa nie jest dostępna do analizy muzyki.")

        logger.info("Analizowanie siatki rytmicznej i tempa utworu...")

        # 1. Obliczenie onset envelope
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)

        # 2. Wykrywanie tempa (BPM) i beatów
        tempo, beat_frames = librosa.beat.beat_track(
            y=y,
            sr=sr,
            onset_envelope=onset_env,
            trim=False
        )

        # Tempo może być tablicą 1-elementową w nowszych wersjach librosa
        bpm = float(np.mean(tempo)) if hasattr(tempo, "__len__") else float(tempo)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beat_times_list = [round(float(t), 3) for t in beat_times]

        if not beat_times_list:
            # Fallback dla bardzo cichych utworów
            duration = librosa.get_duration(y=y, sr=sr)
            bpm = 120.0
            beat_interval = 60.0 / bpm
            beat_times_list = [round(float(t), 3) for t in np.arange(0.0, duration, beat_interval)]

        # 3. Wykrywanie downbeatów i taktów (bars)
        # Grupowanie beatów w takty (np. 4 beaty na takt)
        bars: List[Dict[str, Any]] = []
        bar_start_times: List[float] = []

        for i in range(0, len(beat_times_list), self.beats_per_bar):
            bar_beats = beat_times_list[i : i + self.beats_per_bar]
            if not bar_beats:
                continue
            bar_start = bar_beats[0]
            bar_start_times.append(bar_start)
            
            # Koniec taktu to początek następnego lub szacunek na podstawie odstępu
            if i + self.beats_per_bar < len(beat_times_list):
                bar_end = beat_times_list[i + self.beats_per_bar]
            else:
                avg_interval = (bar_beats[-1] - bar_beats[0]) / max(1, len(bar_beats) - 1) if len(bar_beats) > 1 else (60.0 / bpm)
                bar_end = bar_beats[-1] + avg_interval

            bars.append({
                "bar_idx": len(bars),
                "start_sec": bar_start,
                "end_sec": round(bar_end, 3),
                "duration": round(bar_end - bar_start, 3),
                "beats": bar_beats
            })

        # 4. Wykrywanie fraz muzycznych (np. fraza 4-taktowa = 16 beatów lub 8-taktowa = 32 beaty)
        phrases: List[Dict[str, Any]] = []
        bars_per_phrase = 4  # Typowa fraza w muzyce rozrywkowej to 4 takty

        for p_idx in range(0, len(bars), bars_per_phrase):
            phrase_bars = bars[p_idx : p_idx + bars_per_phrase]
            if not phrase_bars:
                continue
            p_start = phrase_bars[0]["start_sec"]
            p_end = phrase_bars[-1]["end_sec"]
            phrases.append({
                "phrase_idx": len(phrases),
                "start_sec": p_start,
                "end_sec": p_end,
                "duration": round(p_end - p_start, 3),
                "num_bars": len(phrase_bars)
            })

        logger.info(f"Wykryto BPM: {bpm:.1f}, Liczba beatów: {len(beat_times_list)}, Taktów: {len(bars)}, Fraz: {len(phrases)}")

        return {
            "bpm": round(bpm, 2),
            "beat_count": len(beat_times_list),
            "beat_times": beat_times_list,
            "bar_count": len(bars),
            "bars": bars,
            "bar_start_times": bar_start_times,
            "phrases": phrases
        }
