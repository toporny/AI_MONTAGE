"""
Moduł eksportu i walidacji storyboardu do formatu JSON oraz czytelnego pliku TXT.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from montage.openshot_exporter import OpenShotExporter
from utils.config_loader import Config
from utils.helpers import format_timestamp, parse_timestamp, safe_load_json, safe_save_json
from utils.logger import console, logger


class StoryboardManager:
    def __init__(self, config: Config):
        self.config = config
        self.storyboard_dir = config.storyboard_dir
        self.storyboard_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.storyboard_dir / "storyboard.json"
        self.txt_path = self.storyboard_dir / "storyboard.txt"
        self.osp_path = self.storyboard_dir / "montage_openshot.osp"
        self.openshot_exporter = OpenShotExporter(config)

    def export_storyboard(
        self,
        cuts: List[Dict[str, Any]],
        music_meta: Dict[str, Any]
    ) -> Tuple[Path, Path]:
        """
        Zapisuje listę cięć do storyboard.json oraz czytelnego storyboard.txt.
        """
        storyboard_data = {
            "music_track": music_meta.get("file_name", ""),
            "total_duration": music_meta.get("duration", 0.0),
            "bpm": music_meta.get("bpm", 120.0),
            "total_cuts": len(cuts),
            "cuts": cuts
        }

        # 1. Zapis JSON
        safe_save_json(storyboard_data, self.json_path)

        # 2. Zapis czytelnego formatu TXT
        lines = []
        lines.append("================================================================================")
        lines.append(f" STORYBOARD AUTOMATYCZNEGO MONTAŻU AI (Liczba ujęć: {len(cuts)})")
        lines.append(f" Muzyka: {music_meta.get('file_name', '')} | Długość: {format_timestamp(music_meta.get('duration', 0.0))} | BPM: {music_meta.get('bpm', 120.0):.1f}")
        lines.append("================================================================================\n")

        for idx, cut in enumerate(cuts, 1):
            t_start = format_timestamp(cut["timeline_start"])
            t_end = format_timestamp(cut["timeline_end"])
            s_start = format_timestamp(cut["source_start"])
            s_end = format_timestamp(cut["source_end"])
            ev_prog = cut.get("event_progress", 0.0)
            
            lines.append(f"[{idx:03d}] {t_start} – {t_end}  (czas: {cut['duration']:.2f}s, chronologia: {int(ev_prog*100)}%)")
            lines.append(f"source:       {cut['source_file']}")
            lines.append(f"source_start: {s_start}")
            lines.append(f"source_end:   {s_end}")
            lines.append(f"score:        {cut['score']}")
            lines.append(f"shot_type:    {cut['shot_type']} | people: {cut['max_people']}")
            lines.append(f"reason:       {cut['reason']}")
            lines.append(f"music_energy: {cut['music_energy']}{' [DROP/CLIMAX]' if cut.get('is_drop') else ''}")
            lines.append("")

        with open(self.txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        console.print(f"\n[bold green]Wygenerowano Storyboard:[/bold green]")
        console.print(f"  • JSON: [cyan]{self.json_path.resolve()}[/cyan]")
        console.print(f"  • TXT:  [cyan]{self.txt_path.resolve()}[/cyan]")

        # 3. Zapis projektów OpenShot Video Editor (.osp: 4K oraz 480p)
        try:
            self.openshot_exporter.export_both_projects(storyboard_data)
        except Exception as e:
            logger.error(f"Błąd podczas eksportu projektów OpenShot: {e}")

        console.print()

        return self.json_path, self.txt_path

    def load_storyboard(self) -> Optional[Dict[str, Any]]:
        """Wczytuje istniejący storyboard.json."""
        if not self.json_path.exists():
            logger.error(f"Nie znaleziono pliku storyboardu: {self.json_path}")
            return None
        return safe_load_json(self.json_path)
