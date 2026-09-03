"""
Moduł generowania szybkiego podglądu (Preview 480p/15 fps) z plików proxy z nałożonym podkładem muzycznym.
"""

from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional

from utils.config_loader import Config
from utils.helpers import check_ffmpeg_nvenc, format_timestamp, run_command, safe_load_json
from utils.logger import console, logger


class PreviewRenderer:
    def __init__(self, config: Config):
        self.config = config
        self.preview_dir = config.preview_dir
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.output_file = self.preview_dir / "preview_montage_480p.mp4"

    def render_preview(self, storyboard_data: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        """
        Renderuje szybki podgląd 480p na podstawie storyboardu i plików proxy.
        """
        if storyboard_data is None:
            sb_path = self.config.storyboard_dir / "storyboard.json"
            storyboard_data = safe_load_json(sb_path)

        if not storyboard_data or "cuts" not in storyboard_data:
            logger.error("Brak danych storyboardu do wyrenderowania preview!")
            return None

        cuts = storyboard_data["cuts"]
        music_file = self.config.get_music_file_path()
        if not music_file or not music_file.exists():
            logger.error(f"Nie znaleziono pliku muzycznego: {music_file}")
            return None

        console.print(f"\n[bold green]Rozpoczynam renderowanie Preview 480p...[/bold green]")
        console.print(f"Liczba ujęć: [bold cyan]{len(cuts)}[/bold cyan]")
        console.print(f"Podkład audio: [bold cyan]{music_file.name}[/bold cyan]")
        console.print(f"Plik wyjściowy: [bold yellow]{self.output_file.resolve()}[/bold yellow]\n")

        start_time = time.time()

        # 1. Przygotuj listę concat demuxera dla FFmpeg
        concat_list_file = self.preview_dir / "concat_preview.txt"
        temp_segments_dir = self.preview_dir / "temp_segments"
        temp_segments_dir.mkdir(parents=True, exist_ok=True)

        has_nvenc, nvenc_encoder = check_ffmpeg_nvenc()
        v_encoder = "h264_nvenc" if has_nvenc else "libx264"
        prev_cfg = getattr(self.config, "rendering_preview", {}) or {}
        cq = str(prev_cfg.get("cq", "34"))
        preset = prev_cfg.get("preset", "p1")
        a_bitrate = prev_cfg.get("audio_bitrate", "128k")

        # Dla uniknięcia problemów z różnymi timebase w proxy, wycinamy krótkie fragmenty
        segment_files = []
        try:
            for idx, cut in enumerate(cuts):
                s_dur = cut["duration"]
                seg_out = temp_segments_dir / f"seg_{idx:04d}.mp4"

                # --- Obsługa statycznego obrazu outro ---
                if cut.get("source_type") == "image":
                    img_path = cut.get("image_path", cut.get("proxy_path", ""))
                    if not img_path or not Path(img_path).exists():
                        logger.warning(f"Nie znaleziono obrazu outro: {img_path}")
                        continue
                    cmd_img = [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-loop", "1",
                        "-i", str(img_path),
                        "-t", str(s_dur),
                        "-vf", "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2",
                        "-r", "15",
                        "-c:v", v_encoder,
                        "-preset", preset if has_nvenc else "ultrafast",
                        "-cq", cq,
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(seg_out)
                    ]
                    subprocess.run(cmd_img, check=True)
                    segment_files.append(seg_out)
                    continue

                # --- Standardowy klip wideo ---
                proxy_p = Path(cut.get("proxy_path", ""))
                if not proxy_p.exists():
                    proxy_p = self.config.proxy_dir / cut["source_file"]
                    if not proxy_p.exists():
                        # Spróbuj dodać sufiks _480p15
                        candidate = self.config.proxy_dir / f"{proxy_p.stem}_480p15.mp4"
                        if candidate.exists():
                            proxy_p = candidate

                if not proxy_p.exists():
                    logger.warning(f"Nie znaleziono pliku proxy dla ujęcia #{idx+1}: {cut['source_file']}")
                    continue

                s_start = cut["source_start"]
                s_dur = cut["duration"]
                seg_out = temp_segments_dir / f"seg_{idx:04d}.mp4"

                # Wycięcie fragmentu proxy z parametrami draft
                cmd_cut = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(s_start),
                    "-i", str(proxy_p),
                    "-t", str(s_dur),
                    "-c:v", v_encoder,
                    "-preset", preset if has_nvenc else "ultrafast",
                    "-cq", cq,
                    "-an",
                    str(seg_out)
                ]
                subprocess.run(cmd_cut, check=True)
                segment_files.append(seg_out)

            # Zapisz listę do pliku concat
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg in segment_files:
                    f.write(f"file '{seg.resolve().as_posix()}'\n")

            # 2. Połączenie i nałożenie muzyki
            cmd_concat = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list_file),
                "-i", str(music_file),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", a_bitrate,
                "-shortest",
                str(self.output_file)
            ]
            run_command(cmd_concat)

            elapsed = time.time() - start_time
            console.print(f"\n[bold green]Preview wyrenderowane pomyślnie w {elapsed:.1f} s![/bold green]")
            console.print(f"Plik podglądu: [bold yellow]{self.output_file.resolve()}[/bold yellow]\n")

            return self.output_file

        except Exception as e:
            logger.error(f"Błąd podczas renderowania preview: {e}")
            return None
        finally:
            # Czyszczenie plików tymczasowych
            try:
                for seg in segment_files:
                    if seg.exists():
                        seg.unlink()
                if concat_list_file.exists():
                    concat_list_file.unlink()
                if temp_segments_dir.exists():
                    temp_segments_dir.rmdir()
            except Exception:
                pass
