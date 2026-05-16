"""
Sistema de logging do bot
"""

import logging
import os
import sys
from pathlib import Path
import io


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna um logger com handlers de console e arquivo."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console: force UTF-8 encoding for the stream to avoid
    # UnicodeEncodeError on Windows consoles/files configured with CP1252.
    try:
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        # Fallback if stdout has no buffer (e.g. some test harnesses)
        stream = sys.stdout

    ch = logging.StreamHandler(stream)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Em Windows/OneDrive, rotação do arquivo costuma falhar por lock externo.
    # Para evitar spam de traceback, usamos append simples no Windows.
    if os.name == "nt":
        fh = logging.FileHandler(log_dir / "bot.log", encoding="utf-8")
    else:
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
