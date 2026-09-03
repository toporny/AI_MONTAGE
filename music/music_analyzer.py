"""
Główny orkiestrator modułu muzycznego: wczytuje audio, wykonuje pełną analizę
i zapisuje ustrukturyzowany wynik do pliku JSON.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import numpy as np

from music.beat_detector import BeatDetector
from music.energy_analyzer import EnergyAnalyzer
from utils.config_loader import Config
from utils.helpers import format_timestamp, safe_save_json
from utils.logger import console, logger

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


class MusicAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        self.beat_detector = BeatDetector(beats_per_bar=config.beats_per_bar)
        self.energy_analyzer = EnergyAnalyzer(
            smoothing_sec=config.energy_smoothing_sec,
            thresholds=config.energy_thresholds
        )

    def analyze_music_file(self, music_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        """
        Wczytuje i analizuje plik muzyczny MP3/WAV.
        """
        if not LIBROSA_AVAILABLE:
            logger.error("Biblioteka librosa nie jest zainstalowana!")
            return None

        audio_file = music_path or self.config.get_music_file_path()
        if not audio_file or not audio_file.exists():
            logger.error(f"Nie znaleziono pliku muzycznego: {audio_file}")
            return None

        console.print(f"\n[bold green]Rozpoczynam analizę utworu muzycznego:[/bold green] [cyan]{audio_file.name}[/cyan]")
        console.print(f"Ścieżka: [dim]{audio_file.resolve()}[/dim]\n")

        # 1. Wczytanie audio
        logger.info(f"Wczytywanie pliku audio {audio_file.name}...")
        y, sr = librosa.load(str(audio_file), sr=22050, mono=True)
        duration = float(librosa.get_duration(y=y, sr=sr))

        logger.info(f"Wczytano audio: {duration:.2f} s ({format_timestamp(duration)}), Próbkowanie: {sr} Hz")

        # 2. Analiza beatów i rytmu
        beat_info = self.beat_detector.analyze_beats(y, sr)

        # 3. Analiza energii i dynamiki
        energy_info = self.energy_analyzer.analyze_energy(y, sr, beat_info["beat_times"])

        # 4. Złożenie całościowego raportu muzycznego
        analysis_data = {
            "file_name": audio_file.name,
            "audio_path": str(audio_file.resolve()),
            "duration": round(duration, 3),
            "duration_formatted": format_timestamp(duration),
            "sample_rate": sr,
            "bpm": beat_info["bpm"],
            "beat_count": beat_info["beat_count"],
            "beat_times": beat_info["beat_times"],
            "bars": beat_info["bars"],
            "bar_start_times": beat_info["bar_start_times"],
            "phrases": beat_info["phrases"],
            "average_energy": energy_info["average_energy"],
            "max_energy": energy_info["max_energy"],
            "beat_energies": energy_info["beat_energies"],
            "drops": energy_info["drops"],
            "energy_blocks": energy_info["energy_blocks"]
        }

        # Zapisz do katalogu storyboard/ lub analysis/
        out_json = self.config.storyboard_dir / "music_analysis.json"
        safe_save_json(analysis_data, out_json)

        # Wyświetl czytelne podsumowanie w konsoli
        console.print("\n[bold green]Podsumowanie analizy muzyki:[/bold green]")
        console.print(f"  • Czas trwania utworu: [bold cyan]{format_timestamp(duration)}[/bold cyan] ({duration:.2f} s)")
        console.print(f"  • Tempo (BPM): [bold cyan]{beat_info['bpm']:.1f}[/bold cyan]")
        console.print(f"  • Liczba wykrytych beatów: [bold]{beat_info['beat_count']}[/bold]")
        console.print(f"  • Liczba taktów (4/4): [bold]{len(beat_info['bars'])}[/bold]")
        console.print(f"  • Liczba fraz muzycznych: [bold]{len(beat_info['phrases'])}[/bold]")
        console.print(f"  • Punkty kulminacyjne / Dropy: [bold magenta]{len(energy_info['drops'])}[/bold magenta]")
        
        for d in energy_info["drops"]:
            console.print(f"    ↳ Drop #{d['drop_idx']+1} o czasie [bold yellow]{format_timestamp(d['time_sec'])}[/bold yellow] (energia: {d['energy']:.2f})")

        console.print(f"\n[green]Zapisano raport muzyczny do:[/green] [dim]{out_json}[/dim]\n")

        return analysis_data
