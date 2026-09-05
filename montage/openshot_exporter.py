"""
Moduł eksportu projektu OpenShot Video Editor (.osp).
Generuje pliki projektu zgodne z OpenShot Video Editor 4.0.0 / libopenshot 1.0.0:
- montage_openshot_4K.osp   (z plikami 4K z materialy_oryginalne)
- montage_openshot_480p.osp (z plikami proxy z kopie_robocze_480p)
"""

import copy
import json
import os
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.config_loader import Config
from utils.helpers import find_matching_original
from utils.logger import console, logger

_MEDIA_PROBE_CACHE: Dict[str, Dict[str, Any]] = {}


def parse_fraction(s: Any, default_num: int = 1, default_den: int = 1) -> Dict[str, int]:
    """Bezpiecznie parsuje ułamek w postaci stringa 'num/den' na słownik {'num': int, 'den': int}."""
    if not s or "/" not in str(s):
        return {"num": default_num, "den": default_den}
    parts = str(s).split("/")
    if len(parts) == 2:
        try:
            n, d = int(parts[0]), int(parts[1])
            if d > 0:
                return {"num": n, "den": d}
        except Exception:
            pass
    return {"num": default_num, "den": default_den}


def probe_file_media_info(file_path: Path) -> Dict[str, Any]:
    """
    Używa ffprobe do pobrania dokładnych metadanych strumieni (wideo, audio, wymiary, fps, time_base).
    Prawidłowy time_base audio i wideo jest kluczowy dla libopenshot do synchronizacji PTS
    i zapobiegania wyciszaniu odtwarzania muzyki (np. w plikach MP3 time_base to 1/14112000, nie 1/48000).
    """
    key = str(file_path.resolve())
    if key in _MEDIA_PROBE_CACHE:
        return _MEDIA_PROBE_CACHE[key]

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,time_base,channels,sample_rate,channel_layout",
        "-show_entries", "format=duration,size,bit_rate",
        "-of", "json",
        key
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
    except Exception as e:
        logger.debug(f"ffprobe nie powiodło się dla {file_path}: {e}")
        return {}

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    dur = float(fmt.get("duration", 0.0) or 0.0)
    size_str = str(fmt.get("size", "0"))

    has_video = v_stream is not None
    has_audio = a_stream is not None

    # Video details
    width = int(v_stream.get("width", 0)) if v_stream else 0
    height = int(v_stream.get("height", 0)) if v_stream else 0
    vcodec = v_stream.get("codec_name", "") if v_stream else ""
    v_idx = int(v_stream.get("index", -1)) if v_stream else -1

    fps_fraction = parse_fraction(v_stream.get("r_frame_rate") if v_stream else "", 30, 1)
    if fps_fraction["num"] == 0 or fps_fraction["den"] == 0:
        fps_fraction = parse_fraction(v_stream.get("avg_frame_rate") if v_stream else "", 30, 1)

    v_timebase = parse_fraction(v_stream.get("time_base") if v_stream else "", 1, 30)

    # Audio details
    a_idx = int(a_stream.get("index", -1)) if a_stream else -1
    channels = int(a_stream.get("channels", 0)) if a_stream else 0
    sample_rate = int(a_stream.get("sample_rate", 0)) if a_stream else 0
    acodec = a_stream.get("codec_name", "") if a_stream else ""
    channel_layout = 3 if channels == 2 else (1 if channels == 1 else 0)
    a_timebase = parse_fraction(a_stream.get("time_base") if a_stream else "", 1, sample_rate or 48000)

    v_len = str(int(dur * fps_fraction["num"] / fps_fraction["den"])) if (has_video and dur > 0 and fps_fraction["den"] > 0) else "0"

    info = {
        "has_video": has_video,
        "video_stream_index": v_idx,
        "width": width,
        "height": height,
        "fps": fps_fraction,
        "vcodec": vcodec,
        "video_timebase": v_timebase,
        "has_audio": has_audio,
        "audio_stream_index": a_idx,
        "channels": channels,
        "channel_layout": channel_layout,
        "sample_rate": sample_rate,
        "acodec": acodec,
        "audio_timebase": a_timebase,
        "duration": dur,
        "file_size": size_str,
        "video_length": v_len,
    }
    _MEDIA_PROBE_CACHE[key] = info
    return info


def generate_openshot_id(length: int = 10) -> str:
    """Generuje unikalny alfanumeryczny identyfikator w stylu OpenShot."""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))


def _create_default_keyframe(default_y: float = 1.0, interpolation: int = 0) -> Dict[str, Any]:
    """Tworzy standardowy punkt kluczowy dla libopenshot / OpenShot Video Editor."""
    return {
        "Points": [
            {
                "co": {"X": 1.0, "Y": float(default_y)},
                "interpolation": interpolation
            }
        ]
    }



class OpenShotExporter:
    """
    Tworzy pliki projektu OpenShot (.osp) na podstawie storyboardu:
    - wersję 4K z oryginalnych plików wideo
    - wersję 480p z plików proxy
    """

    def __init__(self, config: Config):
        self.config = config

    def export_both_projects(
        self,
        storyboard_data: Dict[str, Any]
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Generuje oba projekty: 4K oraz 480p.
        """
        p_4k = self.config.storyboard_dir / "montage_openshot_4K.osp"
        p_480p = self.config.storyboard_dir / "montage_openshot_480p.osp"

        res_4k = self.export_project(storyboard_data, output_path=p_4k, use_original_media=True)
        res_480p = self.export_project(storyboard_data, output_path=p_480p, use_original_media=False)

        return res_4k, res_480p

    def export_project(
        self,
        storyboard_data: Dict[str, Any],
        output_path: Optional[Path] = None,
        use_original_media: bool = True
    ) -> Optional[Path]:
        """
        Tworzy i zapisuje pojedynczy plik projektu .osp (4K lub 480p).
        """
        cuts = storyboard_data.get("cuts", [])
        if not cuts:
            logger.warning("Brak ujęć w storyboardzie do eksportu OpenShot.")
            return None

        project_id = generate_openshot_id(10)
        total_duration = float(storyboard_data.get("total_duration", 300.0))

        # Parametry zależne od trybu 4K vs 480p
        if use_original_media:
            mode_name = "4K"
            proj_width = 3840
            proj_height = 2160
            proj_fps = {"num": 60, "den": 1}
            proj_profile = "4K UHD 2160p 60 fps"
            default_out_name = "montage_openshot_4K.osp"
        else:
            mode_name = "480p"
            proj_width = 854
            proj_height = 480
            proj_fps = {"num": 15, "den": 1}
            proj_profile = "FWVGA 480p 15 fps"
            default_out_name = "montage_openshot_480p.osp"

        project_layers = [
            {"id": "L1", "label": "Muzyka", "number": 1000000, "y": 0, "lock": False},
            {"id": "L2", "label": "Wideo", "number": 2000000, "y": 0, "lock": False},
            {"id": "L3", "label": "Tytuly/Efekty", "number": 3000000, "y": 0, "lock": False},
            {"id": "L4", "label": "", "number": 4000000, "y": 0, "lock": False},
            {"id": "L5", "label": "", "number": 5000000, "y": 0, "lock": False}
        ]

        files_list: List[Dict[str, Any]] = []
        clips_list: List[Dict[str, Any]] = []
        registered_files: Dict[str, Dict[str, Any]] = {}  # abs_path -> file_data dict

        # 1. Dodaj plik muzyczny
        music_path = self.config.get_music_file_path()
        if music_path and music_path.exists():
            music_abs = str(music_path.resolve())
            music_file_id = generate_openshot_id(10)
            m_info = probe_file_media_info(music_path)
            music_dur = m_info["duration"] if m_info.get("duration") else total_duration

            music_file_data = {
                "id": music_file_id,
                "path": music_abs,
                "name": music_path.name,
                "media_type": "audio",
                "type": "FFmpegReader",
                "has_audio": True,
                "has_video": False,
                "has_single_image": False,
                "duration": music_dur,
                "file_size": m_info.get("file_size", str(music_path.stat().st_size)),
                "video_length": "0",
                "channels": m_info.get("channels", 2),
                "channel_layout": m_info.get("channel_layout", 3),
                "sample_rate": m_info.get("sample_rate", 48000),
                "width": proj_width,
                "height": proj_height,
                "fps": {"num": 30, "den": 1},
                "display_ratio": {"num": 16, "den": 9},
                "pixel_ratio": {"num": 1, "den": 1},
                "pixel_format": -1,
                "video_bit_rate": 0,
                "video_stream_index": -1,
                "video_timebase": {"num": 1, "den": 30},
                "interlaced_frame": False,
                "top_field_first": True,
                "vcodec": "",
                "acodec": m_info.get("acodec", "mp3"),
                "audio_bit_rate": 0,
                "audio_stream_index": m_info.get("audio_stream_index", 0),
                "audio_timebase": m_info.get("audio_timebase", {"num": 1, "den": 14112000}),
                "metadata": {}
            }
            registered_files[music_abs] = music_file_data
            files_list.append(music_file_data)

            # Klip muzyczny na Layer 1 (głośność 100%)
            music_clip_id = generate_openshot_id(10)
            clips_list.append({
                "id": music_clip_id,
                "file_id": music_file_id,
                "title": music_path.name,
                "position": 0.0,
                "start": 0.0,
                "end": total_duration,
                "duration": total_duration,
                "layer": 1000000,
                "scale": 0,
                "gravity": 4,
                "anchor": 0,
                "display": 0,
                "mixing": 0,
                "composite": 0,
                "waveform": False,
                "waveform_mode": 0,
                "reader": copy.deepcopy(music_file_data),
                "effects": [],
                "alpha": _create_default_keyframe(1.0),
                "scale_x": _create_default_keyframe(1.0),
                "scale_y": _create_default_keyframe(1.0),
                "location_x": _create_default_keyframe(0.0),
                "location_y": _create_default_keyframe(0.0),
                "rotation": _create_default_keyframe(0.0),
                "time": _create_default_keyframe(1.0),
                "volume": _create_default_keyframe(1.0),
                "shear_x": _create_default_keyframe(0.0),
                "shear_y": _create_default_keyframe(0.0),
                "origin_x": _create_default_keyframe(0.5),
                "origin_y": _create_default_keyframe(0.5),
                "channel_filter": _create_default_keyframe(-1.0),
                "channel_mapping": _create_default_keyframe(-1.0),
                "has_audio": _create_default_keyframe(1.0),
                "has_video": _create_default_keyframe(0.0),
                "corner_radius": _create_default_keyframe(0.0),
                "margin": _create_default_keyframe(0.0),
            })

        # 2. Dodaj ujęcia wideo i zdjęcia
        for cut in cuts:
            source_file = cut.get("source_file", "")
            source_type = cut.get("source_type", "video")
            t_start = float(cut.get("timeline_start", 0.0))
            t_end = float(cut.get("timeline_end", 0.0))
            s_start = float(cut.get("source_start", 0.0))
            s_end = float(cut.get("source_end", 0.0))

            target_file_path: Optional[Path] = None

            if source_type == "image":
                img_p = Path(cut.get("image_path", cut.get("proxy_path", source_file)))
                if not img_p.is_absolute():
                    img_p = (self.config.base_dir / img_p).resolve()
                if img_p.exists():
                    target_file_path = img_p
            else:
                raw_proxy_p = Path(cut.get("proxy_path", source_file))
                if raw_proxy_p.exists():
                    proxy_p = raw_proxy_p
                else:
                    proxy_p = (self.config.proxy_dir / Path(source_file).name).resolve()

                if use_original_media:
                    orig_cand = find_matching_original(proxy_p, self.config.original_dir)
                    if orig_cand and orig_cand.exists():
                        target_file_path = orig_cand

                # W trybie 480p lub jako fallback dla braku oryginału
                if target_file_path is None and proxy_p.exists():
                    target_file_path = proxy_p

            if not target_file_path or not target_file_path.exists():
                logger.warning(f"OpenShot Exporter ({mode_name}): Nie znaleziono pliku dla ujęcia {source_file}")
                continue

            target_abs = str(target_file_path.resolve())

            if target_abs not in registered_files:
                f_id = generate_openshot_id(10)
                is_img = source_type == "image" or target_file_path.suffix.lower() in [".jpg", ".jpeg", ".png"]
                p_info = probe_file_media_info(target_file_path)

                dur = (
                    300.0 if is_img 
                    else (p_info["duration"] if p_info.get("duration") else max(s_end, float(cut.get("source_clip_duration", 10.0))))
                )
                f_fps = p_info.get("fps") if (p_info.get("fps") and not is_img) else (proj_fps if not is_img else {"num": 30, "den": 1})
                f_w = p_info.get("width") if p_info.get("width") else (proj_width if not is_img else 1920)
                f_h = p_info.get("height") if p_info.get("height") else (proj_height if not is_img else 1080)
                file_size_str = p_info.get("file_size") if p_info.get("file_size") else (str(target_file_path.stat().st_size) if target_file_path.exists() else "0")
                v_len = p_info.get("video_length") if p_info.get("video_length") else str(int(dur * f_fps["num"] / f_fps["den"]))

                f_has_audio = False if is_img else bool(p_info.get("has_audio", False))
                f_a_idx = -1 if (is_img or not f_has_audio) else p_info.get("audio_stream_index", -1)
                f_channels = 0 if (is_img or not f_has_audio) else p_info.get("channels", 0)
                f_layout = 0 if (is_img or not f_has_audio) else p_info.get("channel_layout", 0)
                f_sr = 0 if (is_img or not f_has_audio) else p_info.get("sample_rate", 0)
                f_acodec = "" if (is_img or not f_has_audio) else p_info.get("acodec", "")

                f_data = {
                    "id": f_id,
                    "path": target_abs,
                    "name": target_file_path.name,
                    "media_type": "image" if is_img else "video",
                    "type": "QtImageReader" if is_img else "FFmpegReader",
                    "has_audio": f_has_audio,
                    "has_video": True,
                    "has_single_image": is_img,
                    "duration": dur,
                    "file_size": file_size_str,
                    "video_length": v_len,
                    "channels": f_channels,
                    "channel_layout": f_layout,
                    "sample_rate": f_sr,
                    "width": f_w,
                    "height": f_h,
                    "fps": f_fps,
                    "display_ratio": {"num": 16, "den": 9},
                    "pixel_ratio": {"num": 1, "den": 1},
                    "pixel_format": -1,
                    "video_bit_rate": 0,
                    "video_stream_index": p_info.get("video_stream_index", 0),
                    "video_timebase": p_info.get("video_timebase", {"num": f_fps["den"], "den": f_fps["num"]}),
                    "interlaced_frame": False,
                    "top_field_first": True,
                    "vcodec": p_info.get("vcodec", ""),
                    "acodec": f_acodec,
                    "audio_bit_rate": 0,
                    "audio_stream_index": f_a_idx,
                    "audio_timebase": p_info.get("audio_timebase", {"num": 1, "den": f_sr if f_sr > 0 else 48000}),
                    "metadata": {}
                }
                files_list.append(f_data)
                registered_files[target_abs] = f_data
            else:
                f_data = registered_files[target_abs]
                f_id = f_data["id"]

            clip_id = generate_openshot_id(10)
            cut_duration = round(s_end - s_start, 3)
            # Wycisz audio z oryginalnych klipów wideo (podkładem jest muzyka)
            clip_dict = {
                "id": clip_id,
                "file_id": f_id,
                "title": target_file_path.name,
                "position": round(t_start, 3),
                "start": round(s_start, 3),
                "end": round(s_end, 3),
                "duration": cut_duration,
                "layer": 2000000,
                "scale": 0,  # SCALE_FIT
                "gravity": 4,  # GRAVITY_CENTER
                "anchor": 0,
                "display": 0,
                "mixing": 0,
                "composite": 0,
                "waveform": False,
                "waveform_mode": 0,
                "reader": copy.deepcopy(f_data),
                "effects": [],
                "alpha": _create_default_keyframe(1.0),
                "scale_x": _create_default_keyframe(1.0),
                "scale_y": _create_default_keyframe(1.0),
                "location_x": _create_default_keyframe(0.0),
                "location_y": _create_default_keyframe(0.0),
                "rotation": _create_default_keyframe(0.0),
                "time": _create_default_keyframe(1.0),
                "volume": _create_default_keyframe(0.0),
                "shear_x": _create_default_keyframe(0.0),
                "shear_y": _create_default_keyframe(0.0),
                "origin_x": _create_default_keyframe(0.5),
                "origin_y": _create_default_keyframe(0.5),
                "channel_filter": _create_default_keyframe(-1.0),
                "channel_mapping": _create_default_keyframe(-1.0),
                "has_audio": _create_default_keyframe(0.0),
                "has_video": _create_default_keyframe(1.0),
                "corner_radius": _create_default_keyframe(0.0),
                "margin": _create_default_keyframe(0.0),
            }
            clips_list.append(clip_dict)


        # 3. Zbuduj projekt OpenShot 4.0.0
        project_data = {
            "id": project_id,
            "fps": proj_fps,
            "display_ratio": {"num": 16, "den": 9},
            "pixel_ratio": {"num": 1, "den": 1},
            "width": proj_width,
            "height": proj_height,
            "sample_rate": 48000,
            "channels": 2,
            "channel_layout": 3,
            "settings": {},
            "clips": clips_list,
            "effects": [],
            "files": files_list,
            "duration": total_duration,
            "scale": 15.0,
            "tick_pixels": 100,
            "playhead_position": 0,
            "profile": proj_profile,
            "export_settings": None,
            "layers": project_layers,
            "markers": [],
            "progress": [],
            "history": {
                "undo": [],
                "redo": []
            },
            "version": {
                "openshot-qt": "4.0.0",
                "libopenshot": "1.0.0"
            }
        }

        # 4. Zapisz plik .osp
        if output_path is None:
            output_path = self.config.storyboard_dir / default_out_name

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(project_data, f, indent=1, ensure_ascii=False)

        console.print(f"[bold green]Projekt OpenShot Video Editor ({mode_name}) zapisany:[/bold green]")
        console.print(f"  • Plik projektu: [cyan]{output_path.resolve()}[/cyan]")
        logger.info(f"Wyeksportowano projekt OpenShot ({mode_name}): {output_path} ({len(clips_list)} klipów)")

        return output_path
