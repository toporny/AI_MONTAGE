"""
sync_proxies.py — Synchronizacja katalogu ANALIZA_480P z katalogiem ORYGINALY.

Działanie:
  1. Jeśli w ANALIZA_480P brakuje proxy dla pliku z ORYGINALY → kompresuje go do 480p/15fps.
  2. Jeśli w ANALIZA_480P są pliki bez odpowiednika w ORYGINALY → usuwa je (orphan).
  3. Obsługuje pliki z oryginalnych nazw pisanych WIELKIMI LITERAMI.

Uruchamianie (w katalogu AI_MONTAGE):
  .\\venv\\Scripts\\python.exe sync_proxies.py
  .\\venv\\Scripts\\python.exe sync_proxies.py --dry-run    # tylko podgląd, bez zmian
  run.bat sync-proxies
"""

import argparse
import concurrent.futures
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

# Wymusz UTF-8 na stdout/stderr (Windows cmd/powershell może defaultować do cp1250)
if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Bezpieczne wypisywanie na konsolę w środowisku wielowątkowym."""
    with _print_lock:
        print(*args, **kwargs)


# ---------------------------------------------------------------------------
# Konfiguracja ścieżek (względem katalogu tego skryptu)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
ORYGINALY_DIR   = SCRIPT_DIR / "materialy_oryginalne"
ANALIZA_DIR     = SCRIPT_DIR / "kopie_robocze_480p"


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI"}

# Sufiks doklejany do nazwy proxy
PROXY_SUFFIX = "_480p15"

# Parametry kompresji (fps=15 przed scale odrzuca klatki przed skalowaniem)
PROXY_FFMPEG_OPTS = [
    "-vf", "fps=15,scale=854:480:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=854:480:(ow-iw)/2:(oh-ih)/2",
    "-r", "15",
    "-c:v", "libx264",
    "-crf", "28",
    "-preset", "fast",
    "-c:a", "aac",
    "-b:a", "64k",
    "-movflags", "+faststart",
]


def get_base_stem(filename: str) -> str:
    """Usuwa sufiks proxy (_480p15 itp.) i rozszerzenie."""
    stem = Path(filename).stem
    stem = re.sub(r"_480p\d*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_proxy$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_low$", "", stem, flags=re.IGNORECASE)
    return stem


def proxy_name_for(original: Path) -> str:
    """Zwraca docelową nazwę proxy dla danego oryginału (zawsze lowercase .mp4)."""
    base = original.stem.lower()
    return f"{base}{PROXY_SUFFIX}.mp4"


def build_proxy_map(analiza_dir: Path) -> dict[str, Path]:
    """Słownik: stem_proxy (bez sufiksu, lowercase) → ścieżka pliku proxy."""
    mapping: dict[str, Path] = {}
    for f in analiza_dir.glob("*.mp4"):
        key = get_base_stem(f.name).lower()
        mapping[key] = f
    return mapping


def build_original_map(oryginaly_dir: Path) -> dict[str, Path]:
    """Słownik: stem (lowercase) → ścieżka oryginału."""
    mapping: dict[str, Path] = {}
    for ext in VIDEO_EXTS:
        for f in oryginaly_dir.glob(f"*{ext}"):
            mapping[f.stem.lower()] = f
    return mapping


def get_proxy_encoder_config(force_cpu: bool = False) -> tuple[list[str], str]:
    """
    Automatycznie dobiera akcelerację sprzętową enkodera (AMF dla AMD, NVENC dla NVIDIA, QSV dla Intel)
    lub bezpieczny fallback na CPU (libx264).
    """
    if force_cpu:
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "28"], "CPU (libx264) [Wymuszone przez --cpu]"

    try:
        from utils.hardware import HardwareDetector
        enc = HardwareDetector.get_encoder_config(target_mode="preview", requested_codec="auto")
        return enc.args, enc.description
    except Exception as e:
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "28"], f"CPU (libx264) [Domyślny: {e}]"


def compress_to_proxy(original: Path, output: Path, dry_run: bool, encoder_args: list[str]) -> bool:
    """Kompresuje oryginalny plik do proxy 480p/15fps z akceleracją sprzętową."""
    safe_print(f"  ➕ TWORZĘ PROXY: {original.name}  →  {output.name}")
    if dry_run:
        return True
    output.parent.mkdir(parents=True, exist_ok=True)

    # Optymalizacje wydajnościowe:
    # 1. 'fps=15' PRZED 'scale' — odrzuca klatki (np. 45 z 60) przed skalowaniem, redukując obciążenie o 75%!
    # 2. 'flags=fast_bilinear' — szybkie skalowanie dwuliniowe w swscale.
    vf_filter = "fps=15,scale=854:480:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=854:480:(ow-iw)/2:(oh-ih)/2"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(original),
        "-vf", vf_filter,
        "-r", "15",
        *encoder_args,
        "-c:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        # Automatyczny fallback na czysty procesor CPU (libx264) jeśli enkoder sprzętowy zgłosił błąd
        if "libx264" not in encoder_args:
            fallback_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(original),
                "-vf", vf_filter,
                "-r", "15",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
                str(output),
            ]
            fb_res = subprocess.run(fallback_cmd)
            if fb_res.returncode == 0:
                return True

        safe_print(f"    ❌ FFmpeg błąd dla {original.name}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Synchronizacja ANALIZA_480P z ORYGINALY")
    parser.add_argument("--dry-run", action="store_true", help="Tryb podglądu — nie wykonuje żadnych zmian")
    parser.add_argument("--cpu", action="store_true", help="Wymusza kodowanie na procesorze CPU (libx264) zamiast sprzętowego GPU")
    parser.add_argument("--workers", "-j", type=int, default=2, help="Liczba równoległych wątków konwersji (domyślnie: 2)")
    parser.add_argument("--oryginaly", default=str(ORYGINALY_DIR), help="Ścieżka do katalogu oryginałów")
    parser.add_argument("--analiza",   default=str(ANALIZA_DIR),   help="Ścieżka do katalogu proxy 480p")
    args = parser.parse_args()
    start_time = time.time()

    oryginaly_dir = Path(args.oryginaly)
    analiza_dir   = Path(args.analiza)

    oryginaly_dir.mkdir(parents=True, exist_ok=True)
    analiza_dir.mkdir(parents=True, exist_ok=True)

    original_map = build_original_map(oryginaly_dir)
    proxy_map    = build_proxy_map(analiza_dir)

    if not original_map and not proxy_map:
        print(f"\n{'='*70}")
        print("  AI MONTAGE -- INSTRUKCJA STARTOWA (BRAK PLIKOW WIDEO)")
        print(f"{'='*70}\n")
        print("  Projekt jest gotowy, ale w katalogu roboczym nie znaleziono plikow wideo.")
        print("  Aby rozpoczac:")
        print(f"    1. Wgraj pliki wideo (np. z aparatu lub telefonu) do folderu:")
        print(f"       📁 {oryginaly_dir.resolve()}\n")
        print("    2. Uruchom ponownie:")
        print("       👉 ZROB_PREVIEW.bat (lub w konsoli: run.bat sync-proxies)\n")
        print(f"{'='*70}\n")
        sys.exit(1)

    encoder_args, encoder_desc = get_proxy_encoder_config(args.cpu)

    mode = "[DRY-RUN]" if args.dry_run else "[SYNC]"
    print(f"\n{'='*70}")
    print(f"  {mode} Synchronizacja proxy 480p")
    print(f"  ORYGINALY   : {oryginaly_dir}")
    print(f"  ANALIZA_480P: {analiza_dir}")
    print(f"  SILNIK WIDEO: {encoder_desc}")
    print(f"{'='*70}\n")

    added   = 0
    removed = 0
    ok      = 0

    # --- 1. Sprawdź brakujące proxy ---
    print("Krok 1/2: Sprawdzanie brakujących proxy...\n")
    to_compress: list[tuple[Path, Path]] = []
    for orig_stem_lower, orig_path in sorted(original_map.items()):
        if orig_stem_lower in proxy_map:
            ok += 1
            print(f"  ✅ OK     : {orig_path.name}")
        else:
            target_proxy = analiza_dir / proxy_name_for(orig_path)
            to_compress.append((orig_path, target_proxy))

    if to_compress:
        workers = max(1, args.workers)
        if workers > 1 and len(to_compress) > 1 and not args.dry_run:
            actual_workers = min(workers, len(to_compress))
            print(f"\n  ⚡ Przetwarzanie równoległe: {len(to_compress)} plików na {actual_workers} wątkach...\n")
            with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_to_file = {
                    executor.submit(compress_to_proxy, orig, target, args.dry_run, encoder_args): orig
                    for orig, target in to_compress
                }
                for future in concurrent.futures.as_completed(future_to_file):
                    if future.result():
                        added += 1
        else:
            for orig_path, target_proxy in to_compress:
                success = compress_to_proxy(orig_path, target_proxy, args.dry_run, encoder_args)
                if success:
                    added += 1

    # --- 2. Sprawdź nadmiarowe (orphan) proxy ---
    print(f"\nKrok 2/2: Sprawdzanie nadmiarowych proxy (orphan)...\n")
    for proxy_stem_lower, proxy_path in sorted(proxy_map.items()):
        if proxy_stem_lower not in original_map:
            print(f"  🗑️  USUWAM ORPHAN: {proxy_path.name}")
            if not args.dry_run:
                proxy_path.unlink()
            removed += 1

    # --- Podsumowanie ---
    elapsed = time.time() - start_time
    if elapsed >= 60:
        mins = int(elapsed // 60)
        secs = elapsed % 60
        time_str = f"{elapsed:.1f} s ({mins} min {secs:.1f} s)"
    else:
        time_str = f"{elapsed:.1f} s"

    print(f"\n{'='*70}")
    print(f"  Podsumowanie {mode}:")
    print(f"    ✅ Już zsynchronizowanych : {ok}")
    print(f"    ➕ Dodanych (skompresowanych): {added}")
    print(f"    🗑️  Usuniętych (orphan)   : {removed}")
    print(f"    ⏱️  Czas przetwarzania      : {time_str}")
    if args.dry_run:
        print(f"\n  ⚠️  Tryb DRY-RUN — żadne pliki nie zostały zmienione!")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
