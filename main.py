"""
Główny punkt wejściowy systemu automatycznego montażu AI (AI Montage CLI).

Komendy:
  python main.py analyze             - Analiza wszystkich klipów wideo proxy (480p) z cache
  python main.py analyze-music       - Analiza beatów, tempa BPM i energii muzyki MP3
  python main.py create-storyboard   - Generowanie inteligentnego storyboardu (JSON + TXT)
  python main.py preview             - Renderowanie szybkiego podglądu 480p z proxy
  python main.py render              - Finalny render master 4K / 60 FPS z oryginałów (NVENC)
  python main.py all                 - Wykonanie pełnego pipeline'u od A do Z
"""

import argparse
from pathlib import Path
import sys

from analyzer.video_analyzer import VideoAnalyzer
from montage.selector import MontageSelector
from montage.storyboard import StoryboardManager
from montage.timeline import TimelineBuilder
from music.music_analyzer import MusicAnalyzer
from render.final_render import FinalRenderer
from render.preview import PreviewRenderer
from utils.config_loader import load_config
from utils.hardware import HardwareDetector
from utils.logger import console, logger


def main():
    parser = argparse.ArgumentParser(
        description="AI Automatic Music Montage System (Universal Hardware / NVENC / AMF / QSV / CPU)",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "command",
        choices=["analyze", "analyze-music", "create-storyboard", "preview", "render", "openshot", "hardware", "clean", "all"],
        help="Komenda do wykonania:\n"
             "  analyze           - Skanuje i analizuje pliki wideo proxy 480p\n"
             "  analyze-music     - Analizuje BPM, beaty i dynamikę muzyki MP3\n"
             "  create-storyboard - Generuje storyboard.json oraz storyboard.txt\n"
             "  preview           - Renderuje szybki podgląd 480p z proxy\n"
             "  render            - Renderuje finalny film 4K / 60 FPS z oryginałów\n"
             "  openshot          - Generuje plik projektu OpenShot (.osp) ze storyboardu\n"
             "  hardware          - Wyświetla audyt sprzętu (GPU i FFmpeg) oraz wskazówki\n"
             "  clean             - Czyści pliki tymczasowe, cache i rendery, przygotowując nowy projekt\n"
             "  all               - Uruchamia wszystkie etapy po kolei"
    )

    parser.add_argument("--config", type=str, default=None, help="Ścieżka do pliku config.yaml")
    parser.add_argument("--music", type=str, default=None, help="Ścieżka lub nazwa pliku MP3")
    parser.add_argument("--force", action="store_true", help="Wymusza ponowne przeliczenie analizy wideo (ignoruje cache)")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatyczne potwierdzenie bez pytania (dla komendy clean)")

    args = parser.parse_args()

    # 1. Ładowanie konfiguracji
    try:
        config = load_config(args.config)
        if args.music:
            config.music_file = args.music
    except Exception as e:
        console.print(f"[bold red]Błąd ładowania konfiguracji:[/bold red] {e}")
        sys.exit(1)

    cmd = args.command

    if cmd == "hardware":
        HardwareDetector.print_startup_banner(console)
        return

    if cmd == "clean":
        console.print("[bold yellow]================================================================================[/bold yellow]")
        console.print("[bold yellow]         CZYSZCZENIE PLIKÓW TYMCZASOWYCH I WYNIKOWYCH PROJEKTU[/bold yellow]")
        console.print("[bold yellow]================================================================================[/bold yellow]\n")
        console.print("Operacja usunie zawartość folderów:")
        console.print(f"  • Cache analizy wideo i muzyki: [cyan]{config.cache_dir}[/cyan]")
        console.print(f"  • Storyboard i projekty OSP:    [cyan]{config.storyboard_dir}[/cyan]")
        console.print(f"  • Pliki podglądu (preview):     [cyan]{config.preview_dir}[/cyan]")
        console.print(f"  • Pliki wynikowe 4K (output):   [cyan]{config.output_dir}[/cyan]")
        console.print("  • Wycięte klipy ujęć:           [cyan]clips_480p/, clips_4k/[/cyan]")
        console.print("  • Plik logów aplikacji:         [cyan]montage.log[/cyan]\n")
        console.print("[bold green]Twoje oryginalne materiały wideo i pliki muzyczne NIE zostaną usunięte.[/bold green]\n")

        if not args.yes:
            confirm = input("Czy na pewno chcesz wyczyścić projekt do zera? [t/N]: ")
            if confirm.strip().lower() not in ["t", "tak", "y", "yes"]:
                console.print("[yellow]Anulowano czyszczenie.[/yellow]")
                return

        from utils.helpers import clean_project_artifacts
        res = clean_project_artifacts(config)
        mb = res["total_bytes"] / (1024 * 1024)
        console.print(f"\n[bold green]Projekt został pomyślnie wyczyszczony![/bold green]")
        console.print(f"  • Usunięte pliki w analysis:   [bold cyan]{res['analysis']}[/bold cyan]")
        console.print(f"  • Usunięte pliki w storyboard: [bold cyan]{res['storyboard']}[/bold cyan]")
        console.print(f"  • Usunięte pliki w preview:    [bold cyan]{res['preview']}[/bold cyan]")
        console.print(f"  • Usunięte pliki w output:     [bold cyan]{res['output']}[/bold cyan]")
        console.print(f"  • Usunięte pliki w clips_*:    [bold cyan]{res['clips']}[/bold cyan]")
        console.print(f"  • Zwolnione miejsce na dysku:  [bold cyan]{mb:.1f} MB[/bold cyan]\n")
        console.print("[bold green]Katalogi są puste i gotowe do rozpoczęcia nowego projektu od zera![/bold green]")
        return

    console.print("[bold blue]================================================================================[/bold blue]")
    console.print("[bold cyan]       INTELIGENTNY SYSTEM AUTOMATYCZNEGO MONTAŻU AI (AI MONTAGE)[/bold cyan]")
    console.print("[bold blue]================================================================================[/bold blue]\n")

    if cmd in ["preview", "render", "all"]:
        HardwareDetector.print_startup_banner(console)

    # Inicjalizacja modułów
    video_analyzer = VideoAnalyzer(config)
    music_analyzer = MusicAnalyzer(config)
    timeline_builder = TimelineBuilder(config)
    montage_selector = MontageSelector(config)
    storyboard_mgr = StoryboardManager(config)
    preview_renderer = PreviewRenderer(config)
    final_renderer = FinalRenderer(config)

    # ==========================================
    # ETAP 1: ANALIZA WIDEO (PROXY 480P)
    # ==========================================
    if cmd in ["analyze", "all"]:
        video_analyses = video_analyzer.analyze_all_videos(force_recompute=args.force)
        if not video_analyses and cmd != "all":
            sys.exit(1)

    # ==========================================
    # ETAP 2: ANALIZA MUZYKI
    # ==========================================
    if cmd in ["analyze-music", "all"]:
        music_path = Path(args.music) if args.music else None
        music_data = music_analyzer.analyze_music_file(music_path)
        if not music_data and cmd != "all":
            sys.exit(1)

    # ==========================================
    # ETAP 3 & 4: STORYBOARD (TIMELINE + SELEKCJA)
    # ==========================================
    if cmd in ["create-storyboard", "all"]:
        # Załaduj analizy wideo z cache
        video_analyses = video_analyzer.analyze_all_videos(force_recompute=False)
        if not video_analyses:
            console.print("[bold red]Błąd: Brak danych analizy wideo. Uruchom najpierw: python main.py analyze[/bold red]")
            sys.exit(1)

        # Załaduj lub wykonaj analizę muzyki
        music_path = Path(args.music) if args.music else None
        music_data = music_analyzer.analyze_music_file(music_path)
        if not music_data:
            console.print("[bold red]Błąd: Nie udało się przeprowadzić analizy muzyki.[/bold red]")
            sys.exit(1)

        # Budowa slotów timeline
        timeline_slots = timeline_builder.build_timeline_slots(music_data)

        # Inteligentna selekcja ujęć
        cuts = montage_selector.select_montage(timeline_slots, video_analyses)

        # Eksport storyboardu (JSON + TXT)
        storyboard_mgr.export_storyboard(cuts, music_data)

    # ==========================================
    # ETAP 5: PREVIEW 480P
    # ==========================================
    if cmd in ["preview", "all"]:
        sb_data = storyboard_mgr.load_storyboard()
        if not sb_data:
            console.print("[bold red]Błąd: Brak pliku storyboard.json. Uruchom: python main.py create-storyboard[/bold red]")
            sys.exit(1)

        preview_file = preview_renderer.render_preview(sb_data)
        if not preview_file and cmd != "all":
            sys.exit(1)

    # ==========================================
    # ETAP 6: FINAL MASTER RENDER 4K / 60 FPS
    # ==========================================
    if cmd == "render":
        sb_data = storyboard_mgr.load_storyboard()
        if not sb_data:
            console.print("[bold red]Błąd: Brak pliku storyboard.json. Uruchom: python main.py create-storyboard[/bold red]")
            sys.exit(1)

        final_file = final_renderer.render_final_master(sb_data)
        if not final_file:
            sys.exit(1)

    # ==========================================
    # ETAP 7: EKSPORT PROJEKTU OPENSHOT (.OSP)
    # ==========================================
    if cmd == "openshot":
        sb_data = storyboard_mgr.load_storyboard()
        if not sb_data:
            console.print("[bold red]Błąd: Brak pliku storyboard.json. Uruchom: python main.py create-storyboard[/bold red]")
            sys.exit(1)

        res_4k, res_480p = storyboard_mgr.openshot_exporter.export_both_projects(sb_data)
        if not res_4k and not res_480p:
            sys.exit(1)

    if cmd == "all":
        console.print("[bold green]Wszystkie etapy przygotowawcze (analiza, storyboard, preview 480p) zostały zakończone![/bold green]")
        console.print("[bold yellow]Możesz obejrzeć wygenerowany podgląd w katalogu 'preview/' oraz sprawdzić 'storyboard/storyboard.txt'.[/bold yellow]")
        console.print("[bold cyan]Aby wyrenderować ostateczny film 4K/60 fps, uruchom: python main.py render[/bold cyan]\n")


if __name__ == "__main__":
    main()
