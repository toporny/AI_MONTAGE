"""
Moduł logowania z obsługą biblioteki Rich oraz zapisu do pliku.
"""

import logging
import sys
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler

console = Console()

def setup_logger(log_file: str = "montage.log", level: int = logging.INFO) -> logging.Logger:
    """
    Konfiguruje główny logger aplikacji:
    - kolorowe wyjście w konsoli (RichHandler)
    - szczegółowy zapis do pliku logów
    """
    logger = logging.getLogger("AI_MONTAGE")
    logger.setLevel(level)

    # Zapobieganie dublowaniu handlerów przy wielokrotnym wywołaniu
    if logger.handlers:
        return logger

    # Handler konsolowy Rich
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True
    )
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # Handler plikowy
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        console.print(f"[yellow]Ostrzeżenie: Nie udało się utworzyć pliku logów {log_file}: {e}[/yellow]")

    return logger

logger = setup_logger()
