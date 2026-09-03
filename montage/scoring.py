"""
Moduł funkcji scoringowej dopasowującej fragmenty wideo do osi czasu muzyki.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from utils.config_loader import Config


class MontageScorer:
    def __init__(self, config: Config):
        self.config = config

    def calculate_match_score(
        self,
        highlight: Dict[str, Any],
        clip_meta: Dict[str, Any],
        music_slot: Dict[str, Any],
        recent_history: List[Dict[str, Any]],
        usage_counts: Dict[str, int],
        is_top_tier_highlight: bool = False
    ) -> Tuple[float, str]:
        """
        Oblicza łączny wynik dopasowania kandydata wideo do konkretnego slotu muzycznego
        oraz generuje uzasadnienie (reason).
        """
        base_score = float(highlight.get("score", 50.0))
        slot_category = music_slot.get("category", "medium_energy")
        slot_energy = float(music_slot.get("energy", 0.5))
        is_drop = music_slot.get("is_drop", False)

        motion_score = float(highlight.get("motion_score", 10.0))
        shot_type = highlight.get("shot_type", "wide")
        num_people = int(highlight.get("max_people", 0))
        source_file = clip_meta.get("file_name", "")

        reasons = []

        # 1. Dopasowanie energetyczne (Energy Alignment)
        energy_bonus = 0.0
        if is_drop or slot_category == "drop_or_climax":
            # DROP: wymagana wysoka dynamika i mocny wizualny akcent
            if motion_score > 35.0:
                energy_bonus += 20.0
                reasons.append("high_motion_for_drop")
            if is_top_tier_highlight:
                energy_bonus += 35.0
                reasons.append("top_highlight_reserved_for_drop")
            if num_people > 0:
                energy_bonus += 15.0
                reasons.append(f"{num_people}_people")
            if motion_score < 15.0:
                energy_bonus -= 30.0  # Kara za statyczny kadr na dropie

        elif slot_category == "high_energy":
            if motion_score > 25.0:
                energy_bonus += 15.0
                reasons.append("dynamic_motion")
            if num_people >= 2:
                energy_bonus += 12.0
                reasons.append("group_interaction")

        elif slot_category == "calm":
            # SPOKÓJ: preferujemy stabilne, szerokie plany, mały ruch
            if motion_score < 25.0:
                energy_bonus += 15.0
                reasons.append("calm_stable_shot")
            if shot_type in ["wide", "crowd"]:
                energy_bonus += 12.0
                reasons.append("wide_scenic")
            if motion_score > 55.0:
                energy_bonus -= 20.0  # Zbyt szarpany/szybki kadr na spokojną część

        else: # medium_energy
            if shot_type in ["medium", "close_up"]:
                energy_bonus += 10.0
                reasons.append(f"{shot_type}_focus")
            if num_people > 0:
                energy_bonus += 8.0

        # 2. Kary za brak różnorodności (Diversity & Repetition Penalties)
        penalty = 0.0

        # A. Kara za ponowne użycie tego samego pliku źródłowego
        used_count = usage_counts.get(source_file, 0)
        if used_count > 0:
            if used_count >= self.config.max_source_clip_uses:
                penalty += 999.0  # Wyklucz klip jeśli osiągnął limit użyć
            else:
                penalty += self.config.clip_reuse_penalty * used_count

        # B. Kara jeśli klip pochodzi z tego samego pliku co poprzednie 2 ujęcia
        if recent_history:
            last_clip = recent_history[-1]
            if last_clip.get("source_file") == source_file:
                penalty += 300.0  # Zdecydowanie nie dajemy tego samego pliku pod rząd

            if len(recent_history) >= 2 and recent_history[-2].get("source_file") == source_file:
                penalty += 100.0

            # C. Kara za powtórzenie tego samego typu planu pod rząd (np. Close-up -> Close-up)
            if last_clip.get("shot_type") == shot_type:
                penalty += self.config.consecutive_shot_type_penalty
                
            # D. Kara za powtórzenie 3 takich samych planów z rzędu
            if len(recent_history) >= 2 and recent_history[-2].get("shot_type") == shot_type and last_clip.get("shot_type") == shot_type:
                penalty += 60.0

        # 3. Kary chronologiczne (Chronological Story Arc)
        if getattr(self.config, "chronology_enabled", True):
            cand_progress = float(clip_meta.get("event_progress", 0.5))
            music_progress = float(music_slot.get("music_progress", 0.5))
            cand_event_time = float(clip_meta.get("event_time", 0.0))

            diff = abs(cand_progress - music_progress)
            tol = getattr(self.config, "chronology_local_window", 0.10)
            
            # Silna kara za ujęcie z zupełnie innej części imprezy (np. gala wieczorna na początku filmu)
            if diff > tol:
                excess = (diff - tol) / max(0.01, 1.0 - tol)
                # Kwadratowa kara sprawia, że drobne przesunięcia (w ramach tej samej pory dnia) są dopuszczalne,
                # a mieszanie wieczornej gali z porannymi mowami jest całkowicie wykluczone
                chrono_penalty = (excess ** 2) * 200.0
                penalty += chrono_penalty
                reasons.append(f"chrono_drift_{int(diff*100)}pct")

            # Kara za cofanie się w czasie względem ostatnio wybranego ujęcia
            if recent_history and cand_event_time > 0:
                last_event_time = float(recent_history[-1].get("event_time", 0.0))
                if last_event_time > 0 and cand_event_time < (last_event_time - 900): # > 15 minut wstecz
                    penalty += getattr(self.config, "chronology_backward_penalty", 45.0)

        # 4. Ostateczny wynik dopasowania
        final_match_score = base_score + energy_bonus - penalty

        if not reasons:
            reasons.append(f"{shot_type} + score_{int(base_score)}")

        reason_str = " + ".join(reasons)
        return float(final_match_score), reason_str
