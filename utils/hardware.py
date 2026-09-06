"""
Moduł automatycznego wykrywania i audytu sprzętu (GPU & FFmpeg) dla AI Montage.
Obsługuje:
- Automatyczne rozpoznawanie GPU (NVIDIA, AMD Radeon, Intel Arc/Iris, CPU)
- Audyt wkompilowanych enkoderów FFmpeg (NVENC, AMF, QSV, libx264, libx265)
- Inteligentne wskazówki i diagnostykę (np. karta AMD bez wsparcia AMF w FFmpeg)
- Dedykowane, zoptymalizowane parametry FFmpeg per producent
"""

import dataclasses
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclasses.dataclass
class GPUInfo:
    name: str
    vendor: str  # "nvidia", "amd", "intel", "unknown", "cpu"
    driver_version: Optional[str] = None
    vram_bytes: Optional[int] = None
    status: Optional[str] = None

    @property
    def vram_gb(self) -> Optional[float]:
        if self.vram_bytes and self.vram_bytes > 0:
            return round(self.vram_bytes / (1024 ** 3), 1)
        return None

    @property
    def is_dedicated(self) -> bool:
        v = self.vendor.lower()
        n = self.name.lower()
        if v in ["nvidia", "amd"]:
            # Wyklucz starsze zintegrowane układy jeśli nie mają VRAM
            if "radeon(tm) graphics" in n or "radeon vega" in n:
                return (self.vram_bytes or 0) > 2 * (1024 ** 3)
            return True
        if v == "intel" and ("arc" in n or "xe" in n):
            return True
        return False


@dataclasses.dataclass
class FFmpegCapabilities:
    available: bool = False
    path: Optional[str] = None
    version_str: Optional[str] = None
    encoders: Set[str] = dataclasses.field(default_factory=set)

    # NVENC (NVIDIA)
    has_nvenc_hevc: bool = False
    has_nvenc_h264: bool = False
    has_nvenc_av1: bool = False

    # AMF (AMD)
    has_amf_hevc: bool = False
    has_amf_h264: bool = False
    has_amf_av1: bool = False

    # QSV (Intel)
    has_qsv_hevc: bool = False
    has_qsv_h264: bool = False
    has_qsv_av1: bool = False

    # CPU
    has_libx264: bool = False
    has_libx265: bool = False
    has_libsvtav1: bool = False


@dataclasses.dataclass
class EncoderConfig:
    codec: str
    vendor: str  # "nvidia", "amd", "intel", "cpu"
    args: List[str]
    description: str
    is_hardware: bool


class HardwareDetector:
    _cached_gpus: Optional[List[GPUInfo]] = None
    _cached_ffmpeg: Optional[FFmpegCapabilities] = None

    @classmethod
    def detect_gpus(cls, force_refresh: bool = False) -> List[GPUInfo]:
        """
        Wykrywa wszystkie karty graficzne w systemie operacyjnym (Windows / Linux).
        """
        if cls._cached_gpus is not None and not force_refresh:
            return cls._cached_gpus

        gpus: List[GPUInfo] = []

        # 1. Windows: Win32_VideoController przez PowerShell CIM
        try:
            ps_cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name, DriverVersion, AdapterRAM, Status | "
                "ConvertTo-Json -Compress"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                if isinstance(data, dict):
                    data = [data]

                for item in data:
                    name = item.get("Name") or "Unknown GPU"
                    driver = item.get("DriverVersion")
                    vram = item.get("AdapterRAM")
                    status = item.get("Status")

                    # Określenie producenta
                    name_lower = name.lower()
                    if any(x in name_lower for x in ["nvidia", "geforce", "quadro", "rtx", "gtx", "tesla"]):
                        vendor = "nvidia"
                    elif any(x in name_lower for x in ["amd", "radeon", "advanced micro devices"]):
                        vendor = "amd"
                    elif any(x in name_lower for x in ["intel", "arc", "iris", "uhd graphics", "hd graphics"]):
                        vendor = "intel"
                    else:
                        vendor = "unknown"

                    gpus.append(GPUInfo(
                        name=name,
                        vendor=vendor,
                        driver_version=driver,
                        vram_bytes=vram if isinstance(vram, int) else None,
                        status=status
                    ))
        except Exception:
            pass

        # Dokładne sprawdzenie VRAM dla NVIDIA przez nvidia-smi (WMI często obcina AdapterRAM do 4GB)
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                nv_lines = res.stdout.strip().splitlines()
                for i, line in enumerate(nv_lines):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        name = parts[0]
                        driver = parts[1]
                        vram_mb = int(parts[2])
                        vram_bytes = vram_mb * 1024 * 1024
                        # Zaktualizuj istniejący wpis NVIDIA lub dodaj
                        matched = False
                        for g in gpus:
                            if g.vendor == "nvidia":
                                g.vram_bytes = vram_bytes
                                if not g.driver_version:
                                    g.driver_version = driver
                                matched = True
                                break
                        if not matched:
                            gpus.append(GPUInfo(
                                name=name,
                                vendor="nvidia",
                                driver_version=driver,
                                vram_bytes=vram_bytes,
                                status="OK"
                            ))
        except Exception:
            pass

        # Jeśli nadal brak wykrytych GPU, oznacz CPU
        if not gpus:
            gpus.append(GPUInfo(
                name="Standard Display / CPU",
                vendor="cpu",
                status="OK"
            ))

        cls._cached_gpus = gpus
        return gpus

    @classmethod
    def get_primary_gpu(cls) -> GPUInfo:
        """
        Zwraca główną dedykowaną kartę graficzną lub pierwszą dostępną.
        Priorytet: Dedykowana NVIDIA > Dedykowana AMD > Dedykowana Intel > Zintegrowana > CPU.
        """
        gpus = cls.detect_gpus()
        for g in gpus:
            if g.vendor == "nvidia":
                return g
        for g in gpus:
            if g.vendor == "amd" and g.is_dedicated:
                return g
        for g in gpus:
            if g.vendor == "intel" and g.is_dedicated:
                return g
        for g in gpus:
            if g.vendor in ["amd", "intel"]:
                return g
        return gpus[0]

    @classmethod
    def get_cpu_name(cls) -> str:
        """Zwraca dokładną nazwę procesora CPU (np. AMD Ryzen 7 7730U lub Intel Core i7-8700)."""
        import platform
        import sys
        if sys.platform == "win32":
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip().splitlines()[0].strip()
            except Exception:
                pass
        return platform.processor() or "Standard CPU"

    @classmethod
    def get_model_info(cls, model_name: str) -> Tuple[str, str, str, float]:
        """
        Rozpoznaje klasę wielkości modelu YOLO na podstawie nazwy pliku.
        Zwraca: (tier_code, tier_friendly_name, approx_params, min_vram_gb)
        """
        stem = Path(model_name).stem.lower()
        if stem.endswith("x") or stem.endswith("e"):
            return "xlarge", "Extra Large (flagowy)", "~57-68M parametrów", 4.0
        elif stem.endswith("l"):
            return "large", "Large (duży)", "~43M parametrów", 3.0
        elif stem.endswith("m") or stem.endswith("c"):
            return "medium", "Medium (średni)", "~26M parametrów", 2.0
        elif stem.endswith("s"):
            return "small", "Small (mały)", "~11M parametrów", 1.0
        elif stem.endswith("n"):
            return "nano", "Nano (lekki / mobilny)", "~3M parametrów", 0.5
        return "nano", "Standard (nieznany)", "~3M parametrów", 0.5

    @classmethod
    def validate_yolo_model_compatibility(
        cls,
        model_name: str,
        requested_device: str = "cuda"
    ) -> Tuple[bool, Optional[str]]:
        """
        Waliduje, czy dostępny sprzęt (GPU/VRAM/CPU) jest w stanie pomieścić i wydajnie
        uruchomić wybrany model YOLO.
        
        Jeśli model jest zbyt ciężki (np. xlarge, large) dla wykrytego sprzętu:
        - identyfikuje wykryte karty w systemie (np. AMD Radeon, Intel Iris) lub procesor CPU,
        - zwraca (False, sformatowany_komunikat) z dokładną instrukcją konfiguracji.
        """
        tier_code, tier_name, params_str, min_vram = cls.get_model_info(model_name)

        # Modele lekkie (Nano, Small) są dopuszczalne na każdym sprzęcie (również CPU)
        if tier_code in ["nano", "small"]:
            return True, None

        # Sprawdź dostępność akceleracji CUDA w PyTorch
        has_cuda = False
        cuda_vram_gb = 0.0
        cuda_gpu_name = ""
        try:
            import torch
            has_cuda = torch.cuda.is_available()
            if has_cuda:
                cuda_gpu_name = torch.cuda.get_device_name(0)
                cuda_vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
        except Exception:
            has_cuda = False

        # Przypadek 1: Dedykowana karta NVIDIA z CUDA i odpowiednią ilością VRAM
        if has_cuda and cuda_vram_gb >= min_vram:
            return True, None

        # Przypadek 2: Karta NVIDIA wykryta, ale ma zbyt mało VRAM na ten model
        if has_cuda and cuda_vram_gb < min_vram:
            sep = "=" * 70
            err_msg = (
                f"\n{sep}\n"
                f"  BŁĄD SPRZĘTOWY - ZA MAŁO PAMIĘCI VRAM DLA MODELU '{model_name}'!\n"
                f"{sep}\n"
                f"  Wybrany model:        '{model_name}' ({tier_name}, {params_str})\n"
                f"  Wymagany VRAM:        min. {min_vram:.1f} GB VRAM\n"
                f"  Wykryta karta GPU:    {cuda_gpu_name} ({cuda_vram_gb:.1f} GB VRAM)\n\n"
                f"  Karta graficzna posiada zbyt mało pamięci VRAM, aby pomieścić ten model.\n"
                f"  Próba uruchomienia grozi natychmiastowym błędem Out of Memory (CUDA OOM).\n\n"
                f"  CO NALEŻY ZROBIĆ:\n"
                f"  Otwórz plik 'config.yaml' i w sekcji 'video_analysis' zmień model na lżejszy:\n\n"
                f"  video_analysis:\n"
                f"    yolo_model: \"yolo11s.pt\"   # lub \"yolo11n.pt\"\n"
                f"    device: \"cuda\"\n"
                f"    batch_size: 8             # dopasowana wielkość paczki\n"
                f"{sep}\n"
            )
            return False, err_msg

        # Przypadek 3: Brak karty z obsługą CUDA (np. tylko CPU lub zintegrowana grafika AMD/Intel)
        detected_gpus = cls.detect_gpus()
        cpu_name = cls.get_cpu_name()

        gpu_descriptions = []
        for g in detected_gpus:
            if g.vendor != "cpu":
                vram_info = f", {g.vram_gb:.1f} GB VRAM" if g.vram_gb else ""
                gpu_descriptions.append(f"{g.name} ({g.vendor.upper()}{vram_info})")

        if gpu_descriptions:
            gpu_summary = ", ".join(gpu_descriptions)
            gpu_note = (
                f"  * Wykryta karta GPU:  {gpu_summary}\n"
                f"    (Karta nie obsługuje środowiska NVIDIA CUDA w PyTorch dla Windows)\n"
            )
        else:
            gpu_note = "  * Karta graficzna:    Brak dedykowanej karty graficznej GPU (tylko CPU)\n"

        sep = "=" * 70
        err_msg = (
            f"\n{sep}\n"
            f"  BŁĄD SPRZĘTOWY - MODEL AI JEST ZBYT WYMAGAJĄCY DLA TEGO KOMPUTERA!\n"
            f"{sep}\n"
            f"  Wybrany model:        '{model_name}' ({tier_name}, {params_str})\n\n"
            f"  Wykryty sprzęt w tym komputerze:\n"
            f"{gpu_note}"
            f"  * Procesor CPU:       {cpu_name}\n\n"
            f"  DLACZEGO PROGRAM PRZERWAŁ DZIAŁANIE:\n"
            f"  Model '{model_name}' to bardzo wymagająca sieć neuronowa przeznaczona\n"
            f"  do uruchamiania na dedykowanych kartach graficznych NVIDIA (min. {min_vram:.1f} GB VRAM).\n"
            f"  Na tym komputerze brak akceleracji CUDA dla tak dużego modelu.\n"
            f"  Próba uruchomienia go na procesorze CPU lub zintegrowanej grafice spowodowałaby\n"
            f"  drastyczny spadek wydajności (nawet 1-3 sekundy na 1 klatkę wideo, co dla całego\n"
            f"  materiału oznacza wiele godzin pracy) oraz silne nagrzewanie procesora.\n\n"
            f"  CO NALEŻY ZROBIĆ:\n"
            f"  Otwórz plik 'config.yaml' i w sekcji 'video_analysis' zamień model na wersję lekką:\n\n"
            f"  video_analysis:\n"
            f"    yolo_model: \"yolo11n.pt\"   # lub \"yolov8n.pt\" (zoptymalizowany pod procesor CPU)\n"
            f"    device: \"cpu\"\n"
            f"    batch_size: 4             # optymalna paczka dla procesora bez dedykowanego GPU\n\n"
            f"  Wskazówka: Model 'yolo11n.pt' (Nano) policzy się na Twoim procesorze\n"
            f"  błyskawicznie, zużywając ułamek pamięci RAM i nie przegrzewając komputera!\n"
            f"{sep}\n"
        )
        return False, err_msg


    @classmethod
    def audit_ffmpeg(cls, force_refresh: bool = False) -> FFmpegCapabilities:
        """
        Bada zainstalowany plik binarny FFmpeg i sprawdza wkompilowane enkodery wideo.
        """
        if cls._cached_ffmpeg is not None and not force_refresh:
            return cls._cached_ffmpeg

        caps = FFmpegCapabilities()
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            for cand in [Path("C:/ffmpeg/bin/ffmpeg.exe"), Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe")]:
                if cand.exists():
                    ffmpeg_exe = str(cand)
                    break

        if not ffmpeg_exe:
            cls._cached_ffmpeg = caps
            return caps

        caps.available = True
        caps.path = ffmpeg_exe

        # Wersja FFmpeg
        try:
            ver_res = subprocess.run([ffmpeg_exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
            if ver_res.returncode == 0:
                first_line = ver_res.stdout.splitlines()[0] if ver_res.stdout.splitlines() else ""
                caps.version_str = first_line.strip()
        except Exception:
            caps.version_str = "FFmpeg (unknown version)"

        # Enkodery
        try:
            enc_res = subprocess.run([ffmpeg_exe, "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if enc_res.returncode == 0:
                output = enc_res.stdout
                encoders = set(re.findall(r"\b([a-zA-Z0-9_-]+)\s+[A-Z\.]+\s+", output))
                caps.encoders = encoders

                # NVENC
                caps.has_nvenc_hevc = "hevc_nvenc" in output
                caps.has_nvenc_h264 = "h264_nvenc" in output
                caps.has_nvenc_av1 = "av1_nvenc" in output

                # AMF
                caps.has_amf_hevc = "hevc_amf" in output
                caps.has_amf_h264 = "h264_amf" in output
                caps.has_amf_av1 = "av1_amf" in output

                # QSV
                caps.has_qsv_hevc = "hevc_qsv" in output
                caps.has_qsv_h264 = "h264_qsv" in output
                caps.has_qsv_av1 = "av1_qsv" in output

                # CPU
                caps.has_libx264 = "libx264" in output
                caps.has_libx265 = "libx265" in output
                caps.has_libsvtav1 = "libsvtav1" in output
        except Exception:
            pass

        cls._cached_ffmpeg = caps
        return caps

    @classmethod
    def get_diagnostics(cls) -> List[str]:
        """
        Generuje inteligentne wskazówki i ostrzeżenia dla użytkownika na podstawie
        zbieżności posiadanej karty graficznej i możliwości FFmpeg.
        """
        gpu = cls.get_primary_gpu()
        caps = cls.audit_ffmpeg()
        hints: List[str] = []

        if not caps.available:
            hints.append("[bold red][BLAD][/bold red] Nie znaleziono programu FFmpeg w PATH! Zainstaluj FFmpeg.")
            return hints

        # Przypadek 1: Karta AMD Radeon
        if gpu.vendor == "amd":
            if not caps.has_amf_hevc and not caps.has_amf_h264:
                hints.append(
                    f"[bold yellow][UWAGA][/bold yellow] Wykryto karte AMD Radeon ({gpu.name}), ale Twoj FFmpeg NIE POSIADA wkompilowanego enkodera AMF (brak 'hevc_amf' / 'h264_amf').\n"
                    f"[bold cyan][WSKAZOWKA - jak przyspieszyc render 5-10x]:[/bold cyan]\n"
                    f"  Pobierz pelna wersje FFmpeg z wkompilowanym AMF:\n"
                    f"  -> https://www.gyan.dev/ffmpeg/builds/ (wybierz 'ffmpeg-git-full.7z' lub 'ffmpeg-release-full.7z')\n"
                    f"  Rozpakuj i podmien plik ffmpeg.exe lub dodaj katalog bin do PATH.\n"
                    f"[yellow][TRYB AWARYJNY]:[/yellow] System montazu automatycznie przelacza sie na stabilny enkoder procesora (CPU libx264)."
                )

        # Przypadek 2: Karta NVIDIA GeForce / RTX
        elif gpu.vendor == "nvidia":
            if not caps.has_nvenc_hevc and not caps.has_nvenc_h264:
                hints.append(
                    f"[bold yellow][UWAGA][/bold yellow] Wykryto karte NVIDIA ({gpu.name}), ale Twoj FFmpeg nie posiada wsparcia NVENC.\n"
                    f"[bold cyan][WSKAZOWKA]:[/bold cyan] Pobierz pelny build FFmpeg ze wsparciem NVENC (https://www.gyan.dev/ffmpeg/builds/ wersja 'full').\n"
                    f"[yellow][TRYB AWARYJNY]:[/yellow] Renderowanie bedzie uzywac procesora CPU (libx264)."
                )

        # Przypadek 3: Karta Intel Arc / Iris
        elif gpu.vendor == "intel":
            if not caps.has_qsv_hevc and not caps.has_qsv_h264:
                hints.append(
                    f"[bold yellow][UWAGA][/bold yellow] Wykryto uklad graficzny Intel ({gpu.name}), ale FFmpeg nie posiada wsparcia Intel QuickSync (QSV).\n"
                    f"[bold cyan][WSKAZOWKA]:[/bold cyan] Pobierz pelny build FFmpeg z obsluga QSV ('hevc_qsv')."
                )

        # Przypadek 4: Brak dedykowanego GPU lub CPU
        elif gpu.vendor == "cpu" or not gpu.is_dedicated:
            hints.append(
                "[INFO] Praca na procesorze CPU: Nie wykryto dedykowanej karty graficznej ze sprzetowa akceleracja wideo.\n"
                "Renderowanie odbywa sie przy uzyciu wielowatkowego enkodera CPU (libx264)."
            )

        return hints

    @classmethod
    def get_encoder_config(
        cls,
        target_mode: str = "final",  # "final" lub "preview"
        requested_codec: str = "auto",
        cq: Optional[int] = None,
        preset: Optional[str] = None,
        tune: Optional[str] = None
    ) -> EncoderConfig:
        """
        Zwraca precyzyjnie skonstruowaną konfigurację wiersza poleceń FFmpeg dla danego enkodera.
        Gwarantuje, że nie zostaną przekazane niekompatybilne parametry (np. -cq do libx264 lub -tune hq do AMF).
        """
        gpu = cls.get_primary_gpu()
        caps = cls.audit_ffmpeg()

        codec = requested_codec.lower().strip() if requested_codec else "auto"

        # 1. Automatyczny dobór kodeka
        if codec == "auto":
            if gpu.vendor == "nvidia" and (caps.has_nvenc_hevc or caps.has_nvenc_h264):
                if target_mode == "final":
                    codec = "hevc_nvenc" if caps.has_nvenc_hevc else "h264_nvenc"
                else:
                    codec = "h264_nvenc" if caps.has_nvenc_h264 else "hevc_nvenc"
            elif gpu.vendor == "amd" and (caps.has_amf_hevc or caps.has_amf_h264):
                if target_mode == "final":
                    codec = "hevc_amf" if caps.has_amf_hevc else "h264_amf"
                else:
                    codec = "h264_amf" if caps.has_amf_h264 else "hevc_amf"
            elif gpu.vendor == "intel" and (caps.has_qsv_hevc or caps.has_qsv_h264):
                if target_mode == "final":
                    codec = "hevc_qsv" if caps.has_qsv_hevc else "h264_qsv"
                else:
                    codec = "h264_qsv" if caps.has_qsv_h264 else "hevc_qsv"
            else:
                codec = "libx264"

        # 2. Weryfikacja dostępności żądanego kodeka w FFmpeg (fallback jeśli brak)
        if "nvenc" in codec and not (caps.has_nvenc_hevc or caps.has_nvenc_h264):
            codec = "libx264"
        elif "amf" in codec and not (caps.has_amf_hevc or caps.has_amf_h264):
            codec = "libx264"
        elif "qsv" in codec and not (caps.has_qsv_hevc or caps.has_qsv_h264):
            codec = "libx264"

        # 3. Budowa dedykowanych argumentów FFmpeg
        if "nvenc" in codec:
            # --- NVIDIA NVENC ---
            p = preset or ("p6" if target_mode == "final" else "p1")
            q = str(cq if cq is not None else (19 if target_mode == "final" else 34))
            t = tune or "hq"
            if target_mode == "final":
                args = [
                    "-c:v", codec,
                    "-preset", p,
                    "-tune", t,
                    "-rc", "vbr",
                    "-cq", q,
                    "-b:v", "0"
                ]
            else:
                args = [
                    "-c:v", codec,
                    "-preset", p,
                    "-rc", "vbr",
                    "-cq", q
                ]
            desc = f"NVIDIA NVENC ({codec.upper()}) [Hardware GPU]"
            return EncoderConfig(codec=codec, vendor="nvidia", args=args, description=desc, is_hardware=True)

        elif "amf" in codec:
            # --- AMD AMF ---
            q_val = str(cq if cq is not None else (19 if target_mode == "final" else 32))
            quality_mode = "quality" if target_mode == "final" else "speed"
            args = [
                "-c:v", codec,
                "-quality", quality_mode,
                "-rc", "cqp",
                "-qp_i", q_val,
                "-qp_p", q_val
            ]
            desc = f"AMD AMF ({codec.upper()}) [Hardware GPU]"
            return EncoderConfig(codec=codec, vendor="amd", args=args, description=desc, is_hardware=True)

        elif "qsv" in codec:
            # --- INTEL QuickSync (QSV) ---
            q_val = str(cq if cq is not None else (19 if target_mode == "final" else 32))
            p = "quality" if target_mode == "final" else "veryfast"
            args = [
                "-c:v", codec,
                "-preset", p,
                "-global_quality", q_val
            ]
            desc = f"Intel QuickSync ({codec.upper()}) [Hardware GPU]"
            return EncoderConfig(codec=codec, vendor="intel", args=args, description=desc, is_hardware=True)

        elif "libx265" in codec:
            # --- CPU H.265 ---
            q_val = str(cq if cq is not None else (22 if target_mode == "final" else 32))
            p = preset or ("fast" if target_mode == "final" else "ultrafast")
            args = [
                "-c:v", "libx265",
                "-preset", p,
                "-crf", q_val
            ]
            desc = "CPU H.265 (libx265) [Software]"
            return EncoderConfig(codec="libx265", vendor="cpu", args=args, description=desc, is_hardware=False)

        else:
            # --- CPU H.264 (libx264) Fallback ---
            q_val = str(cq if cq is not None else (19 if target_mode == "final" else 30))
            p = preset or ("fast" if target_mode == "final" else "ultrafast")
            args = [
                "-c:v", "libx264",
                "-preset", p,
                "-crf", q_val
            ]
            desc = "CPU H.264 (libx264) [Software Universal]"
            return EncoderConfig(codec="libx264", vendor="cpu", args=args, description=desc, is_hardware=False)

    @classmethod
    def print_startup_banner(cls, console_out=None) -> None:
        """
        Drukuje czytelną tabelę diagnostyczną sprzętu i silnika FFmpeg na starcie programu.
        """
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            c = console_out or Console()
        except ImportError:
            c = None

        primary_gpu = cls.get_primary_gpu()
        caps = cls.audit_ffmpeg()
        hints = cls.get_diagnostics()

        final_enc = cls.get_encoder_config(target_mode="final", requested_codec="auto")
        preview_enc = cls.get_encoder_config(target_mode="preview", requested_codec="auto")

        if c:
            table = Table(title="[bold cyan]SPRZET I SILNIK RENDEROWANIA AI MONTAGE[/bold cyan]", show_header=True, header_style="bold magenta")
            table.add_column("Komponent", style="cyan", width=24)
            table.add_column("Wykryta konfiguracja / Status", style="green")

            vram_str = f" ({primary_gpu.vram_gb} GB VRAM)" if primary_gpu.vram_gb else ""
            driver_str = f" [dim]sterownik {primary_gpu.driver_version}[/dim]" if primary_gpu.driver_version else ""
            table.add_row("Karta graficzna (GPU)", f"[bold white]{primary_gpu.name}[/bold white]{vram_str}{driver_str}")

            if caps.available:
                hw_list = []
                if caps.has_nvenc_hevc or caps.has_nvenc_h264:
                    hw_list.append("[green]NVENC (NVIDIA)[/green]")
                if caps.has_amf_hevc or caps.has_amf_h264:
                    hw_list.append("[green]AMF (AMD)[/green]")
                if caps.has_qsv_hevc or caps.has_qsv_h264:
                    hw_list.append("[green]QSV (Intel)[/green]")
                if not hw_list:
                    hw_list.append("[yellow]Brak akceleracji sprzetowej (tylko CPU)[/yellow]")
                hw_str = ", ".join(hw_list)

                table.add_row("Silnik FFmpeg", f"[bold white]{caps.path}[/bold white]\n[dim]{caps.version_str}[/dim]")
                table.add_row("Wspierany sprzet FFmpeg", hw_str)
            else:
                table.add_row("Silnik FFmpeg", "[bold red]NIE ZNALEZIONO W PATH![/bold red]")

            table.add_row("Profil Final 4K Master", f"[bold yellow]{final_enc.description}[/bold yellow]")
            table.add_row("Profil Preview Draft", f"[dim]{preview_enc.description}[/dim]")

            c.print(table)

            if hints:
                for hint in hints:
                    c.print(Panel(hint, title="[bold yellow]Diagnostyka i Rekomendacja[/bold yellow]", border_style="yellow"))
        else:
            print(f"=== GPU: {primary_gpu.name} | FFmpeg: {caps.path} | Encoder: {final_enc.description} ===")
            for h in hints:
                print(f"HINT: {h}")
