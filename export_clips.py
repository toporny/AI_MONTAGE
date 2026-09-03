"""
export_clips.py — Eksportuje wycięte fragmenty z finalnego storyboardu do dwóch katalogów:

  AI_MONTAGE/
    clips_4k/      — fragmenty wycięte z oryginalnych plików 4K (pełna jakość)
    clips_480p/    — fragmenty wycięte z proxy 480p/15fps (podgląd)

Pliki są numerowane zgodnie z kolejnością cięcia: 001_<oryginalna_nazwa>.mp4

Uruchamianie (w katalogu AI_MONTAGE):
  .\\venv\\Scripts\\python.exe export_clips.py
  .\\venv\\Scripts\\python.exe export_clips.py --only-proxy    # tylko wersja 480p
  .\\venv\\Scripts\\python.exe export_clips.py --only-4k       # tylko wersja 4K
  run.bat export-clips
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
# Konfiguracja ścieżek
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).parent.resolve()
ORYGINALY_DIR = SCRIPT_DIR / "materialy_oryginalne"
ANALIZA_DIR   = SCRIPT_DIR / "kopie_robocze_480p"
STORYBOARD_JSON = SCRIPT_DIR / "storyboard" / "storyboard.json"
CLIPS_4K_DIR    = SCRIPT_DIR / "clips_4k"
CLIPS_480P_DIR  = SCRIPT_DIR / "clips_480p"


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI"}


def get_base_stem(filename: str) -> str:
    """Usuwa sufiks proxy (_480p15 itp.) i rozszerzenie."""
    stem = Path(filename).stem
    stem = re.sub(r"_480p\d*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_proxy$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_low$", "", stem, flags=re.IGNORECASE)
    return stem


def find_original(proxy_name: str, originals_dir: Path) -> Path | None:
    """
    Znajduje oryginalny plik 4K pasujący do nazwy proxy.
    Obsługuje pliki pisane WIELKIMI LITERAMI w ORYGINALY.
    """
    base_stem = get_base_stem(proxy_name)

    # 1. Dokładne dopasowanie (lowercase i oryginalna)
    for ext in (".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV"):
        for candidate in [
            originals_dir / f"{base_stem}{ext}",
            originals_dir / f"{base_stem.upper()}{ext}",
        ]:
            if candidate.exists():
                return candidate

    # 2. Case-insensitive glob po wszystkich plikach w katalogu
    base_lower = base_stem.lower()
    for ext in VIDEO_EXTS:
        for f in originals_dir.glob(f"*{ext}"):
            if f.stem.lower() == base_lower:
                return f

    # 3. Dopasowanie po prefiksie (stem oryginału zaczyna się od base_stem)
    for ext in VIDEO_EXTS:
        for f in originals_dir.glob(f"*{ext}"):
            if f.stem.lower().startswith(base_lower) or base_lower.startswith(f.stem.lower()):
                return f

    return None


def find_proxy(proxy_name: str, analiza_dir: Path) -> Path | None:
    """Znajduje plik proxy 480p. proxy_name pochodzi bezpośrednio ze storyboardu."""
    direct = analiza_dir / proxy_name
    if direct.exists():
        return direct
    # Fallback: szukaj case-insensitive
    target_lower = proxy_name.lower()
    for f in analiza_dir.glob("*.mp4"):
        if f.name.lower() == target_lower:
            return f
    return None


def cut_segment(input_file: Path, output_file: Path, start_sec: float, duration: float,
                codec: str = "copy", extra_args: list[str] | None = None) -> bool:
    """Wycina fragment z pliku wideo przez FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_sec:.3f}",
        "-i", str(input_file),
        "-t", f"{duration:.3f}",
        "-c:v", codec,
        "-an",  # bez oryginalnego audio w klipach
    ]
    if extra_args:
        cmd += extra_args
    cmd.append(str(output_file))
    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Eksport wycięć ze storyboardu do katalogów clips_4k/ i clips_480p/")
    parser.add_argument("--only-proxy", action="store_true", help="Eksportuj tylko wersje 480p")
    parser.add_argument("--only-4k",   action="store_true", help="Eksportuj tylko wersje 4K")
    parser.add_argument("--storyboard", default=str(STORYBOARD_JSON), help="Ścieżka do pliku storyboard.json")
    parser.add_argument("--oryginaly",  default=str(ORYGINALY_DIR),   help="Katalog oryginałów 4K")
    parser.add_argument("--analiza",    default=str(ANALIZA_DIR),     help="Katalog proxy 480p")
    parser.add_argument("--out-4k",     default=str(CLIPS_4K_DIR),    help="Katalog wyjściowy dla klipów 4K")
    parser.add_argument("--out-480p",   default=str(CLIPS_480P_DIR),  help="Katalog wyjściowy dla klipów 480p")
    args = parser.parse_args()

    import json
    sb_path = Path(args.storyboard)
    if not sb_path.exists():
        print(f"❌ Nie znaleziono storyboard.json: {sb_path}", file=sys.stderr)
        sys.exit(1)

    with open(sb_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    cuts = storyboard.get("cuts", [])
    if not cuts:
        print("❌ Storyboard jest pusty lub nie zawiera ujęć.", file=sys.stderr)
        sys.exit(1)

    oryginaly_dir = Path(args.oryginaly)
    analiza_dir   = Path(args.analiza)
    out_4k        = Path(args.out_4k)
    out_480p      = Path(args.out_480p)

    do_4k   = not args.only_proxy
    do_480p = not args.only_4k

    if do_4k:
        out_4k.mkdir(parents=True, exist_ok=True)
    if do_480p:
        out_480p.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  Eksport klipów ze storyboardu ({len(cuts)} ujęć)")
    if do_4k:
        print(f"  clips_4k/   → {out_4k}")
    if do_480p:
        print(f"  clips_480p/ → {out_480p}")
    print(f"{'='*70}\n")

    ok_4k = 0; fail_4k = 0
    ok_480p = 0; fail_480p = 0

    for cut in cuts:
        idx          = cut["cut_idx"]
        source_file  = cut["source_file"]   # np. 28_154900_przed_wejsciem2_480p15.mp4
        source_start = float(cut["source_start"])
        duration     = float(cut["duration"])
        timeline_s   = cut["timeline_start"]
        timeline_e   = cut["timeline_end"]

        base_stem    = get_base_stem(source_file)
        safe_name    = re.sub(r"[^\w\-.]", "_", base_stem)
        clip_name    = f"{idx:03d}_{safe_name}.mp4"

        print(f"[{idx:03d}] {source_file}  ({timeline_s:.1f}s–{timeline_e:.1f}s, src@{source_start:.2f}s, dur={duration:.2f}s)")

        # --- Eksport 480p ---
        if do_480p:
            proxy_file = find_proxy(source_file, analiza_dir)
            if proxy_file:
                out_path = out_480p / clip_name
                ok = cut_segment(proxy_file, out_path, source_start, duration, codec="copy")
                if ok:
                    print(f"    ✅ 480p: {clip_name}")
                    ok_480p += 1
                else:
                    # Fallback: przelicz przez libx264 jeśli copy zawiedzie
                    ok = cut_segment(proxy_file, out_path, source_start, duration,
                                     codec="libx264", extra_args=["-crf", "28", "-preset", "ultrafast"])
                    if ok:
                        print(f"    ✅ 480p (re-encode): {clip_name}")
                        ok_480p += 1
                    else:
                        print(f"    ❌ 480p BŁĄD: {source_file}")
                        fail_480p += 1
            else:
                print(f"    ⚠️  480p: nie znaleziono proxy dla {source_file}")
                fail_480p += 1

        # --- Eksport 4K ---
        if do_4k:
            orig_file = find_original(source_file, oryginaly_dir)
            if orig_file:
                out_path = out_4k / clip_name
                ok = cut_segment(orig_file, out_path, source_start, duration,
                                 codec="hevc_nvenc",
                                 extra_args=["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19",
                                             "-b:v", "0", "-pix_fmt", "yuv420p", "-r", "60"])
                if ok:
                    print(f"    ✅ 4K:   {clip_name}")
                    ok_4k += 1
                else:
                    # Fallback do libx265 jeśli NVENC niedostępny
                    ok = cut_segment(orig_file, out_path, source_start, duration,
                                     codec="libx265", extra_args=["-crf", "22", "-preset", "fast"])
                    if ok:
                        print(f"    ✅ 4K (CPU): {clip_name}")
                        ok_4k += 1
                    else:
                        print(f"    ❌ 4K BŁĄD: {source_file}")
                        fail_4k += 1
            else:
                print(f"    ⚠️  4K: nie znaleziono oryginału dla {source_file}")
                fail_4k += 1

    print(f"\n{'='*70}")
    print(f"  Podsumowanie eksportu klipów:")
    if do_480p:
        print(f"    clips_480p/ ✅ {ok_480p}  ❌ {fail_480p}")
    if do_4k:
        print(f"    clips_4k/   ✅ {ok_4k}   ❌ {fail_4k}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
