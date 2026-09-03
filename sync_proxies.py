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
import re
import subprocess
import sys

# Wymusz UTF-8 na stdout/stderr (Windows cmd/powershell może defaultować do cp1250)
if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguracja ścieżek (względem katalogu tego skryptu)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
ORYGINALY_DIR   = SCRIPT_DIR / "materialy_oryginalne"
ANALIZA_DIR     = SCRIPT_DIR / "kopie_robocze_480p"


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI"}

# Sufiks doklejany do nazwy proxy
PROXY_SUFFIX = "_480p15"

# Parametry kompresji
PROXY_FFMPEG_OPTS = [
    "-vf", "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2",
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


def compress_to_proxy(original: Path, output: Path, dry_run: bool) -> bool:
    """Kompresuje oryginalny plik do proxy 480p/15fps."""
    print(f"  ➕ TWORZĘ PROXY: {original.name}  →  {output.name}")
    if dry_run:
        return True
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(original),
        *PROXY_FFMPEG_OPTS,
        str(output),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"    ❌ FFmpeg błąd dla {original.name}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Synchronizacja ANALIZA_480P z ORYGINALY")
    parser.add_argument("--dry-run", action="store_true", help="Tryb podglądu — nie wykonuje żadnych zmian")
    parser.add_argument("--oryginaly", default=str(ORYGINALY_DIR), help="Ścieżka do katalogu oryginałów")
    parser.add_argument("--analiza",   default=str(ANALIZA_DIR),   help="Ścieżka do katalogu proxy 480p")
    args = parser.parse_args()

    oryginaly_dir = Path(args.oryginaly)
    analiza_dir   = Path(args.analiza)

    if not oryginaly_dir.exists():
        print(f"❌ Katalog oryginałów nie istnieje: {oryginaly_dir}", file=sys.stderr)
        sys.exit(1)

    analiza_dir.mkdir(parents=True, exist_ok=True)

    mode = "[DRY-RUN]" if args.dry_run else "[SYNC]"
    print(f"\n{'='*70}")
    print(f"  {mode} Synchronizacja proxy 480p")
    print(f"  ORYGINALY   : {oryginaly_dir}")
    print(f"  ANALIZA_480P: {analiza_dir}")
    print(f"{'='*70}\n")

    original_map = build_original_map(oryginaly_dir)
    proxy_map    = build_proxy_map(analiza_dir)

    added   = 0
    removed = 0
    ok      = 0

    # --- 1. Sprawdź brakujące proxy ---
    print("Krok 1/2: Sprawdzanie brakujących proxy...\n")
    for orig_stem_lower, orig_path in sorted(original_map.items()):
        if orig_stem_lower in proxy_map:
            ok += 1
            print(f"  ✅ OK     : {orig_path.name}")
        else:
            target_proxy = analiza_dir / proxy_name_for(orig_path)
            success = compress_to_proxy(orig_path, target_proxy, args.dry_run)
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
    print(f"\n{'='*70}")
    print(f"  Podsumowanie {mode}:")
    print(f"    ✅ Już zsynchronizowanych : {ok}")
    print(f"    ➕ Dodanych (skompresowanych): {added}")
    print(f"    🗑️  Usuniętych (orphan)   : {removed}")
    if args.dry_run:
        print(f"\n  ⚠️  Tryb DRY-RUN — żadne pliki nie zostały zmienione!")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
