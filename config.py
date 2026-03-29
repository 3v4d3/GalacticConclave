"""config.py — Application paths, config load/save, and input validation."""

import json
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME    = "GalacticConclave"
CONFIG_DIR  = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_SAVE_DIR = (
    Path.home()
    / "Documents"
    / "Paradox Interactive"
    / "Stellaris"
    / "save games"
)

def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"WARNING: Config file corrupted ({e}). Starting fresh.", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"ERROR loading config: {e}", file=sys.stderr)
        return {}

def save_config(cfg: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"WARNING: Failed to save config: {e}", file=sys.stderr)

def validate_save_dir(path: str) -> bool:
    try:
        p = Path(path)
        return p.exists() and p.is_dir() and os.access(p, os.R_OK)
    except Exception:
        return False

def validate_console_key(key: str) -> bool:
    return len((key or "").strip()) == 1

# ── Logging setup (v0.6) ───────────────────────────────────────────────────────

def setup_logging():
    """Configure logging to file in CONFIG_DIR with rotation.
    Returns a logger configured for the app. Safe to call multiple times.
    Logs to CONFIG_DIR / "galactic_conclave.log" with 5 MB rotation.
    """
    log_file = CONFIG_DIR / "galactic_conclave.log"
    
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("galcon")
    logger.setLevel(logging.DEBUG)
    
    if not logger.handlers:
        handler = RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=3
        )
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

# ── Game directory validation (v0.6) ──────────────────────────────────────────

def validate_game_dir(path: str) -> tuple[bool, str]:
    """Verify game directory exists, is accessible, and is writable.
    Returns (is_valid, diagnostic_message).
    Diagnostic messages are user-friendly and actionable.
    """
    try:
        p = Path(path)
        if not p.exists():
            return False, f"Directory does not exist: {path}"
        if not p.is_dir():
            return False, f"Not a directory: {path}"
        if not os.access(p, os.R_OK):
            return False, f"Directory is not readable: {path}"
        if not os.access(p, os.W_OK):
            return False, (
                f"Directory is not writable: {path}\n"
                "SOLUTION: Run Galactic Conclave as Administrator, or grant write permissions."
            )
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(dir=p, delete=True):
                pass
            return True, "Game directory is valid and writable."
        except PermissionError:
            return False, f"Cannot write to {path}. Run as Administrator."
    except Exception as e:
        return False, f"Error validating directory: {e}"