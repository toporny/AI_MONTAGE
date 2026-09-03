"""
Funkcje pomocnicze do operacji na plikach, formatowania czasu i integracji z FFmpeg.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.logger import logger


def format_timestamp(seconds: float) -> str:
    """
    Formatuje sekundy do postaci MM:SS.mmm lub HH:MM:SS.mmm.
    np. 4.12 -> 00:04.120
    """
    if seconds < 0:
        seconds = 0.0
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    else:
        return f"{minutes:02d}:{secs:06.3f}"


def parse_timestamp(ts_str: str) -> float:
    """
    Parsuje timestamp w formacie MM:SS.mmm lub HH:MM:SS.mmm do sekund.
    """
    parts = ts_str.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        elif len(parts) == 1:
            return float(parts[0])
    except Exception as e:
        logger.error(f"Błąd parsowania timestampu '{ts_str}': {e}")
    return 0.0


def safe_load_json(file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Bezpiecznie wczytuje plik JSON."""
    p = Path(file_path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Błąd odczytu JSON z {file_path}: {e}")
        return None


def safe_save_json(data: Any, file_path: Union[str, Path], indent: int = 2) -> bool:
    """Bezpiecznie zapisuje dane do pliku JSON."""
    p = Path(file_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        temp_path = p.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        temp_path.replace(p)
        return True
    except Exception as e:
        logger.error(f"Błąd zapisu JSON do {file_path}: {e}")
        return False


def extract_event_timestamp(filename_or_path: Union[str, Path]) -> float:
    """
    Ekstraktuje datę i godzinę z nazwy pliku w formacie DD_HHMMSS lub DD_HHMM (np. 28_154815_...).
    Zwraca ciągłą wartość czasu w sekundach (dzień * 86400 + godzina * 3600 + minuta * 60 + sekunda).
    W przypadku braku wzorca, używa czasu modyfikacji pliku lub 0.
    """
    p = Path(filename_or_path)
    name = p.name

    # Sprawdź wzorzec DD_HHMMSS lub DD_HHMM...
    m = re.match(r"^(\d{2})_(\d{2})(\d{2})(\d{1,2})?", name)
    if m:
        try:
            day = int(m.group(1))
            hour = int(m.group(2))
            minute = int(m.group(3))
            sec = int(m.group(4)) if m.group(4) else 0
            return float(day * 86400 + hour * 3600 + minute * 60 + sec)
        except Exception:
            pass

    # Fallback: czas modyfikacji pliku jeśli istnieje na dysku
    try:
        if p.exists():
            return float(p.stat().st_mtime)
    except Exception:
        pass

    return 0.0


def get_base_stem(filename: str) -> str:
    """
    Usuwa sufiksy proxy typu _480p15, _480p, _proxy z nazwy pliku.
    np. 28_154815_rejestracja_480p15.mp4 -> 28_154815_rejestracja
    """
    stem = Path(filename).stem
    # Usuń typowe wzorce proxy
    stem = re.sub(r"_480p\d*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_proxy$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_low$", "", stem, flags=re.IGNORECASE)
    return stem


def find_matching_original(proxy_path: Union[str, Path], originals_dir: Union[str, Path]) -> Optional[Path]:
    """
    Znajduje odpowiadający oryginalny plik 4K w katalogu oryginałów.
    Obsługuje:
    - identyczną nazwę (plik.mp4 -> plik.mp4)
    - usunięcie sufiksu proxy (plik_480p15.mp4 -> plik.mp4)
    - dopasowanie prefiksu
    - pliki ORYGINALY pisane WIELKIMI LITERAMI (np. 29_125240_piata_mowczyni_na_scenie_B.mp4)
    """
    p_path = Path(proxy_path)
    orig_dir = Path(originals_dir)
    if not orig_dir.exists():
        logger.error(f"Katalog oryginałów nie istnieje: {originals_dir}")
        return None

    base_stem = get_base_stem(p_path.name)
    base_stem_lower = base_stem.lower()

    # 1. Sprawdź po usunięciu sufiksu — wszystkie kombinacje rozszerzeń i wielkości liter
    for ext in (".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV"):
        for stem_variant in (base_stem, base_stem.upper(), base_stem.capitalize()):
            candidate = orig_dir / f"{stem_variant}{ext}"
            if candidate.exists():
                return candidate

    # 2. Case-insensitive glob po wszystkich plikach wideo w katalogu oryginałów
    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".mts", ".m2ts"}
    for f in orig_dir.iterdir():
        if f.suffix.lower() in video_exts:
            if f.stem.lower() == base_stem_lower:
                return f

    # 3. Wyszukaj plik o podobnym początku nazwy (prefix match, case-insensitive)
    for f in orig_dir.iterdir():
        if f.suffix.lower() in video_exts:
            f_lower = f.stem.lower()
            if f_lower.startswith(base_stem_lower) or base_stem_lower.startswith(f_lower):
                return f

    return None


def run_command(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Uruchamia komendę systemową i loguje ewentualne błędy."""
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    logger.debug(f"Uruchamianie komendy: {cmd_str}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        logger.error(f"Błąd wykonania komendy (kod {result.returncode}):\n{result.stderr}")
        raise RuntimeError(f"Komenda zakończona błędem {result.returncode}: {cmd_str}\n{result.stderr}")
    return result


def check_ffmpeg_nvenc() -> Tuple[bool, str]:
    """Sprawdza czy FFmpeg obsługuje NVENC dla H.264 lub HEVC."""
    try:
        res = subprocess.run(["ffmpeg", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        encoders = res.stdout
        has_hevc = "hevc_nvenc" in encoders
        has_h264 = "h264_nvenc" in encoders
        if has_hevc:
            return True, "hevc_nvenc"
        elif has_h264:
            return True, "h264_nvenc"
        else:
            return False, "libx264"
    except Exception as e:
        logger.warning(f"Nie można sprawdzić enkoderów FFmpeg: {e}")
        return False, "libx264"
