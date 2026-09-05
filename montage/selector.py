"""
Główny algorytm decyzyjny montażysty (Montage Selector).
Wybiera optymalne ujęcia, synchronizuje je z muzyką, rezerwuje najlepsze momenty na dropy
i gwarantuje różnorodność planów filmowych.

Wymuszone ujęcia: lista forced_clips w config.yaml pozwala użytkownikowi wskazać
konkretne klipy które ZAWSZE znajdą się w montażu, z opcjonalnym żądanym czasem
pojawienia się w gotowym filmie.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from montage.scoring import MontageScorer
from utils.config_loader import Config
from utils.helpers import extract_event_timestamp
from utils.logger import console, logger


class MontageSelector:
    def __init__(self, config: Config):
        self.config = config
        self.scorer = MontageScorer(config)

    def _normalize_stem(self, filename: str) -> str:
        """Normalizuje nazwę pliku do czystego stemu (bez rozszerzenia i sufiksu _480pNN)."""
        stem = Path(filename).stem
        return re.sub(r"_480p\d+$", "", stem, flags=re.IGNORECASE).lower()

    def _find_forced_clips(
        self,
        sorted_videos: List[Dict[str, Any]],
        timeline_slots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Wczytuje listę forced_clips z config i dopasowuje do analiz wideo.
        Dopasowanie jest ŚCISŁE (exact match na nazwie pliku).
        Jeśli któregoś pliku nie ma — ABORT z listą brakujących.
        Zwraca listę: [{video: Dict, time_sec: float|None, pattern: str}, ...]
        """
        forced_configs = getattr(self.config, "forced_clips", [])
        if not forced_configs:
            return []

        # Zbuduj słownik: znormalizowany stem → analiza wideo
        video_by_stem: Dict[str, Dict[str, Any]] = {}
        for v in sorted_videos:
            norm = self._normalize_stem(v.get("file_name", ""))
            video_by_stem[norm] = v

        result: List[Dict[str, Any]] = []
        missing: List[str] = []

        for fc in forced_configs:
            raw_name = fc["file"]
            # Znormalizuj to co wpisał użytkownik (akceptuje: z/bez _480p15, z/bez .mp4)
            norm_pattern = self._normalize_stem(raw_name)

            if norm_pattern not in video_by_stem:
                missing.append(raw_name)
                continue

            matched_v = video_by_stem[norm_pattern]
            clip_time_sec = fc.get("clip_time_sec")

            time_info_parts = ["auto-chronologia"]
            if clip_time_sec is not None:
                time_info_parts.append(f"od klatki: {int(clip_time_sec//60)}:{int(clip_time_sec%60):02d}")

            time_info = " (" + ", ".join(time_info_parts) + ")"
            logger.info(f"Wymuszone ujęcie: '{raw_name}'{time_info} → {matched_v.get('file_name')}")

            result.append({
                "video": matched_v,
                "clip_time_sec": clip_time_sec,
                "pattern": raw_name
            })

        # ABORT jeśli któregoś pliku nie ma
        if missing:
            console.print("\n[bold red]═══════════════════════════════════════════════════════[/bold red]")
            console.print("[bold red]  BŁĄD KRYTYCZNY — wymuszone ujęcia nie zostały znalezione:[/bold red]")
            console.print("[bold red]═══════════════════════════════════════════════════════[/bold red]")
            for m in missing:
                console.print(f"  [red]✗  '{m}'[/red]")
            console.print()
            console.print("[yellow]  Sprawdź nazwy w config.yaml → forced_clips[/yellow]")
            console.print("[yellow]  Wpisz dokładną nazwę pliku (bez rozszerzenia i bez _480p15)[/yellow]")
            console.print("[yellow]  Dostępne proxy znajdziesz w katalogu kopie_robocze_480p/[/yellow]")
            console.print("[bold red]═══════════════════════════════════════════════════════[/bold red]\n")
            raise SystemExit(1)

        return result

    def select_montage(
        self,
        timeline_slots: List[Dict[str, Any]],
        video_analyses: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Główny algorytm wyboru ujęć do slotów na osi czasu z uwzględnieniem chronologii wydarzeń.
        Wymuszone ujęcia z config.forced_clips mają gwarantowane miejsce w montażu.
        """
        if not video_analyses or not timeline_slots:
            logger.error("Brak danych analizy wideo lub slotów timeline!")
            return []

        console.print("\n[bold green]Rozpoczynam inteligentny dobór ujęć montażowych (AI Editor)...[/bold green]")

        # 1. Wylicz daty i ciągłą oś czasu dla każdego pliku wideo
        sorted_videos = sorted(video_analyses, key=lambda v: extract_event_timestamp(v.get("file_name", "")))
        total_unique_vids = len(sorted_videos)

        for rank_idx, v in enumerate(sorted_videos):
            v["file_idx"] = rank_idx
            v["event_time"] = extract_event_timestamp(v.get("file_name", ""))
            v["event_progress"] = rank_idx / max(1, total_unique_vids - 1)

        # Wylicz pozycję na osi czasu muzyki dla każdego slotu
        music_total_dur = timeline_slots[-1]["end_sec"] if timeline_slots else 1.0
        for s_idx, slot in enumerate(timeline_slots):
            slot["music_progress"] = slot["start_sec"] / max(1.0, music_total_dur)

        # 2. Przygotuj pulę wszystkich dostępnych kandydatów (highlightów)
        all_candidates: List[Dict[str, Any]] = []
        for v in sorted_videos:
            src_file = v["file_name"]
            src_dur = v["duration"]
            proxy_p = v.get("proxy_path", "")

            for h in v.get("candidate_highlights", []):
                all_candidates.append({
                    "source_file": src_file,
                    "proxy_path": proxy_p,
                    "source_duration": src_dur,
                    "highlight": h,
                    "clip_meta": v
                })

        if not all_candidates:
            logger.error("Nie znaleziono żadnych kandydatów highlightów w analizie wideo!")
            return []

        # 3. Rezerwacja ostatniego slotu — statyczny obraz outro lub klip wideo
        assigned_cuts: List[Optional[Dict[str, Any]]] = [None] * len(timeline_slots)
        used_source_counts: Dict[str, int] = {}
        used_highlight_keys: Set[str] = set()
        recent_history: List[Dict[str, Any]] = []

        last_slot = timeline_slots[-1]
        outro_image = getattr(self.config, "outro_image_path", None)

        if outro_image and outro_image.exists():
            duration = round(last_slot["end_sec"] - last_slot["start_sec"], 3)
            cut_outro = {
                "cut_idx": last_slot["slot_idx"],
                "timeline_start": last_slot["start_sec"],
                "timeline_end": last_slot["end_sec"],
                "duration": duration,
                "source_file": outro_image.name,
                "proxy_path": str(outro_image),
                "source_start": 0.0,
                "source_end": duration,
                "source_clip_duration": duration,
                "source_type": "image",
                "image_path": str(outro_image),
                "score": 100.0,
                "highlight_base_score": 100.0,
                "shot_type": "wide",
                "max_people": 0,
                "motion_score": 0.0,
                "event_time": 9999999.0,
                "event_progress": 1.0,
                "reason": "Outro: statyczny obraz końcowy",
                "music_energy": "calm",
                "is_drop": False
            }
            assigned_cuts[-1] = cut_outro
            logger.info(f"Ostatnie ujęcie: statyczny obraz outro → {outro_image.name}")
        else:
            outro_kw = getattr(self.config, "outro_video_keyword", "")
            if outro_kw:
                outro_cands = [c for c in all_candidates if outro_kw.lower() in c["source_file"].lower()]
            else:
                outro_cands = []
            if outro_cands:
                best_outro = max(outro_cands, key=lambda x: x["highlight"]["score"])
                cut_outro = self._create_cut_entry(last_slot, best_outro, best_outro["highlight"]["score"], f"Outro: {outro_kw}")
                assigned_cuts[-1] = cut_outro
                used_highlight_keys.add(f"{best_outro['source_file']}_{best_outro['highlight']['start_sec']}")
                used_source_counts[best_outro["source_file"]] = 1

        has_outro = assigned_cuts[-1] is not None

        # 4. Wymuszone ujęcia z listy forced_clips (GWARANCJA UŻYCIA)
        num_slots_total = len(timeline_slots)
        outro_offset = 1 if has_outro else 0
        num_main_slots = num_slots_total - outro_offset
        num_vids = len(sorted_videos)

        forced_clips_list = self._find_forced_clips(sorted_videos, timeline_slots)
        # s_idx -> (best_forced_cand, pattern, clip_time_sec)
        forced_slot_reservations: Dict[int, Tuple[Dict[str, Any], str, Optional[float]]] = {}

        for fc in forced_clips_list:
            matched_v = fc["video"]
            clip_time_sec = fc.get("clip_time_sec")
            pattern = fc["pattern"]

            # Wyznacz docelowy slot chronologicznie
            file_idx = matched_v["file_idx"]
            target_s_idx = int(file_idx * (num_main_slots - 1) / max(1, num_vids - 1))
            target_s_idx = max(0, min(num_main_slots - 1, target_s_idx))

            # Najlepszy highlight z tego klipu (lub dopasowany do clip_time)
            forced_cands = [c for c in all_candidates if c["clip_meta"]["file_idx"] == matched_v["file_idx"]]
            if not forced_cands:
                logger.warning(f"Wymuszone ujęcie '{pattern}' — brak danych w analizie (uruchom ponownie 'analyze')")
                continue

            if clip_time_sec is not None:
                # Szukaj highlightu najbliższego żądanej chwili czasowej w klipie
                best_forced_cand = min(
                    forced_cands,
                    key=lambda x: abs(x["highlight"]["start_sec"] - clip_time_sec)
                )
            else:
                best_forced_cand = max(forced_cands, key=lambda x: x["highlight"]["score"])

            # Unikaj kolizji ze slotami już zarezerwowanymi — szukaj wolnego slotu
            reserved_slot = target_s_idx
            for offset in range(num_main_slots):
                candidate_slot = (target_s_idx + offset) % num_main_slots
                if candidate_slot not in forced_slot_reservations and assigned_cuts[candidate_slot] is None:
                    reserved_slot = candidate_slot
                    break

            forced_slot_reservations[reserved_slot] = (best_forced_cand, pattern, clip_time_sec)
            slot_time = timeline_slots[reserved_slot]["start_sec"]
            desc_parts = [f"slot={slot_time:.1f}s"]
            if clip_time_sec is not None:
                desc_parts.append(f"od_klatki={clip_time_sec:.1f}s")
            logger.info(f"  → slot {reserved_slot} ({', '.join(desc_parts)})")

        # Wypełnij zarezerwowane sloty wymuszonymi ujęciami
        for s_idx, (forced_cand, pattern, clip_time_sec) in forced_slot_reservations.items():
            slot = timeline_slots[s_idx]
            reason_parts = [f"forced:{pattern}"]
            if clip_time_sec is not None:
                reason_parts.append(f"clip@{clip_time_sec:.0f}s")
            reason = " ".join(reason_parts)

            cut = self._create_cut_entry(
                slot=slot,
                cand=forced_cand,
                match_score=forced_cand["highlight"]["score"] + 50.0,
                reason=reason,
                clip_start_override=clip_time_sec
            )
            assigned_cuts[s_idx] = cut
            key = f"{forced_cand['source_file']}_{cut['source_start']}"
            used_highlight_keys.add(key)
            src = forced_cand["source_file"]
            used_source_counts[src] = used_source_counts.get(src, 0) + 1

        if forced_slot_reservations:
            console.print(f"[bold yellow]  ★ Zarezerwowano {len(forced_slot_reservations)} slot(ów) dla wymuszonych ujęć[/bold yellow]")

        # 5. Sekwencyjne dopasowanie ujęć w ściśle progresywnym oknie chronologicznym
        last_vid_idx = 0

        for s_idx in range(num_slots_total - outro_offset):
            # Pomiń sloty już wypełnione (wymuszone lub outro)
            if assigned_cuts[s_idx] is not None:
                existing = assigned_cuts[s_idx]
                for v in sorted_videos:
                    if v.get("file_name") == existing.get("source_file"):
                        last_vid_idx = max(last_vid_idx, v["file_idx"])
                        break
                continue

            slot = timeline_slots[s_idx]
            target_idx = int(s_idx * (num_vids - 1) / max(1, num_slots_total - 1))
            slot_copy = dict(slot)

            best_cand = None
            best_score = -99999.0
            best_reason = ""

            # Przeszukaj w rozszerzających się oknach z kontrolowanym wyprzedzeniem
            for w in [2, 4, 8, 15, 30, num_vids]:
                min_idx = max(last_vid_idx, target_idx - w)
                max_idx = min(num_vids - 1, target_idx + max(2, w // 2))

                cand_subset = [c for c in all_candidates if min_idx <= c["clip_meta"]["file_idx"] <= max_idx]
                for cand in cand_subset:
                    # Pomiń klip zarezerwowany jako outro wideo
                    outro_kw = getattr(self.config, "outro_video_keyword", "")
                    if outro_kw and outro_kw.lower() in cand["source_file"].lower():
                        continue
                    key = f"{cand['source_file']}_{cand['highlight']['start_sec']}"
                    if key in used_highlight_keys:
                        continue
                    src = cand["source_file"]
                    if used_source_counts.get(src, 0) >= self.config.max_source_clip_uses:
                        continue

                    score, reason = self.scorer.calculate_match_score(
                        cand["highlight"],
                        cand["clip_meta"],
                        slot_copy,
                        recent_history=recent_history,
                        usage_counts=used_source_counts,
                        is_top_tier_highlight=False
                    )

                    idx_diff = abs(cand["clip_meta"]["file_idx"] - target_idx)
                    score -= idx_diff * 0.8

                    if score > best_score:
                        best_score = score
                        best_cand = cand
                        best_reason = reason

                if best_cand is not None:
                    break

            if best_cand is None:
                for cand in all_candidates:
                    outro_kw = getattr(self.config, "outro_video_keyword", "")
                    if outro_kw and outro_kw.lower() in cand["source_file"].lower():
                        continue
                    key = f"{cand['source_file']}_{cand['highlight']['start_sec']}"
                    if key in used_highlight_keys:
                        continue
                    src = cand["source_file"]
                    if used_source_counts.get(src, 0) >= self.config.max_source_clip_uses:
                        continue
                    if cand["clip_meta"]["file_idx"] >= last_vid_idx:
                        best_cand = cand
                        best_score = cand["highlight"]["score"]
                        best_reason = "chrono_fallback_forward"
                        break

            if best_cand is None:
                best_cand = all_candidates[0]
                best_score = 50.0
                best_reason = "chrono_fallback_any"

            cut = self._create_cut_entry(slot, best_cand, best_score, best_reason)
            assigned_cuts[s_idx] = cut

            key = f"{best_cand['source_file']}_{best_cand['highlight']['start_sec']}"
            used_highlight_keys.add(key)
            src = best_cand["source_file"]
            used_source_counts[src] = used_source_counts.get(src, 0) + 1
            last_vid_idx = max(last_vid_idx, best_cand["clip_meta"]["file_idx"])

            recent_history.append(cut)
            if len(recent_history) > 4:
                recent_history.pop(0)

        # 6. Ostateczna lista cięć
        final_cuts = [c for c in assigned_cuts if c is not None]

        forced_used = sum(1 for c in final_cuts if c.get("reason", "").startswith("forced:"))
        logger.info(f"Pomyślnie zmontowano {len(final_cuts)} ujęć w ścisłym porządku chronologicznym.")
        if forced_used:
            logger.info(f"  ★ W tym {forced_used} wymuszonych ujęć z listy forced_clips.")

        return final_cuts

    def _create_cut_entry(
        self,
        slot: Dict[str, Any],
        cand: Dict[str, Any],
        match_score: float,
        reason: str,
        clip_start_override: Optional[float] = None
    ) -> Dict[str, Any]:
        """Tworzy ustrukturyzowany rekord ujęcia na osi czasu."""
        slot_duration = slot["duration"]
        h = cand["highlight"]
        h_start = h["start_sec"]
        h_dur = h["duration"]
        src_total_dur = cand["source_duration"]

        if clip_start_override is not None:
            # Użytkownik podał konkretną chwilę czasową wewnątrz klipu
            src_start = max(0.0, min(src_total_dur, float(clip_start_override)))
            src_end = min(src_total_dur, src_start + slot_duration)
            # Jeśli klip jest za krótki od tego miejsca do końca, cofnij początek na ile to możliwe
            if (src_end - src_start) < slot_duration and src_start > 0.0:
                src_start = max(0.0, src_end - slot_duration)
        elif h_dur >= slot_duration:
            src_start = h_start
            src_end = min(src_total_dur, h_start + slot_duration)
        else:
            diff = slot_duration - h_dur
            src_start = max(0.0, h_start - (diff / 2.0))
            src_end = min(src_total_dur, src_start + slot_duration)
            if (src_end - src_start) < slot_duration and src_start > 0.0:
                src_start = max(0.0, src_end - slot_duration)

        return {
            "cut_idx": slot["slot_idx"],
            "timeline_start": slot["start_sec"],
            "timeline_end": slot["end_sec"],
            "duration": round(slot["end_sec"] - slot["start_sec"], 3),
            "source_file": cand["source_file"],
            "proxy_path": cand["proxy_path"],
            "source_start": round(src_start, 3),
            "source_end": round(src_end, 3),
            "source_clip_duration": round(src_end - src_start, 3),
            "score": round(match_score, 1),
            "highlight_base_score": round(h["score"], 1),
            "shot_type": h.get("shot_type", "wide"),
            "max_people": h.get("max_people", 0),
            "motion_score": h.get("motion_score", 0.0),
            "event_time": cand["clip_meta"].get("event_time", 0.0),
            "event_progress": round(float(cand["clip_meta"].get("event_progress", 0.0)), 3),
            "reason": reason,
            "music_energy": slot.get("category", "medium_energy"),
            "is_drop": slot.get("is_drop", False)
        }
