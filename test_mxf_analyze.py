#!/usr/bin/env python3
# test_mxf_analyze.py
# Skrypt testowy do analizy plików MXF przy użyciu ffprobe

import json
import logging
import os
import subprocess
import sys
from typing import Dict, Optional, List

# Konfiguracja logowania
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def find_ffprobe() -> Optional[str]:
    """Znajdź ścieżkę do ffprobe."""
    # Popularne lokalizacje ffprobe
    common_paths = [
        "D:/soft/ffmpeg/bin/ffprobe.exe",  # Ścieżka z logów
        "C:/ffmpeg/bin/ffprobe.exe",
        "C:/Program Files/ffmpeg/bin/ffprobe.exe",
        "/usr/bin/ffprobe",
        "/usr/local/bin/ffprobe"
    ]

    for path in common_paths:
        if os.path.exists(path):
            return path

    # Spróbuj znaleźć w PATH
    try:
        if os.name == 'nt':  # Windows
            result = subprocess.run(["where", "ffprobe"], capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]
        else:  # Linux/Mac
            result = subprocess.run(["which", "ffprobe"], capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except Exception as e:
        logger.error(f"Błąd podczas szukania ffprobe w PATH: {e}")

    return None


def run_ffprobe_commands(file_path: str, ffprobe_path: str) -> None:
    """Uruchom różne komendy ffprobe i pokaż wyniki."""
    if not os.path.exists(file_path):
        logger.error(f"Plik nie istnieje: {file_path}")
        return

    logger.info(f"Analizuję plik: {file_path}")

    # Lista komend do przetestowania
    commands = [
        # Komenda 1: Prosta komenda badająca podstawowe informacje
        {
            "name": "Podstawowa komenda",
            "args": ["-v", "error", "-show_format", "-show_streams", "-of", "json"]
        },
        # Komenda 2: Wyszukiwanie timecode'u
        {
            "name": "Komenda wyszukująca timecode",
            "args": ["-v", "error", "-show_entries", "stream_tags=timecode", "-of", "json"]
        },
        # Komenda 3: Podobna do oryginalnego source_finder
        {
            "name": "Komenda z oryginalnego source_finder",
            "args": ["-v", "error", "-show_entries",
                     "stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,nb_frames,width,height,channels,channel_layout,sample_rate:stream_tags=timecode:format=duration,start_time",
                     "-of", "json", "-sexagesimal"]
        },
        # Komenda 4: Stream v:0
        {
            "name": "Komenda z wyborem pierwszego strumienia wideo",
            "args": ["-v", "error", "-select_streams", "v:0", "-show_entries",
                     "stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,nb_frames,width,height:stream_tags=timecode:format=duration",
                     "-of", "json"]
        },
        # Komenda 5: Stream stream_index=0
        {
            "name": "Komenda z wyborem pierwszego strumienia po indeksie",
            "args": ["-v", "error", "-select_streams", "0", "-show_entries",
                     "stream=index,codec_type,codec_name,duration,r_frame_rate,avg_frame_rate,start_time,nb_frames,width,height:stream_tags=timecode:format=duration",
                     "-of", "json"]
        },
        # Komenda 6: Uproszczona (np. dla MXF)
        {
            "name": "Uproszczona komenda",
            "args": ["-v", "error", "-show_entries",
                     "stream=codec_type,codec_name,r_frame_rate,avg_frame_rate:format=duration:stream_tags=timecode",
                     "-of", "json"]
        }
    ]

    for cmd_info in commands:
        logger.info(f"\n{'=' * 80}\nTestuję: {cmd_info['name']}")

        command = [ffprobe_path] + cmd_info["args"] + [file_path]
        logger.info(f"Komenda: {' '.join(command)}")

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8',
                errors='ignore'
            )

            if result.returncode != 0:
                logger.error(f"Komenda zakończona błędem (kod {result.returncode})")
                if result.stderr:
                    logger.error(f"Komunikat błędu: {result.stderr}")
                continue

            # Spróbuj sparsować JSON
            try:
                data = json.loads(result.stdout)
                logger.info(f"Wynik (JSON):\n{json.dumps(data, indent=2, ensure_ascii=False)}")

                # Dodatkowa analiza danych wyjściowych
                if "streams" in data:
                    logger.info(f"Znaleziono {len(data['streams'])} strumieni")

                    # Szukaj timecode'ów
                    timecodes = []
                    for i, stream in enumerate(data["streams"]):
                        if "tags" in stream and "timecode" in stream["tags"]:
                            timecode = stream["tags"]["timecode"]
                            timecodes.append((i, timecode))
                            logger.info(f"  Stream {i}: Znaleziono timecode: {timecode}")

                    if not timecodes:
                        logger.info("  Nie znaleziono żadnego timecode")

                    # Sprawdź frame rate
                    for i, stream in enumerate(data["streams"]):
                        if "codec_type" in stream and stream["codec_type"] == "video":
                            for rate_key in ["r_frame_rate", "avg_frame_rate"]:
                                if rate_key in stream:
                                    logger.info(f"  Stream {i}: {rate_key} = {stream[rate_key]}")

                # Sprawdź duration
                if "format" in data and "duration" in data["format"]:
                    logger.info(f"Duration z format: {data['format']['duration']}")

            except json.JSONDecodeError:
                logger.error("Nie można sparsować wyniku jako JSON")
                logger.info(f"Surowy wynik:\n{result.stdout}")

        except Exception as e:
            logger.error(f"Błąd podczas wykonywania komendy: {e}")


if __name__ == "__main__":
    # Obsługa argumentów wiersza poleceń
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = r"A:\__ORYGINAL_POST__\_Mario\Visa_mxf_lut\A001C012_220101J6.mxf"  # Domyślna ścieżka

    # Znajdź ffprobe
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        logger.error("Nie można znaleźć ffprobe! Proszę podać pełną ścieżkę jako drugi argument.")
        if len(sys.argv) > 2:
            ffprobe_path = sys.argv[2]
        else:
            sys.exit(1)

    logger.info(f"Używam ffprobe: {ffprobe_path}")
    run_ffprobe_commands(file_path, ffprobe_path)
