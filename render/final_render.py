"""
Moduł finalnego renderowania Master 4K / 60 FPS z oryginalnych plików (ORYGINALY)
z wykorzystaniem sprzętowej akceleracji NVIDIA NVENC i CUDA.
"""

from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional

from utils.config_loader import Config
from utils.helpers import check_ffmpeg_nvenc, find_matching_original, format_timestamp, run_command, safe_load_json
from utils.logger import console, logger


class FinalRenderer:
    def __init__(self, config: Config):
        self.config = config
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_file = self.output_dir / "final_montage_4K60.mp4"

    def render_final_master(self, storyboard_data: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        """
        Renderuje finalny film 4K/60fps na podstawie zaakceptowanego storyboardu
        oraz oryginalnych plików wysokiej jakości.
        """
        if storyboard_data is None:
            sb_path = self.config.storyboard_dir / "storyboard.json"
            storyboard_data = safe_load_json(sb_path)

        if not storyboard_data or "cuts" not in storyboard_data:
            logger.error("Brak danych storyboardu do renderu finalnego!")
            return None

        cuts = storyboard_data["cuts"]
        music_file = self.config.get_music_file_path()
        if not music_file or not music_file.exists():
            logger.error(f"Nie znaleziono pliku muzycznego: {music_file}")
            return None

        orig_dir = self.config.original_dir
        if not orig_dir.exists():
            logger.error(f"Katalog oryginałów 4K nie istnieje: {orig_dir}")
            return None

        console.print(f"\n[bold green]================================================================================[/bold green]")
        console.print(f"[bold green]        ROZPOCZYNAM FINALNY RENDER MASTER 4K / 60 FPS (NVIDIA NVENC)[/bold green]")
        console.print(f"[bold green]================================================================================[/bold green]\n")
        console.print(f"Liczba ujęć: [bold cyan]{len(cuts)}[/bold cyan]")
        console.print(f"Katalog oryginałów: [dim]{orig_dir.resolve()}[/dim]")
        console.print(f"Podkład audio: [bold cyan]{music_file.name}[/bold cyan]")
        console.print(f"Plik docelowy: [bold yellow]{self.output_file.resolve()}[/bold yellow]\n")

        start_time = time.time()

        has_nvenc, nvenc_codec = check_ffmpeg_nvenc()
        cfg_codec = self.config.final_settings.get("codec", "hevc_nvenc")
        
        # Wybierz odpowiedni kodek NVENC
        if has_nvenc:
            chosen_codec = cfg_codec if (cfg_codec in ["hevc_nvenc", "h264_nvenc"]) else nvenc_codec
        else:
            chosen_codec = "libx264"
            logger.warning("NVENC nie jest dostępny. Używam programowego libx264.")

        cq = str(self.config.final_settings.get("cq", 19))
        preset = self.config.final_settings.get("preset", "p6")
        tune = self.config.final_settings.get("tune", "hq")

        temp_dir = self.output_dir / "temp_4k_segments"
        temp_dir.mkdir(parents=True, exist_ok=True)
        concat_list_file = self.output_dir / "concat_4k.txt"

        segment_files: List[Path] = []
        missing_originals = []

        try:
            console.print("[yellow]Etap 1/2: Precyzyjne wycinanie i kodowanie ujęć 4K/60fps przez GPU...[/yellow]")
            for idx, cut in enumerate(cuts, 1):
                proxy_name = cut["source_file"]
                s_dur = cut["duration"]
                seg_out = temp_dir / f"master_seg_{idx:04d}.mp4"

                # --- Obsługa statycznego obrazu outro ---
                if cut.get("source_type") == "image":
                    img_path = cut.get("image_path", cut.get("proxy_path", ""))
                    if not img_path or not Path(img_path).exists():
                        logger.error(f"Nie znaleziono obrazu outro: {img_path}")
                        missing_originals.append(proxy_name)
                        continue
                    console.print(f"  [{idx:03d}/{len(cuts):03d}] OBRAZ OUTRO: {Path(img_path).name} ({s_dur:.2f}s)")
                    cmd_img = [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-loop", "1",
                        "-i", str(img_path),
                        "-t", str(s_dur),
                        "-vf", "scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2",
                        "-r", "60",
                        "-c:v", chosen_codec,
                        "-preset", preset,
                        "-tune", tune,
                        "-rc", "vbr",
                        "-cq", cq,
                        "-b:v", "0",
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(seg_out)
                    ]
                    subprocess.run(cmd_img, check=True)
                    segment_files.append(seg_out)
                    continue

                # --- Standardowy klip wideo ---
                orig_file = find_matching_original(proxy_name, orig_dir)

                if not orig_file or not orig_file.exists():
                    logger.error(f"Nie znaleziono oryginału 4K dla: {proxy_name}")
                    missing_originals.append(proxy_name)
                    continue

                s_start = cut["source_start"]
                s_dur = cut["duration"]
                seg_out = temp_dir / f"master_seg_{idx:04d}.mp4"

                console.print(f"  [{idx:03d}/{len(cuts):03d}] Wycinanie {orig_file.name} od {format_timestamp(s_start)} ({s_dur:.2f}s)")

                # Komenda wycinania ujęcia z akceleracją GPU
                cmd_cut = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(s_start),
                    "-i", str(orig_file),
                    "-t", str(s_dur),
                    "-c:v", chosen_codec,
                    "-preset", preset,
                    "-tune", tune,
                    "-rc", "vbr",
                    "-cq", cq,
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                    "-r", "60",
                    "-an",  # Całkowite odcięcie oryginalnego audio
                    str(seg_out)
                ]

                subprocess.run(cmd_cut, check=True)
                segment_files.append(seg_out)

            if not segment_files:
                logger.error("Żadne ujęcie 4K nie zostało pomyślnie wycięte.")
                return None

            # Zapisz listę concat
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg in segment_files:
                    f.write(f"file '{seg.resolve().as_posix()}'\n")

            console.print("\n[yellow]Etap 2/2: Łączenie filmu i miksowanie ścieżki muzycznej MP3...[/yellow]")
            
            # Połączenie ujęć z nałożeniem muzyki
            cmd_concat = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list_file),
                "-i", str(music_file),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "320k",
                "-shortest",
                str(self.output_file)
            ]
            run_command(cmd_concat)

            elapsed = time.time() - start_time
            file_size_mb = self.output_file.stat().st_size / (1024 * 1024)

            console.print(f"\n[bold green]================================================================================[/bold green]")
            console.print(f"[bold green]                 FINALNY MASTER 4K / 60 FPS GOTOWY![/bold green]")
            console.print(f"[bold green]================================================================================[/bold green]")
            console.print(f"  • Plik wynikowy: [bold yellow]{self.output_file.resolve()}[/bold yellow]")
            console.print(f"  • Rozmiar pliku: [bold cyan]{file_size_mb:.2f} MB[/bold cyan]")
            console.print(f"  • Czas renderowania: [bold cyan]{elapsed:.1f} s[/bold cyan] ({elapsed/60:.1f} min)")
            console.print(f"  • Użyty kodek: [bold green]{chosen_codec}[/bold green] (NVIDIA NVENC)")
            console.print(f"  • Oryginalne audio: [bold red]USUNIĘTE[/bold red]")
            console.print(f"  • Muzyka: [bold green]{music_file.name}[/bold green] (AAC 320 kbps)")
            console.print(f"[bold green]================================================================================[/bold green]\n")

            return self.output_file

        except Exception as e:
            logger.error(f"Błąd podczas finalnego renderowania 4K: {e}")
            return None
        finally:
            # Czyszczenie segmentów tymczasowych
            try:
                for seg in segment_files:
                    if seg.exists():
                        seg.unlink()
                if concat_list_file.exists():
                    concat_list_file.unlink()
                if temp_dir.exists():
                    temp_dir.rmdir()
            except Exception:
                pass
