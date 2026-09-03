"""
Moduł budowania rytmicznej osi czasu montażu (Timeline Builder).
Dzieli utwór na precyzyjne sloty ujęć zsynchronizowane z beatami i energią.
"""

from typing import Any, Dict, List, Optional
import numpy as np

from utils.config_loader import Config
from utils.logger import logger


class TimelineBuilder:
    def __init__(self, config: Config):
        self.config = config

    def build_timeline_slots(self, music_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Tworzy listę slotów ujęć zsynchronizowanych z rytmem i energią utworu.
        """
        duration = music_data["duration"]
        beat_times = music_data.get("beat_times", [])
        beat_energies = music_data.get("beat_energies", [])
        drops = music_data.get("drops", [])
        energy_blocks = music_data.get("energy_blocks", [])

        if not beat_times:
            # Fallback dla braku beatów
            logger.warning("Brak siatki beatów - podział co 2.5s.")
            return self._build_fixed_slots(duration, 2.5)

        drop_times = [d["time_sec"] for d in drops]
        drop_indices = {d["beat_idx"] for d in drops}

        min_cut_dur = max(1.0, getattr(self.config, "min_cut_duration_sec", 1.20))
        slots: List[Dict[str, Any]] = []
        curr_beat_idx = 0
        total_beats = len(beat_times)

        while curr_beat_idx < total_beats:
            curr_time = beat_times[curr_beat_idx]
            curr_energy = beat_energies[curr_beat_idx] if curr_beat_idx < len(beat_energies) else 0.5
            
            # Sprawdź czy bieżący beat to drop
            is_drop = curr_beat_idx in drop_indices

            # Określ kategorię energii
            if is_drop or curr_energy >= self.config.energy_thresholds.get("drop_peak", 0.85):
                category = "drop_or_climax"
                rule = self.config.cut_durations.get("drop_or_climax", {"beat_interval": 4, "min_sec": 1.20, "max_sec": 2.20})
            elif curr_energy >= self.config.energy_thresholds.get("high", 0.80):
                category = "high_energy"
                rule = self.config.cut_durations.get("high_energy", {"beat_interval": 4, "min_sec": 1.50, "max_sec": 2.80})
            elif curr_energy >= self.config.energy_thresholds.get("calm", 0.30):
                category = "medium_energy"
                rule = self.config.cut_durations.get("medium_energy", {"beat_interval": 8, "min_sec": 2.20, "max_sec": 4.20})
            else:
                category = "calm"
                rule = self.config.cut_durations.get("calm", {"beat_interval": 12, "min_sec": 3.50, "max_sec": 6.50})

            # Liczba beatów dla tego ujęcia
            beat_step = int(rule.get("beat_interval", 4))
            
            # Upewnij się, że krok beatów daje co najmniej min_cut_dur
            while curr_beat_idx + beat_step < total_beats:
                if (beat_times[curr_beat_idx + beat_step] - curr_time) >= min_cut_dur:
                    break
                beat_step += 1

            # Sprawdź czy w pobliżu nie ma nadchodzącego dropu (aby ujęcie kończyło się dokładnie na dropie, o ile zachowuje min_cut_dur)
            for d_idx in sorted(drop_indices):
                if curr_beat_idx < d_idx <= curr_beat_idx + beat_step:
                    drop_span_sec = beat_times[d_idx] - curr_time
                    if drop_span_sec >= min_cut_dur:
                        beat_step = d_idx - curr_beat_idx
                        break

            next_beat_idx = min(total_beats - 1, curr_beat_idx + beat_step)

            if next_beat_idx >= total_beats - 1 or curr_beat_idx == next_beat_idx:
                end_time = duration
                next_beat_idx = total_beats
            else:
                end_time = beat_times[next_beat_idx]

            slot_dur = end_time - curr_time

            slots.append({
                "slot_idx": len(slots),
                "start_sec": round(curr_time, 3),
                "end_sec": round(end_time, 3),
                "duration": round(slot_dur, 3),
                "category": category,
                "energy": round(float(curr_energy), 3),
                "is_drop": is_drop,
                "start_beat_idx": curr_beat_idx,
                "end_beat_idx": next_beat_idx
            })

            curr_beat_idx = next_beat_idx

        # Upewnij się, że pierwszy slot zaczyna się od 0.000
        if slots and slots[0]["start_sec"] > 0.0:
            slots[0]["duration"] = round(slots[0]["duration"] + slots[0]["start_sec"], 3)
            slots[0]["start_sec"] = 0.0

        # Upewnij się, że ostatni slot kończy się dokładnie na końcu utworu
        if slots and slots[-1]["end_sec"] < duration:
            slots[-1]["end_sec"] = round(duration, 3)
            slots[-1]["duration"] = round(duration - slots[-1]["start_sec"], 3)

        # Drugi przebieg (Post-processing): Bezwzględna eliminacja ujęć krótszych niż min_cut_dur
        merged_slots: List[Dict[str, Any]] = []
        for s in slots:
            if not merged_slots:
                merged_slots.append(s)
                continue
            if s["duration"] < min_cut_dur:
                # Dołącz zbyt krótki fragment do poprzedniego ujęcia
                merged_slots[-1]["end_sec"] = s["end_sec"]
                merged_slots[-1]["duration"] = round(merged_slots[-1]["end_sec"] - merged_slots[-1]["start_sec"], 3)
                merged_slots[-1]["end_beat_idx"] = s.get("end_beat_idx", merged_slots[-1]["end_beat_idx"])
                if s.get("is_drop"):
                    merged_slots[-1]["is_drop"] = True
                    merged_slots[-1]["category"] = "drop_or_climax"
            else:
                s["slot_idx"] = len(merged_slots)
                merged_slots.append(s)

        # Ponowna numeracja slotów
        for idx, s in enumerate(merged_slots):
            s["slot_idx"] = idx

        logger.info(f"Utworzono timeline z {len(merged_slots)} slotami cięć (min: {min_cut_dur}s) dla utworu o długości {duration:.2f} s.")
        return merged_slots

    def _build_fixed_slots(self, duration: float, interval: float) -> List[Dict[str, Any]]:
        slots = []
        t = 0.0
        while t < duration:
            end = min(duration, t + interval)
            slots.append({
                "slot_idx": len(slots),
                "start_sec": round(t, 3),
                "end_sec": round(end, 3),
                "duration": round(end - t, 3),
                "category": "medium_energy",
                "energy": 0.5,
                "is_drop": False
            })
            t = end
        return slots
