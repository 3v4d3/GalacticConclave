"""game_io.py — Intent detection, keyword classification, and console injection (batch‑only)."""

import json
import re
import sys
import time
import logging
import hashlib
from pathlib import Path
from datetime import datetime

import llm_client
from llm_client import MAX_TOKENS_CLASSIFIER, _current_provider

# ── Enclave civic sets ──────────────────────────────────────────────────────

ENCLAVE_CIVICS = {
    "civic_trading_conglomerate",
    "civic_ancient_preservers",
    "civic_salvager_enclave",
    "civic_artist_collective",
    "civic_free_traders",
}

ENCLAVE_BLOCKED_INTENTS = {"NAP_ACCEPTED", "INSULT", "WAR_DECLARED", "TRUST_UP", "TRUST_DOWN"}
ENCLAVE_ONLY_INTENTS = {"TRADE_DEAL", "TRADE_TECH", "TRADE_ENERGY", "TRADE_MINERALS"}

# ── Intent → (console_command_template, display_label) ───────────────────────

INTENT_MAP = {
    "OPINION_UP": ("add_opinion {tag} 0 40", "Grant Goodwill (+40)"),
    "OPINION_DOWN": ("add_opinion {tag} 0 -30", "Lodge Grievance (-30)"),
    "TRUST_UP": ("add_opinion {tag} 0 20", "+20 Trust"),
    "TRUST_DOWN": ("add_opinion {tag} 0 -20", "-20 Trust"),
    "NAP_ACCEPTED": ("add_opinion {tag} 0 50", "Non-Aggression (+50)"),
    "TRADE_ENERGY": ("energy 500", "+500 Energy (receiving)"),
    "TRADE_MINERALS": ("minerals 500", "+500 Minerals (receiving)"),
    "TRADE_DEAL": ("energy 250", "Trade Concluded (+250 Energy)"),
    "TRADE_TECH": ("physics 500", "+500 Physics Research"),
    "INSULT": ("add_opinion {tag} 0 -40", "Register Insult (-40)"),
    "WAR_DECLARED": ("add_opinion 0 {tag} -100", "Declare War (-100 opinion)"),
    "NONE": (None, None),
}

# ── LLM classifier prompt ─────────────────────────────────────────────────────

CLASSIFIER_PROMPT = """Classify the diplomatic intent of a message from an interstellar empire.
Return ONLY valid JSON, no other text:
{
  "intent": "OPINION_UP|OPINION_DOWN|TRUST_UP|TRUST_DOWN|NAP_ACCEPTED|TRADE_ENERGY|TRADE_MINERALS|TRADE_TECH|TRADE_DEAL|INSULT|WAR_DECLARED|NONE",
  "confidence": "high|medium",
  "direction": "receiving|giving|neutral",
  "reason": "one sentence max"
}

RETURN NONE FOR ALMOST EVERYTHING.
Only classify when you see the exact patterns below.

WAR_DECLARED — ONLY these count:
  YES: "We declare war on you", "Our fleets are en route to your worlds", "Hostilities commence now"
  NO: "territory under consideration", "strategic sweep", "you will identify yourself", "state your purpose",
      "non-regulation greeting", "we have reached out", "we do not tolerate", ANY assertive or demanding tone

INSULT — ONLY these count:
  YES: "contemptible", "beneath us", "unworthy", "your kind are inferior", explicit degradation
  NO: "this is not acceptable", "incorrect protocol", "misguided", "we do not engage with", tone of disapproval

NAP_ACCEPTED — ONLY when peace/non-aggression is explicitly agreed by BOTH sides:
  YES: "we accept your non-aggression proposal", "ceasefire agreed", "peace is established"
  NO: "we recognize you", "we will process your transmission", "we have reached out", introductions

OPINION_UP — ONLY explicit gratitude for a specific action the player just took
OPINION_DOWN — ONLY explicit grievance naming a specific player action
TRUST_UP/DOWN — ONLY explicit statement about trust or betrayal
TRADE_DEAL — ONLY when a trade is explicitly concluded with trigger words:
  "terms agreed", "deal concluded", "shipments dispatched", "treaty ratified", "signatures synchronized"

direction field (TRADE only):
- "receiving": player receives resource
- "giving": player pays resource
- "neutral": mutual or unclear

If unsure: NONE. If assertive but not explicit: NONE.
If introducing or probing: NONE."""

# ── Keyword pre-filter lists ──────────────────────────────────────────────────

_KW_WAR = [
    "declare war", "war is declared", "hostilities commence", "fleets are en route",
    "your worlds will burn", "we will destroy you", "attack is imminent",
    "our armies march", "your empire ends", "this means war", "we declare war",
    "war begins now", "prepare for war",
]
_KW_INSULT = [
    "contemptible", "beneath us", "unworthy of", "inferior species",
    "you are pathetic", "pitiful", "worthless", "deplorable",
]
_KW_NAP = [
    "non-aggression pact", "we accept your peace", "ceasefire agreed",
    "peace is established", "truce accepted", "non-aggression accepted",
]
_KW_OPINION_UP = [
    "we are grateful for", "thank you for", "we appreciate your",
    "your actions have earned", "we commend you",
]
_KW_OPINION_DOWN = [
    "we are offended by", "your actions have insulted", "this is an outrage",
    "we take grievance", "we protest your", "unacceptable action",
]

_KW_TRADE_CLOSE = [
    "terms agreed", "deal concluded", "deal is done", "shipments dispatched",
    "treaty ratified", "signatures synchronized", "accord formalized",
    "transactions proceed", "we accept your offer", "formal agreement", 
    "mutual resource exchange is agreeable"
]

_KW_PLAYER_INSULT = [
    "read it and weep", "you are nothing", "worthless", "idiots", "fools",
    "i despise you", "we despise you", "scum", "you disgust",
    "you are all but motes", "you don't matter", "pathetic",
    "heathens", "heretics", "blasphemers", "damned", "cursed",
    "apostates", "infidels", "unbelievers",
    "boil forever", "burn in", "shall suffer", "you will perish",
    "end you", "annihilate you", "obliterate you",
    "face our wrath", "feel our wrath", "you are doomed",
    "kettle of", "fires of", "wrath of",
]

def _keyword_classify(msg: str) -> str | None:
    """Return intent if hard keywords match, else None (defer to LLM)."""
    m = msg.lower()
    for kw in _KW_WAR:
        if kw in m:
            return "WAR_DECLARED"
    for kw in _KW_INSULT:
        if kw in m:
            return "INSULT"
    for kw in _KW_NAP:
        if kw in m:
            return "NAP_ACCEPTED"
    for kw in _KW_OPINION_UP:
        if kw in m:
            return "OPINION_UP"
    for kw in _KW_OPINION_DOWN:
        if kw in m:
            return "OPINION_DOWN"
    for kw in _KW_TRADE_CLOSE:
        if kw in m:
            return "TRADE_DEAL"
    return None

def get_player_insult_keywords() -> list:
    return _KW_PLAYER_INSULT

def get_war_keywords() -> list:
    return _KW_WAR

# ── Intent detector ───────────────────────────────────────────────────────────

def detect_intent(client, empire_name: str, empire_tag: str, message: str,
                  empire_civics_list: list = None, cache: dict = None,
                  cache_times: dict = None, max_age: int = 300) -> dict:
    logger = logging.getLogger("galcon")
    empire_civics_list = empire_civics_list or []

    if not empire_tag.isdigit():
        return {"intent": "NONE", "confidence": "low",
                "reason": "Invalid empire tag", "command": None, "label": None,
                "raw_intent": "INVALID_TAG"}

    if cache is not None and cache_times is not None:
        msg_hash = hashlib.md5(message.encode()).hexdigest()
        cache_key = (empire_tag, msg_hash)

        if cache_key in cache:
            cached_time = cache_times.get(cache_key, 0)
            age = time.time() - cached_time
            if age < max_age:
                return cache[cache_key]

    kw_intent = _keyword_classify(message)
    if kw_intent is not None:
        cmd_tmpl, label = INTENT_MAP.get(kw_intent, (None, None))
        cmd = cmd_tmpl.format(tag=empire_tag) if cmd_tmpl else None
        result = {"intent": kw_intent, "confidence": "high",
                "reason": "keyword match", "command": cmd, "label": label,
                "raw_intent": kw_intent, "direction": "neutral"}

        if cache is not None and cache_times is not None:
            msg_hash = hashlib.md5(message.encode()).hexdigest()
            cache_key = (empire_tag, msg_hash)
            cache[cache_key] = result
            cache_times[cache_key] = time.time()

        return result

    trade_hints = [
        "offer accepted", "deal accepted", "exchange agreed", "minerals in exchange",
        "energy in exchange", "payment agreed", "terms agreed", "treaty of trade",
        "research transfer", "technology transfer", "shipment dispatched",
        "resources exchanged", "trade agreement", "commercial deal",
        "formal agreement", "mutual exchange", "resource exchange"
    ]
   
    if not any(h in message.lower() for h in trade_hints):
        result = {"intent": "NONE", "confidence": "high",
                "reason": "no actionable keywords", "command": None, "label": None,
                "raw_intent": "NONE", "direction": "neutral"}

        if cache is not None and cache_times is not None:
            msg_hash = hashlib.md5(message.encode()).hexdigest()
            cache_key = (empire_tag, msg_hash)
            cache[cache_key] = result
            cache_times[cache_key] = time.time()

        return result

    try:
        raw = llm_client.call_llm(
            client, llm_client._current_provider, "classifier",
            [{"role": "user", "content": CLASSIFIER_PROMPT + f"\n\nMESSAGE: {message}"}],
            max_tokens=MAX_TOKENS_CLASSIFIER,
            json_mode=True
        )
        data = json.loads(raw)

        intent_val = data.get("intent", "NONE")
        if intent_val not in INTENT_MAP:
            intent_val = "NONE"

        conf = data.get("confidence", "low")
        direction = data.get("direction", "neutral")
        reason = data.get("reason", "LLM classification")

        cmd_tmpl, label = INTENT_MAP.get(intent_val, (None, None))
        cmd = cmd_tmpl.format(tag=empire_tag) if cmd_tmpl else None

        result = {
            "intent": intent_val,
            "confidence": conf,
            "command": cmd,
            "label": label,
            "raw_intent": intent_val,
            "direction": direction,
            "reason": reason
        }

        if cache is not None and cache_times is not None:
            msg_hash = hashlib.md5(message.encode()).hexdigest()
            cache_key = (empire_tag, msg_hash)
            cache[cache_key] = result
            cache_times[cache_key] = time.time()

        return result

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Intent classifier JSON parse error for {empire_name}: {e}")
        return {"intent": "NONE", "confidence": "low",
                "reason": f"Parse error: {str(e)[:50]}", "command": None, "label": None,
                "raw_intent": "NONE"}
    except Exception as e:
        logger.error(f"Intent classifier error for {empire_name}: {e}")
        return {"intent": "NONE", "confidence": "low",
                "reason": f"Classifier error: {str(e)[:50]}", "command": None, "label": None,
                "raw_intent": "NONE"}

# ── Stellaris install discovery ──────────────────────────────────────────────
_stellaris_dir_cache = False

def _find_steam_libraries() -> list[Path]:
    libraries: list[Path] = []
    steam_path: str | None = None

    try:
        import winreg
        for hive, key in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Valve\Steam"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as k:
                    steam_path, _ = winreg.QueryValueEx(k, "InstallPath")
                    break
            except OSError:
                continue
    except ImportError:
        pass 

    if steam_path:
        libraries.append(Path(steam_path))
        vdf = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(m.group(1))
                    if p not in libraries:
                        libraries.append(p)
            except Exception:
                pass

    return libraries

def _find_stellaris_dir() -> Path | None:
    global _stellaris_dir_cache
    if _stellaris_dir_cache is not False:          
        return _stellaris_dir_cache

    STEAM_APP_ID = "281990"

    try:
        import winreg
        reg_keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {STEAM_APP_ID}"),
            (winreg.HKEY_LOCAL_MACHINE,
             rf"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {STEAM_APP_ID}"),
        ]
        for hive, key_path in reg_keys:
            try:
                with winreg.OpenKey(hive, key_path) as k:
                    loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                    p = Path(loc)
                    if p.exists() and (p / "stellaris.exe").exists():
                        _stellaris_dir_cache = p
                        print(f"[GalCon] Stellaris found via registry: {p}", file=sys.stderr)
                        return p
            except OSError:
                continue
    except ImportError:
        pass  

    for lib_root in _find_steam_libraries():
        p = lib_root / "steamapps" / "common" / "Stellaris"
        if p.exists() and (p / "stellaris.exe").exists():
            _stellaris_dir_cache = p
            print(f"[GalCon] Stellaris found via Steam VDF: {p}", file=sys.stderr)
            return p

    fallbacks = [
        Path("C:/Program Files (x86)/Steam/steamapps/common/Stellaris"),
        Path("C:/Program Files/Steam/steamapps/common/Stellaris"),
        Path("C:/Program Files/Stellaris"),
        Path("C:/Program Files (x86)/Stellaris"),
        Path("C:/GOG Games/Stellaris"),
        Path.home() / ".steam/steam/steamapps/common/Stellaris",
        Path.home() / ".local/share/Steam/steamapps/common/Stellaris",
    ]
    for p in fallbacks:
        exe = p / "stellaris.exe"
        if not exe.exists():
            exe = p / "stellaris"     
        if p.exists() and exe.exists():
            _stellaris_dir_cache = p
            print(f"[GalCon] Stellaris found via fallback path: {p}", file=sys.stderr)
            return p

    _stellaris_dir_cache = None
    print("[GalCon] WARNING: Could not locate Stellaris installation directory.", file=sys.stderr)
    return None

# ── Console injection (batch‑only) ───────────────────────────────────────────

def inject_console(
    command: str,
    console_key: str = "`",
    dry_run: bool = False,
    batch: bool = True          
) -> tuple[bool, str]:
    console_key = console_key.strip()
    if len(console_key) != 1:
        return False, f"FAIL: Console key must be exactly 1 character, got '{console_key}'"

    try:
        import pyautogui
        import pygetwindow as gw
    except ImportError:
        return False, "FAIL: pyautogui / pygetwindow not installed — run: pip install pyautogui pygetwindow"

    all_wins = [w for w in gw.getAllWindows() if w.title.strip()]
    wins = [w for w in all_wins if "stellaris" in w.title.lower()]
    if not wins:
        return False, f"FAIL: Stellaris not running. Open windows: {[w.title for w in all_wins[:15]]}"

    visible = [w for w in wins if w.isActive or w.visible]
    win = visible[0] if visible else wins[0]

    if dry_run:
        return True, f"DRY RUN OK — found window: '{win.title}' | command: {command}"

    try:
        win.activate()
    except Exception:
        pass   
    time.sleep(0.3)

    active = gw.getActiveWindow()
    if active is None or "stellaris" not in active.title.lower():
        return False, "FAIL: Stellaris not active. Try clicking the game window first."

    try:
        pyautogui.press(console_key)
        time.sleep(0.3)
    except Exception as e:
        return False, f"FAIL: Console open failed: {e}"

    return _inject_via_batch(command, console_key)

def _inject_via_batch(command: str, key: str) -> tuple[bool, str]:
    logger = logging.getLogger("galcon")
    
    try:
        import pyautogui
    except ImportError:
        return False, "FAIL: pyautogui not installed"

    game_dir = _find_stellaris_dir()

    if not game_dir:
        msg = (
            "FAIL: Could not locate Stellaris installation directory.\n"
            "SOLUTIONS:\n"
            "  1. Verify Stellaris is installed and discoverable via Steam or GOG\n"
            "  2. In ⚙ Settings, manually specify your Stellaris game directory\n"
            "  3. Ensure Steam is running so libraryfolders.vdf is current\n"
            "  4. Check that you have read access to your Steam directory"
        )
        logger.error(f"Stellaris directory not found. {msg}")
        return False, msg

    from config import validate_game_dir
    is_valid, diag = validate_game_dir(str(game_dir))
    if not is_valid:
        logger.error(f"Game directory validation failed: {diag}")
        return False, f"FAIL: {diag}"

    logger.debug(f"Using Stellaris directory: {game_dir}")

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    cmd_file   = game_dir / f"galcon_{timestamp}.txt"

    try:
        cmd_file.write_text(command.strip(), encoding="utf-8")
        logger.debug(f"Wrote command file: {cmd_file}")
    except PermissionError:
        msg = (
            f"FAIL: Permission denied writing to {game_dir}.\n"
            "SOLUTION: Run Galactic Conclave as Administrator."
        )
        logger.error(msg)
        return False, msg
    except Exception as e:
        logger.error(f"Failed to write command file: {e}")
        return False, f"FAIL: Write error: {e}"

    try:
        pyautogui.write(f"run {cmd_file.stem}", interval=0.02)
        time.sleep(0.15)
        pyautogui.press("enter")
        time.sleep(0.3)
        pyautogui.press(key)
        logger.debug(f"Typed 'run {cmd_file.stem}' and pressed enter")
    except Exception as e:
        logger.error(f"Execution error: {e}")
        cmd_file.unlink(missing_ok=True)
        return False, f"FAIL: Execute error: {e}"

    max_wait = 5.0
    check_interval = 0.1
    elapsed = 0.0

    while elapsed < max_wait:
        try:
            stat = cmd_file.stat()
            mtime = stat.st_mtime
            now = time.time()
            age = now - mtime

            if age > 0.5:  
                cmd_file.unlink(missing_ok=True)
                logger.debug(f"Cleaned up command file after {age:.1f}s")
                return True, f"Executed: {cmd_file.name} → {command}"
        except FileNotFoundError:
            return True, f"Executed: {cmd_file.name} → {command}"
        except Exception:
            pass

        time.sleep(check_interval)
        elapsed += check_interval

    try:
        cmd_file.unlink(missing_ok=True)
        logger.warning(f"Forced cleanup of {cmd_file.name} after timeout")
    except Exception as e:
        logger.warning(f"Could not clean up {cmd_file.name}: {e}")

    return True, f"Executed (cleanup delayed): {cmd_file.name} → {command}"