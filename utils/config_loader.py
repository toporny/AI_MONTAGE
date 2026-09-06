"""
Ładowanie i walidacja pliku konfiguracyjnego config.yaml.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import yaml

from utils.logger import logger


class Config:
    def __init__(self, raw_config: Dict[str, Any], base_dir: Path):
        self.raw = raw_config
        self.base_dir = base_dir
        
        # Paths
        paths_section = raw_config.get("paths", {})
        self.proxy_dir = self._resolve_path(paths_section.get("proxy_dir", "kopie_robocze_480p"))
        self.original_dir = self._resolve_path(paths_section.get("original_dir", "materialy_oryginalne"))
        self.music_dir = self._resolve_path(paths_section.get("music_dir", "sciezkadzwiekowa"))
        self.music_file = paths_section.get("music_file", "")
        
        self.cache_dir = self._resolve_path(paths_section.get("cache_dir", "analysis"))
        self.storyboard_dir = self._resolve_path(paths_section.get("storyboard_dir", "storyboard"))
        self.preview_dir = self._resolve_path(paths_section.get("preview_dir", "preview"))
        self.output_dir = self._resolve_path(paths_section.get("output_dir", "output"))

        # Statyczny obraz outro (opcjonalny)
        outro_raw = paths_section.get("outro_image", "")
        self.outro_image_path: Optional[Path] = Path(outro_raw) if outro_raw else None

        # Słowo kluczowe outro wideo — klip z tym słowem w nazwie będzie ostatnim ujęciem
        self.outro_video_keyword: str = str(raw_config.get("outro_video_keyword", "")).strip()

        # Lista wymuszonych ujęć: [{file: str, clip_time_start_sec: float|None, clip_time_end_sec: float|None}, ...]
        forced_raw = raw_config.get("forced_clips", []) or []
        self.forced_clips: List[Dict[str, Any]] = []
        for entry in forced_raw:
            if not isinstance(entry, dict) or "file" not in entry:
                continue

            # Odczyt parametrów punktu startowego i końcowego
            raw_start = entry.get("clip_time_start", entry.get("clip_time", None))
            raw_end = entry.get("clip_time_end", None)

            # Ścisła walidacja wzajemnego wykluczania
            if raw_start is not None and raw_end is not None:
                file_name = entry.get("file", "nieznany")
                sep = "=" * 70
                err_msg = (
                    f"\n{sep}\n"
                    f"  BŁĄD KRYTYCZNY KONFIGURACJI config.yaml (forced_clips):\n"
                    f"{sep}\n"
                    f"  Dla wymuszonego klipu '{file_name}' podano JEDNOCZEŚNIE:\n"
                    f"    - clip_time_start: {raw_start}\n"
                    f"    - clip_time_end:   {raw_end}\n\n"
                    f"  Parametry te wzajemnie się wykluczają!\n"
                    f"  Wybierz tylko jeden z nich:\n"
                    f"    * clip_time_start - jeśli chcesz, aby ujęcie ZACZYNAŁO się od podanego momentu.\n"
                    f"    * clip_time_end   - jeśli chcesz, aby ujęcie KOŃCZYŁO się dokładnie w podanym momencie.\n"
                    f"{sep}\n"
                )
                logger.error(err_msg)
                print(err_msg, file=sys.stderr)
                sys.exit(1)

            start_sec = self._parse_time_to_sec(raw_start)
            end_sec = self._parse_time_to_sec(raw_end)

            self.forced_clips.append({
                "file": str(entry["file"]).strip(),
                "clip_time_start_sec": start_sec,
                "clip_time_end_sec": end_sec,
                "clip_time_sec": start_sec  # kompatybilność wsteczna
            })

        # Video Analysis
        va = raw_config.get("video_analysis", {})
        self.sample_interval_sec: float = float(va.get("sample_interval_sec", 0.2))
        self.yolo_model: str = str(va.get("yolo_model", "yolov8n.pt"))
        self.device: str = str(va.get("device", "cuda"))
        self.batch_size: int = int(va.get("batch_size", 16))
        self.highlight_window_sizes: List[float] = [float(x) for x in va.get("highlight_window_sizes", [1.0, 1.5, 2.0, 3.0, 4.0])]
        self.scene_threshold: float = float(va.get("scene_threshold", 27.0))
        self.min_scene_duration_sec: float = float(va.get("min_scene_duration_sec", 0.8))

        # Scoring Weights
        sw = raw_config.get("scoring_weights", {})
        self.weight_sharpness: float = float(sw.get("sharpness", 0.20))
        self.weight_people: float = float(sw.get("people", 0.35))
        self.weight_motion: float = float(sw.get("motion", 0.25))
        self.weight_composition: float = float(sw.get("composition", 0.20))
        self.blur_penalty: float = float(sw.get("blur_penalty", 0.35))
        self.exposure_penalty: float = float(sw.get("exposure_penalty", 0.30))
        self.camera_shake_penalty: float = float(sw.get("camera_shake_penalty", 0.25))

        # Music Analysis
        ma = raw_config.get("music_analysis", {})
        self.onset_sensitivity: float = float(ma.get("onset_sensitivity", 0.5))
        self.beats_per_bar: int = int(ma.get("beats_per_bar", 4))
        self.energy_smoothing_sec: float = float(ma.get("energy_smoothing_sec", 0.5))
        self.energy_thresholds: Dict[str, float] = ma.get("energy_thresholds", {
            "calm": 0.30,
            "medium": 0.60,
            "high": 0.80,
            "drop_peak": 0.85
        })

        # Montage Rules
        mr = raw_config.get("montage_rules", {})
        self.min_cut_duration_sec: float = float(mr.get("min_cut_duration_sec", 1.20))
        self.cut_durations = mr.get("cut_durations", {})
        self.snap_to_beat: bool = bool(mr.get("snap_to_beat", True))
        self.snap_tolerance_sec: float = float(mr.get("snap_tolerance_sec", 0.15))
        self.reserve_top_highlights_ratio: float = float(mr.get("reserve_top_highlights_for_drops_ratio", 0.15))
        
        chrono = mr.get("chronology", {})
        self.chronology_enabled: bool = bool(chrono.get("enabled", True))
        self.chronology_weight: float = float(chrono.get("weight", 50.0))
        self.chronology_local_window: float = float(chrono.get("local_window_tolerance", 0.12))
        self.chronology_backward_penalty: float = float(chrono.get("backward_jump_penalty", 35.0))

        penalties = mr.get("penalties", {})
        self.consecutive_shot_type_penalty: float = float(penalties.get("consecutive_shot_type_penalty", 30.0))
        self.clip_reuse_penalty: float = float(penalties.get("clip_reuse_penalty", 55.0))
        self.max_source_clip_uses: int = int(penalties.get("max_source_clip_uses", 2))

        # Rendering
        rend = raw_config.get("rendering", {})
        self.preview_settings = rend.get("preview", {})
        self.final_settings = rend.get("final", {})

    def _parse_time_to_sec(self, time_val) -> Optional[float]:
        """Parsuje czas w formacie mm:ss, hh:mm:ss lub liczbę sekund → float lub None."""
        if time_val is None:
            return None
        s = str(time_val).strip()
        if not s:
            return None
        try:
            if ":" in s:
                parts = s.split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return float(s)
        except (ValueError, IndexError):
            logger.warning(f"Nieprawidłowy format czasu wymuszonego ujęcia: '{s}' (oczekiwane np. '1:30' lub '90')")
            return None

    def _resolve_path(self, path_str: str) -> Path:
        """Rozwiązuje ścieżkę jako absolutną lub względną do base_dir."""
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    def get_music_file_path(self) -> Optional[Path]:
        """Zwraca bezwzględną ścieżkę do pliku muzycznego. Wymaga podania konkretnego pliku w config.yaml."""
        if not self.music_file:
            logger.error("Nie zdefiniowano 'music_file' w pliku konfiguracyjnym config.yaml! Wymagane jest podanie konkretnego pliku MP3.")
            return None

        mf = Path(self.music_file)
        if mf.is_absolute() and mf.exists():
            return mf
        
        in_music_dir = self.music_dir / self.music_file
        if in_music_dir.exists():
            return in_music_dir
        
        # Sprawdź też w base_dir
        in_base = self.base_dir / self.music_file
        if in_base.exists():
            return in_base

        logger.error(f"Nie znaleziono wskazanego pliku muzycznego '{self.music_file}' w katalogu {self.music_dir}!")
        return None


def load_config(config_path: Optional[str] = None) -> Config:
    """Wczytuje plik konfiguracyjny config.yaml."""
    if config_path:
        cfg_file = Path(config_path)
    else:
        # Domyślnie szukaj w bieżącym katalogu lub w katalogu skryptu
        candidates = [
            Path("config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
            Path("AI_MONTAGE/config.yaml")
        ]
        cfg_file = next((c for c in candidates if c.exists()), Path("config.yaml"))

    if not cfg_file.exists():
        logger.error(f"Nie znaleziono pliku konfiguracyjnego: {cfg_file}")
        raise FileNotFoundError(f"Brak pliku konfiguracyjnego: {cfg_file}")

    with open(cfg_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    base_dir = cfg_file.parent.resolve()
    return Config(raw, base_dir)
