"""
Moduł analizy krzywej energii, natężenia dźwięku, zmian dynamiki oraz wykrywania dropów i kulminacji.
"""

from typing import Any, Dict, List, Tuple
import numpy as np
from scipy.ndimage import gaussian_filter1d

from utils.logger import logger

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


class EnergyAnalyzer:
    def __init__(self, smoothing_sec: float = 0.5, thresholds: Dict[str, float] = None):
        self.smoothing_sec = smoothing_sec
        self.thresholds = thresholds or {
            "calm": 0.30,
            "medium": 0.60,
            "high": 0.80,
            "drop_peak": 0.85
        }

    def analyze_energy(self, y: np.ndarray, sr: int, beat_times: List[float]) -> Dict[str, Any]:
        """
        Oblicza ciągłą krzywą energii (RMS + spectral centroid/flux) oraz klasyfikuje poziomy energii.
        """
        if not LIBROSA_AVAILABLE:
            raise RuntimeError("Biblioteka librosa jest wymagana do analizy energii.")

        logger.info("Obliczanie krzywej energii i dynamiki utworu...")

        hop_length = 512
        frame_rate = sr / hop_length

        # 1. Obliczenie RMS (Root Mean Square Energy)
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]

        # 2. Obliczenie Spectral Centroid (jasność brzmienia / obecność wysokich tonów i mocnych transjentów)
        spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]
        spectral_centroid_norm = (spectral_centroid - np.min(spectral_centroid)) / (np.ptp(spectral_centroid) + 1e-6)

        # 3. Złożenie surowej energii: 70% RMS + 30% Spectral Centroid
        rms_norm = (rms - np.min(rms)) / (np.ptp(rms) + 1e-6)
        combined_energy = (0.70 * rms_norm) + (0.30 * spectral_centroid_norm)

        # 4. Wygładzenie filtrem Gaussa dla eliminacji szumów mikro-transjentów
        sigma = int(self.smoothing_sec * frame_rate)
        smoothed_energy = gaussian_filter1d(combined_energy, sigma=max(1, sigma))
        # Normalizacja do [0.0, 1.0]
        smoothed_energy = (smoothed_energy - np.min(smoothed_energy)) / (np.ptp(smoothed_energy) + 1e-6)

        # Oblicz czasy dla każdej ramki energii
        energy_times = librosa.frames_to_time(np.arange(len(smoothed_energy)), sr=sr, hop_length=hop_length)

        # 5. Obliczenie energii per beat
        beat_energies = []
        for i in range(len(beat_times)):
            t_start = beat_times[i]
            t_end = beat_times[i+1] if i + 1 < len(beat_times) else t_start + 0.5
            
            mask = (energy_times >= t_start) & (energy_times <= t_end)
            if np.any(mask):
                b_energy = float(np.mean(smoothed_energy[mask]))
            else:
                # Interpolacja najbliższej wartości
                idx = np.argmin(np.abs(energy_times - t_start))
                b_energy = float(smoothed_energy[idx])
            
            beat_energies.append(round(b_energy, 4))

        # 6. Detekcja dropów i kulminacji
        # Drop charakteryzuje się:
        # - wzrostem energii (d_energy > threshold) lub
        # - skrajnie wysokim poziomem energii (> drop_peak) po wcześniejszym wyciszeniu/build-upie
        drops = self._detect_drops(beat_times, beat_energies)

        # 7. Segmentacja utworu na sekcje energetyczne (Continuous Energy Blocks)
        energy_blocks = self._segment_energy_blocks(beat_times, beat_energies, drops)

        logger.info(f"Wykryto {len(drops)} punktów kulminacyjnych (dropów/mocnych wejść) oraz {len(energy_blocks)} sekcji energetycznych.")

        return {
            "average_energy": round(float(np.mean(smoothed_energy)), 3),
            "max_energy": round(float(np.max(smoothed_energy)), 3),
            "beat_energies": beat_energies,
            "drops": drops,
            "energy_blocks": energy_blocks
        }

    def _detect_drops(self, beat_times: List[float], beat_energies: List[float]) -> List[Dict[str, Any]]:
        """Wykrywa punkty dropów i gwałtownych wzrostów energii."""
        drops = []
        if len(beat_energies) < 8:
            return drops

        arr = np.array(beat_energies)
        diff = np.diff(arr)

        for i in range(4, len(arr) - 2):
            curr_e = arr[i]
            prev_e = np.mean(arr[max(0, i - 4) : i])
            
            # Warunek 1: Znaczący skok energii (> 0.22) i obecny poziom > 0.65
            is_surge = (curr_e - prev_e > 0.22) and (curr_e >= 0.65)
            # Warunek 2: Absolutny pik energetyczny (> 0.88)
            is_peak = curr_e >= self.thresholds["drop_peak"] and curr_e == np.max(arr[max(0, i - 3) : min(len(arr), i + 4)])

            if is_surge or is_peak:
                t_drop = beat_times[i]
                # Sprawdź czy nie jest zbyt blisko poprzedniego dropu (min 6 sekund odstępu)
                if not drops or (t_drop - drops[-1]["time_sec"] > 6.0):
                    drops.append({
                        "drop_idx": len(drops),
                        "beat_idx": i,
                        "time_sec": round(t_drop, 3),
                        "energy": round(float(curr_e), 3),
                        "type": "surge" if is_surge else "peak"
                    })

        return drops

    def _segment_energy_blocks(
        self,
        beat_times: List[float],
        beat_energies: List[float],
        drops: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Dzieli utwór na spójne bloki energetyczne."""
        blocks: List[Dict[str, Any]] = []
        if not beat_times:
            return blocks

        drop_beat_indices = {d["beat_idx"] for d in drops}

        def get_category(energy: float, is_drop: bool) -> str:
            if is_drop or energy >= self.thresholds["drop_peak"]:
                return "drop_or_climax"
            elif energy >= self.thresholds["high"]:
                return "high_energy"
            elif energy >= self.thresholds["calm"]:
                return "medium_energy"
            else:
                return "calm"

        current_block = {
            "block_idx": 0,
            "start_beat_idx": 0,
            "start_sec": beat_times[0],
            "category": get_category(beat_energies[0], 0 in drop_beat_indices),
            "energies": [beat_energies[0]]
        }

        for i in range(1, len(beat_times)):
            cat = get_category(beat_energies[i], i in drop_beat_indices)
            if cat != current_block["category"] and len(current_block["energies"]) >= 4:
                # Zamknij bieżący blok
                end_sec = beat_times[i]
                current_block["end_sec"] = end_sec
                current_block["end_beat_idx"] = i - 1
                current_block["duration"] = round(end_sec - current_block["start_sec"], 3)
                current_block["avg_energy"] = round(float(np.mean(current_block["energies"])), 3)
                blocks.append(current_block)

                current_block = {
                    "block_idx": len(blocks),
                    "start_beat_idx": i,
                    "start_sec": beat_times[i],
                    "category": cat,
                    "energies": [beat_energies[i]]
                }
            else:
                current_block["energies"].append(beat_energies[i])

        # Zamknij ostatni blok
        last_end = beat_times[-1] + 0.5
        current_block["end_sec"] = round(last_end, 3)
        current_block["end_beat_idx"] = len(beat_times) - 1
        current_block["duration"] = round(last_end - current_block["start_sec"], 3)
        current_block["avg_energy"] = round(float(np.mean(current_block["energies"])), 3)
        blocks.append(current_block)

        return blocks
