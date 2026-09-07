"""
Główny orkiestrator analizy wideo. Przetwarza wszystkie pliki proxy,
zarządza pamięcią podręczną JSON (cache), obsługuje błędy i prezentuje postęp.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import cv2
import numpy as np
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from analyzer.highlight_detector import HighlightDetector
from analyzer.motion_analyzer import MotionAnalyzer
from analyzer.people_detector import PeopleDetector
from analyzer.quality_analyzer import QualityAnalyzer
from analyzer.scene_detector import SceneDetector
from utils.config_loader import Config
from utils.helpers import safe_load_json, safe_save_json
from utils.logger import console, logger


class VideoAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        self.scene_detector = SceneDetector(
            threshold=config.scene_threshold,
            min_scene_duration_sec=config.min_scene_duration_sec
        )
        self.quality_analyzer = QualityAnalyzer()
        self.people_detector = PeopleDetector(
            model_name=config.yolo_model,
            device=config.device
        )
        self.motion_analyzer = MotionAnalyzer()
        self.highlight_detector = HighlightDetector(config)

        self.cache_dir = config.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.errors_log_path = self.cache_dir / "errors.log"

    def analyze_all_videos(self, force_recompute: bool = False) -> List[Dict[str, Any]]:
        """
        Skanuje katalog proxy i analizuje wszystkie pliki wideo.
        Wznawia pracę od miejsca przerwania dzięki plikom cache JSON.
        """
        proxy_dir = self.config.proxy_dir
        proxy_dir.mkdir(parents=True, exist_ok=True)

        # Wyszukaj wszystkie unikalne pliki wideo (obsługa Windows bez duplikatów)
        seen_paths = set()
        video_files = []
        for p in proxy_dir.iterdir():
            if p.is_file() and p.suffix.lower() in [".mp4", ".mov", ".mkv", ".avi"]:
                p_resolved = p.resolve()
                if p_resolved not in seen_paths:
                    seen_paths.add(p_resolved)
                    video_files.append(p)
        video_files.sort(key=lambda x: x.name)
        total_files = len(video_files)

        if total_files == 0:
            logger.warning(f"Brak plików wideo w katalogu: {proxy_dir}")
            return []

        console.print(f"\n[bold green]Rozpoczynam analizę {total_files} plików wideo (Proxy 480p)...[/bold green]")
        console.print(f"Katalog proxy: [cyan]{proxy_dir}[/cyan]")
        console.print(f"Katalog cache: [cyan]{self.cache_dir}[/cyan]\n")

        results: List[Dict[str, Any]] = []
        errors_count = 0
        cached_count = 0
        analyzed_count = 0

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console
        )

        with progress:
            task_id = progress.add_task("[yellow]Analiza klipów wideo...", total=total_files)

            for idx, video_path in enumerate(video_files, 1):
                cache_file = self.cache_dir / f"{video_path.stem}.json"
                progress.update(task_id, description=f"[{idx}/{total_files}] {video_path.name[:30]}")

                # 1. Sprawdź cache
                if not force_recompute and cache_file.exists():
                    cached_data = safe_load_json(cache_file)
                    if cached_data and "candidate_highlights" in cached_data:
                        results.append(cached_data)
                        cached_count += 1
                        progress.advance(task_id)
                        continue

                # 2. Wykonaj pełną analizę pliku (weryfikuje sprzęt przy pierwszym ujęciu)
                self.people_detector.ensure_model_loaded()
                try:
                    analysis_result = self.analyze_single_video(video_path)
                    if analysis_result:
                        safe_save_json(analysis_result, cache_file)
                        results.append(analysis_result)
                        analyzed_count += 1
                    else:
                        errors_count += 1
                        self._log_error(video_path.name, "Analiza zwróciła pusty wynik.")
                except Exception as e:
                    errors_count += 1
                    logger.error(f"Błąd podczas analizy {video_path.name}: {e}")
                    self._log_error(video_path.name, str(e))

                progress.advance(task_id)

        console.print("\n[bold green]Podsumowanie analizy wideo:[/bold green]")
        console.print(f"  • Wszystkich plików: [bold]{total_files}[/bold]")
        console.print(f"  • Nowo przeanalizowanych: [bold cyan]{analyzed_count}[/bold cyan]")
        console.print(f"  • Wczytanych z cache: [bold green]{cached_count}[/bold green]")
        if errors_count > 0:
            console.print(f"  • Błędów: [bold red]{errors_count}[/bold red] (szczegóły w {self.errors_log_path})")
        else:
            console.print("  • Błędów: [green]0 (Wszystko OK)[/green]")

        return results

    def analyze_single_video(self, video_path: Path) -> Optional[Dict[str, Any]]:
        """
        Analizuje pojedynczy plik wideo pod kątem scen, jakości, osób, ruchu i wyznacza highlighty.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"Nie można otworzyć pliku wideo: {video_path}")
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = float(total_frames / fps) if fps > 0 else 0.0

        if duration < 0.5:
            logger.warning(f"Klip {video_path.name} jest zbyt krótki (<0.5s). Pomijam.")
            cap.release()
            return None

        # 1. Detekcja scen
        scenes = self.scene_detector.detect_scenes(video_path, fps, duration)

        # 2. Próbkowanie klatek
        sample_step_frames = max(1, int(self.config.sample_interval_sec * fps))
        
        sampled_frames: List[np.ndarray] = []
        frame_timestamps: List[float] = []
        frame_indices: List[int] = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % sample_step_frames == 0:
                sampled_frames.append(frame)
                frame_timestamps.append(round(frame_idx / fps, 3))
                frame_indices.append(frame_idx)
            frame_idx += 1

        cap.release()

        if not sampled_frames:
            return None

        # 3. Analiza jakości technicznej każdej klatki
        quality_results = [self.quality_analyzer.analyze_frame(f) for f in sampled_frames]

        # 4. Detekcja ludzi (YOLO - batching dla maksymalnej wydajności GPU)
        batch_size = self.config.batch_size
        people_results: List[Dict[str, Any]] = []
        for i in range(0, len(sampled_frames), batch_size):
            batch = sampled_frames[i:i + batch_size]
            people_results.extend(self.people_detector.detect_batch(batch))

        # 5. Analiza ruchu i stabilności między klatkami
        motion_results: List[Dict[str, Any]] = []
        stability_scores: List[float] = []

        for i in range(len(sampled_frames)):
            if i == 0:
                motion_results.append({
                    "mean_motion_mag": 0.0,
                    "p95_motion_mag": 0.0,
                    "coherence": 1.0,
                    "motion_score": 10.0,
                    "motion_category": "static"
                })
                stability_scores.append(85.0)
            else:
                prev_f = sampled_frames[i - 1]
                curr_f = sampled_frames[i]
                m_info = self.motion_analyzer.compute_motion(prev_f, curr_f)
                motion_results.append(m_info)

                prev_gray = cv2.cvtColor(prev_f, cv2.COLOR_BGR2GRAY)
                curr_gray = cv2.cvtColor(curr_f, cv2.COLOR_BGR2GRAY)
                stab = self.quality_analyzer.compute_stability_score(prev_gray, curr_gray)
                stability_scores.append(stab)

        # 6. Złożenie danych per-klatka
        frame_data: List[Dict[str, Any]] = []
        for i in range(len(sampled_frames)):
            fdata = {
                "timestamp": frame_timestamps[i],
                "frame_idx": frame_indices[i],
                "stability_score": stability_scores[i],
                **quality_results[i],
                **people_results[i],
                **motion_results[i]
            }
            frame_data.append(fdata)

        # 7. Wyodrębnienie najlepszych fragmentów (highlightów)
        highlights = self.highlight_detector.extract_highlights(frame_data, scenes, duration)

        # 8. Podsumowanie całego klipu
        avg_sharpness = float(np.mean([q["sharpness"] for q in quality_results])) if quality_results else 50.0
        avg_motion = float(np.mean([m["motion_score"] for m in motion_results])) if motion_results else 10.0
        max_people = max([p["num_people"] for p in people_results]) if people_results else 0
        overall_score = max([h["score"] for h in highlights]) if highlights else 40.0

        # Dominujący typ kadru w klipie
        shot_types = [p["shot_type"] for p in people_results if p["shot_type"] != "no_people"]
        dominant_shot = max(set(shot_types), key=shot_types.count) if shot_types else "wide"

        return {
            "file_name": video_path.name,
            "stem": video_path.stem,
            "proxy_path": str(video_path.resolve()),
            "duration": round(duration, 3),
            "fps": round(fps, 2),
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "scenes": scenes,
            "candidate_highlights": highlights,
            "overall_score": round(overall_score, 2),
            "dominant_shot_type": dominant_shot,
            "max_people": max_people,
            "avg_motion": round(avg_motion, 2),
            "avg_sharpness": round(avg_sharpness, 2),
            "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def _log_error(self, filename: str, reason: str):
        """Zapisuje informację o błędzie do pliku errors.log."""
        try:
            with open(self.errors_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {filename} | Reason: {reason}\n")
        except Exception:
            pass
