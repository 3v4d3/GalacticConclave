"""ui.py — Galactic Conclave overlay window and all widget code."""

import logging
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import llm_client
from config import (
    DEFAULT_SAVE_DIR,
    load_config,
    save_config,
    validate_console_key,
    validate_save_dir,
)
from game_io import (
    INTENT_MAP,
    detect_intent,
    get_player_insult_keywords,
    get_war_keywords,
    inject_console,
)
from llm_client import (
    MAX_TOKENS_CHAT,
    PROVIDERS,
    build_client,
    call_llm,
    detect_provider,
)
from prompts import (
    AUTO_PROMPTS,
    MOCK_RESPONSES,
    _generate_ruler_name,
    build_system_prompt,
)
from save_parser import newest_save, parse_save

logger = logging.getLogger("galcon")

# ── Colour palette (Paradox / Stellaris aesthetic) ─────────────────────────

BG = "#080b10"
BG_PANEL = "#0d1118"
BG_CHAT = "#0a0e15"
BG_INPUT = "#131824"
ACCENT = "#1e2535"
GOLD = "#c8a050"
GOLD_DIM = "#5a4820"
GOLD_TEXT = "#f0c870"
TEXT = "#d8cdb8"
TEXT_DIM = "#6a6050"
BTN_GREEN = "#1e4a28"
BTN_BLUE = "#1a3050"
BTN_RED = "#4a1010"
BTN_GRAY = "#1e2535"

EMPIRE_COLORS = [
    "#4a8fc8",
    "#5ab05a",
    "#c87a30",
    "#b84040",
    "#7a5ab8",
    "#30a870",
    "#c8b040",
    "#30a8b8",
]

_KW_PLAYER_INSULT = get_player_insult_keywords()
_KW_WAR = get_war_keywords()

# ── Main overlay window ─────────────────────────────────────────────────────


class GalacticConclave:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.client = None
        self.provider = "groq"
        self.game_data = {}
        self.empires = {}
        self.clr = {}
        self.histories = {}
        self.selected = None
        self.auto_on = False
        self._last_sav = None
        self._last_mtime = 0
        self._last_parsed_date = ""
        self.empire_enabled: dict = {}
        self.ruler_names: dict = {}
        self.met_tags: set = set()
        self.var_dry_run = None
        self.var_console_key = None
        self.mock_mode = False
        self.injection_enabled = True
        self.ironman = False

        self.var_game_dir = tk.StringVar(value=self.cfg.get("game_dir", ""))

        self._intent_cache: dict = {}
        self._intent_cache_times: dict = {}

        self._lock = threading.RLock()
        self._inject_queue = queue.Queue()
        self._llm_sem = threading.Semaphore(5)
        threading.Thread(target=self._injection_worker, daemon=True).start()

        self._build_ui()
        self._apply_api_key()

        save_dir = self.cfg.get("save_dir", str(DEFAULT_SAVE_DIR))
        if not validate_save_dir(save_dir):
            print(f"WARNING: Save directory not found: {save_dir}", file=sys.stderr)
            save_dir = str(DEFAULT_SAVE_DIR)
            if not validate_save_dir(save_dir):
                print(
                    f"ERROR: Default save directory also not found: {save_dir}",
                    file=sys.stderr,
                )

        self.var_save_dir.set(save_dir)
        if self.client and validate_save_dir(save_dir):
            self._auto_load_newest(save_dir)

        self._poll_for_new_save()

    def _injection_worker(self):
        while True:
            task = self._inject_queue.get()
            if task is None:
                break
            if task == "STOP_SIGNAL":
                break
            cmd, key, dry, callback = task
            ok, msg = inject_console(cmd, console_key=key, dry_run=dry)
            if callback:
                self.root.after(0, lambda ok=ok, msg=msg, cb=callback: cb(ok, msg))
            self._inject_queue.task_done()

    def _queue_inject(self, cmd: str, callback=None):
        key = (self.var_console_key.get() or "`") if self.var_console_key else "`"
        dry = self.var_dry_run.get() if self.var_dry_run else False
        self._inject_queue.put((cmd, key, dry, callback))

    F_TITLE = ("Georgia", 11, "bold")
    F_HDR = ("Georgia", 8, "bold")
    F_LABEL = ("Segoe UI", 8)
    F_LABEL_B = ("Segoe UI", 8, "bold")
    F_BODY = ("Segoe UI", 9)
    F_SMALL = ("Segoe UI", 7)
    F_BTN = ("Segoe UI", 8, "bold")
    F_MONO = ("Consolas", 8)

    def _divider(self, parent, color=None, pady=0):
        tk.Frame(parent, bg=color or GOLD_DIM, height=1).pack(fill="x", pady=pady)

    def _section_header(self, parent, text):
        f = tk.Frame(parent, bg=BG_PANEL)
        f.pack(fill="x", padx=0)
        tk.Frame(f, bg=GOLD_DIM, height=1).pack(fill="x")
        inner = tk.Frame(f, bg=BG_PANEL)
        inner.pack(fill="x")
        tk.Label(inner, text=f"  {text}  ", bg=BG_PANEL, fg=GOLD, font=self.F_HDR).pack(
            side="left", pady=3
        )
        tk.Frame(f, bg=GOLD_DIM, height=1).pack(fill="x")
        return inner

    def _build_ui(self):
        r = self.root
        r.title("Galactic Conclave  v0.6.0")
        r.configure(bg=BG)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.96)
        r.geometry("500x740+30+40")
        r.minsize(400, 520)

        tk.Frame(r, bg=GOLD, height=2).pack(fill="x")
        self._build_topbar(r)
        self._build_settings(r)
        self._build_body(r)
        tk.Frame(r, bg=GOLD_DIM, height=1).pack(fill="x")
        self._build_input(r)
        self._build_statusbar(r)

    def _build_topbar(self, r):
        bar = tk.Frame(r, bg=BG_PANEL, pady=8)
        bar.pack(fill="x")
        tk.Label(bar, text="✦", bg=BG_PANEL, fg=GOLD, font=("Georgia", 13)).pack(
            side="left", padx=(12, 4)
        )
        tk.Label(
            bar,
            text="SUBSPACE COMMUNICATIONS",
            bg=BG_PANEL,
            fg=GOLD_TEXT,
            font=self.F_TITLE,
        ).pack(side="left")
        tk.Button(
            bar,
            text="⚙",
            bg=BG_PANEL,
            fg=GOLD_DIM,
            relief="flat",
            font=("Segoe UI", 12),
            activebackground=BG_PANEL,
            activeforeground=GOLD,
            cursor="hand2",
            command=self._toggle_settings,
        ).pack(side="right", padx=10)
        self.lbl_date = tk.Label(
            bar, text="", bg=BG_PANEL, fg=GOLD_DIM, font=self.F_SMALL
        )
        self.lbl_date.pack(side="right", padx=6)
        tk.Frame(r, bg=GOLD, height=1).pack(fill="x")

    def _build_settings(self, r):
        self.frm_settings = tk.Frame(r, bg=BG_PANEL)
        pad = {"padx": 12, "pady": 3}

        row_api = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_api.pack(fill="x", **pad)
        tk.Label(
            row_api,
            text="API KEY",
            bg=BG_PANEL,
            fg=GOLD,
            font=self.F_HDR,
            width=9,
            anchor="w",
        ).pack(side="left")
        self.var_api = tk.StringVar(value=self.cfg.get("api_key", ""))
        tk.Entry(
            row_api,
            textvariable=self.var_api,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_MONO,
            show="●",
        ).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 6))
        tk.Button(
            row_api,
            text="CONFIRM",
            bg=BTN_BLUE,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            padx=6,
            cursor="hand2",
            command=self._save_api_key,
        ).pack(side="right")

        row_prov = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_prov.pack(fill="x", padx=12, pady=(0, 2))
        self.var_provider_lbl = tk.StringVar(value="— paste key and confirm —")
        tk.Label(
            row_prov,
            textvariable=self.var_provider_lbl,
            bg=BG_PANEL,
            fg=GOLD_TEXT,
            font=self.F_SMALL,
        ).pack(side="left")

        row_ollama = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_ollama.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(
            row_ollama,
            text="Local LLM: type 'ollama' as key.",
            bg=BG_PANEL,
            fg=GOLD_DIM,
            font=self.F_SMALL,
        ).pack(side="left")
        import webbrowser as _wb

        tk.Button(
            row_ollama,
            text="↗ ollama.com",
            bg=BG_PANEL,
            fg=GOLD,
            relief="flat",
            font=self.F_SMALL,
            cursor="hand2",
            command=lambda: _wb.open(llm_client.OLLAMA_URL),
        ).pack(side="right")

        row_model = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_model.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(
            row_model,
            text="MODEL OVERRIDE",
            bg=BG_PANEL,
            fg=GOLD,
            font=self.F_HDR,
            width=15,
            anchor="w",
        ).pack(side="left")
        self.var_model = tk.StringVar(value=self.cfg.get("model_override", ""))
        tk.Entry(
            row_model,
            textvariable=self.var_model,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_MONO,
        ).pack(side="left", fill="x", expand=True, ipady=3, padx=(4, 6))
        tk.Label(
            row_model,
            text="(leave blank for default)",
            bg=BG_PANEL,
            fg=GOLD_DIM,
            font=self.F_SMALL,
        ).pack(side="left")
        tk.Button(
            row_model,
            text="SAVE",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            padx=4,
            cursor="hand2",
            command=self._save_model_override,
        ).pack(side="right")

        row_dir = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_dir.pack(fill="x", **pad)
        tk.Label(
            row_dir,
            text="SAVES",
            bg=BG_PANEL,
            fg=GOLD,
            font=self.F_HDR,
            width=9,
            anchor="w",
        ).pack(side="left")
        self.var_save_dir = tk.StringVar(value=str(DEFAULT_SAVE_DIR))
        tk.Entry(
            row_dir,
            textvariable=self.var_save_dir,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_MONO,
        ).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 6))
        tk.Button(
            row_dir,
            text="BROWSE",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            padx=4,
            cursor="hand2",
            command=self._browse_dir,
        ).pack(side="right")

        row_game = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_game.pack(fill="x", **pad)
        tk.Label(
            row_game,
            text="GAME DIR",
            bg=BG_PANEL,
            fg=GOLD,
            font=self.F_HDR,
            width=9,
            anchor="w",
        ).pack(side="left")
        tk.Entry(
            row_game,
            textvariable=self.var_game_dir,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_MONO,
        ).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 6))
        tk.Button(
            row_game,
            text="BROWSE",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            padx=4,
            cursor="hand2",
            command=self._browse_game_dir,
        ).pack(side="right")

        row_mid = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_mid.pack(fill="x", padx=12, pady=(4, 8))
        tk.Button(
            row_mid,
            text="↺  RELOAD SAVE",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            cursor="hand2",
            command=self._manual_reload,
        ).pack(side="left")
        self.var_mock = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row_mid,
            text="⚗  Mock mode  (no API required)",
            variable=self.var_mock,
            bg=BG_PANEL,
            fg="#c87a30",
            selectcolor=BG_INPUT,
            activebackground=BG_PANEL,
            font=self.F_SMALL,
            cursor="hand2",
            command=self._toggle_mock,
        ).pack(side="right")

        row_inj = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_inj.pack(fill="x", padx=12, pady=(0, 2))
        self.var_injection = tk.BooleanVar(value=True)
        self.chk_injection = tk.Checkbutton(
            row_inj,
            text="⚡  Console injection",
            variable=self.var_injection,
            bg=BG_PANEL,
            fg=GOLD_TEXT,
            selectcolor=BG_INPUT,
            activebackground=BG_PANEL,
            font=self.F_SMALL,
            cursor="hand2",
            command=lambda: setattr(
                self, "injection_enabled", self.var_injection.get()
            ),
        )
        self.chk_injection.pack(side="left")
        self.var_dry_run = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row_inj,
            text="Dry run",
            variable=self.var_dry_run,
            bg=BG_PANEL,
            fg="#c87a30",
            selectcolor=BG_INPUT,
            activebackground=BG_PANEL,
            font=self.F_SMALL,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        for line in [
            "⚠  Injection only works when Stellaris is running and unpaused.",
            "⚠  Ironman mode disables the console — injection unavailable.",
            "⚠  Stellaris must be the active window when APPLY is clicked.",
        ]:
            tk.Label(
                self.frm_settings,
                text=line,
                bg=BG_PANEL,
                fg="#c87a30",
                font=self.F_SMALL,
                anchor="w",
            ).pack(fill="x", padx=12)

        row_key = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_key.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(
            row_key,
            text="CONSOLE KEY",
            bg=BG_PANEL,
            fg=GOLD,
            font=self.F_HDR,
            width=12,
            anchor="w",
        ).pack(side="left")
        self.var_console_key = tk.StringVar(value=self.cfg.get("console_key", "`"))
        tk.Entry(
            row_key,
            textvariable=self.var_console_key,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_MONO,
            width=4,
        ).pack(side="left", ipady=3)
        tk.Label(
            row_key,
            text="  (check Stellaris Settings → Controls if injection fails)",
            bg=BG_PANEL,
            fg=GOLD_DIM,
            font=self.F_SMALL,
        ).pack(side="left", padx=4)
        tk.Button(
            row_key,
            text="TEST",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_HDR,
            padx=6,
            cursor="hand2",
            command=self._test_injection,
        ).pack(side="right")

        row_note = tk.Frame(self.frm_settings, bg=BG_PANEL)
        row_note.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(
            row_note,
            text="⚠  Injection requires direct Steam launch — not the Paradox Launcher.",
            bg=BG_PANEL,
            fg="#c87a30",
            font=self.F_SMALL,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            row_note,
            text="  Steam → right-click Stellaris → Properties → Launch Options → add:  -open_console",
            bg=BG_PANEL,
            fg=GOLD_DIM,
            font=self.F_SMALL,
            anchor="w",
        ).pack(fill="x", padx=0)

        tk.Frame(self.frm_settings, bg=GOLD, height=1).pack(fill="x")

    def _build_body(self, r):
        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG_PANEL, width=168)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(body, bg=GOLD_DIM, width=1).pack(side="left", fill="y")

        shdr = tk.Frame(left, bg=BG_PANEL)
        shdr.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(shdr, text="KNOWN POWERS", bg=BG_PANEL, fg=GOLD, font=self.F_HDR).pack(
            side="left"
        )
        self.var_all = tk.BooleanVar(value=True)
        tk.Checkbutton(
            shdr,
            text="all",
            variable=self.var_all,
            bg=BG_PANEL,
            fg=GOLD_DIM,
            selectcolor=BG_INPUT,
            activebackground=BG_PANEL,
            font=self.F_SMALL,
            cursor="hand2",
            command=self._toggle_all_empires,
        ).pack(side="right")

        shdr2 = tk.Frame(left, bg=BG_PANEL)
        shdr2.pack(fill="x", padx=8, pady=(0, 4))
        self.btn_contact_all = tk.Button(
            shdr2,
            text="📡 CONTACT ALL",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_SMALL,
            cursor="hand2",
            command=self._contact_all,
        )
        self.btn_contact_all.pack(side="left")

        tk.Frame(left, bg=GOLD_DIM, height=1).pack(fill="x", padx=4)

        self.frm_empire_btns = tk.Frame(left, bg=BG_PANEL)
        self.frm_empire_btns.pack(fill="both", expand=True, padx=6, pady=4)

        right = tk.Frame(body, bg=BG_CHAT)
        right.pack(side="left", fill="both", expand=True)

        self.chat = scrolledtext.ScrolledText(
            right,
            bg=BG_CHAT,
            fg=TEXT,
            insertbackground=GOLD,
            font=self.F_BODY,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=10,
            pady=10,
            selectbackground=ACCENT,
        )
        self.chat.pack(fill="both", expand=True)

        self.chat.tag_config("ts", foreground=GOLD_DIM, font=self.F_SMALL)
        self.chat.tag_config("you", foreground=GOLD_TEXT, font=self.F_LABEL_B)
        self.chat.tag_config("sys", foreground=GOLD_DIM, font=("Segoe UI", 8, "italic"))
        self.chat.tag_config("divider", foreground=GOLD_DIM, font=self.F_SMALL)
        self.chat.tag_config("sender", foreground=GOLD, font=self.F_LABEL_B)
        self.chat.tag_config("body", foreground=TEXT, font=self.F_BODY)

    def _build_input(self, r):
        bot = tk.Frame(r, bg=BG_PANEL, pady=8)
        bot.pack(fill="x")

        row1 = tk.Frame(bot, bg=BG_PANEL)
        row1.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(row1, text="TRANSMIT TO", bg=BG_PANEL, fg=GOLD, font=self.F_HDR).pack(
            side="left", padx=(0, 6)
        )
        tk.Button(
            row1,
            text="📡 ALL",
            bg=BTN_GRAY,
            fg=GOLD_TEXT,
            relief="flat",
            font=self.F_BTN,
            padx=6,
            cursor="hand2",
            command=self._broadcast_all,
        ).pack(side="left", padx=(0, 6))

        self.var_empire = tk.StringVar(value="— select empire —")
        self.cmb_empire = ttk.Combobox(
            row1,
            textvariable=self.var_empire,
            state="readonly",
            width=21,
            font=self.F_LABEL,
        )
        self.cmb_empire.pack(side="left")
        self.cmb_empire.bind("<<ComboboxSelected>>", self._on_empire_pick)

        self.btn_now = tk.Button(
            row1,
            text="⚡",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=("Segoe UI", 10),
            cursor="hand2",
            command=self._fire_now,
        )
        self.btn_now.pack(side="right", padx=(3, 0))

        self.btn_auto = tk.Button(
            row1,
            text="▶  AUTO",
            bg=BTN_GRAY,
            fg=GOLD,
            relief="flat",
            font=self.F_BTN,
            padx=8,
            cursor="hand2",
            command=self._toggle_auto,
        )
        self.btn_auto.pack(side="right", padx=4)

        tk.Label(
            row1, text="INTERVAL", bg=BG_PANEL, fg=GOLD_DIM, font=self.F_SMALL
        ).pack(side="right", padx=(8, 2))
        self.var_interval = tk.IntVar(value=30)
        sl = tk.Scale(
            row1,
            from_=5,
            to=120,
            orient="horizontal",
            variable=self.var_interval,
            bg=BG_PANEL,
            fg=GOLD_DIM,
            troughcolor=BG_INPUT,
            highlightthickness=0,
            length=80,
            showvalue=True,
            font=self.F_SMALL,
        )
        sl.pack(side="right")

        row2 = tk.Frame(bot, bg=BG_PANEL)
        row2.pack(fill="x", padx=10)
        tk.Frame(row2, bg=GOLD_DIM, height=1).pack(fill="x", pady=(0, 4))

        inner = tk.Frame(row2, bg=BG_INPUT, padx=4)
        inner.pack(fill="x")

        self.var_msg = tk.StringVar()
        self.ent_msg = tk.Entry(
            inner,
            textvariable=self.var_msg,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=GOLD,
            relief="flat",
            font=self.F_BODY,
            disabledbackground=BG_INPUT,
        )
        self.ent_msg.pack(side="left", fill="x", expand=True, ipady=6)
        self.ent_msg.bind("<Return>", lambda _: self._send())

        tk.Button(
            inner,
            text="TRANSMIT  ▶",
            bg=BTN_GREEN,
            fg=GOLD_TEXT,
            relief="flat",
            font=self.F_BTN,
            padx=10,
            cursor="hand2",
            command=self._send,
        ).pack(side="right", pady=2)

    def _build_statusbar(self, r):
        bar = tk.Frame(r, bg=BG_PANEL, pady=3)
        bar.pack(fill="x")
        self.var_status = tk.StringVar(value="Configure your API key (⚙) to begin.")
        tk.Label(
            bar,
            textvariable=self.var_status,
            bg=BG_PANEL,
            fg=GOLD_DIM,
            font=self.F_SMALL,
            anchor="w",
        ).pack(side="left", padx=10)

    def _toggle_settings(self):
        if self.frm_settings.winfo_ismapped():
            self.frm_settings.pack_forget()
        else:
            self.frm_settings.pack(fill="x")

    def _test_injection(self):
        key = self.var_console_key.get() or "`"
        self.cfg["console_key"] = key
        save_config(self.cfg)
        dry = self.var_dry_run.get()

        ok, msg = inject_console("help", console_key=key, dry_run=True)
        self._sys(f"Console test (help): {msg}")
        if not ok:
            return

        ok2, msg2 = inject_console("energy 100", console_key=key, dry_run=dry)
        self._sys(f"Resource test (energy +100): {msg2}")
        if ok2 and not dry:
            self._sys(
                "Check your energy stockpile — if it went up by 100, injection is working."
            )

        ok3, msg3 = inject_console("debugtooltip", console_key=key, dry_run=dry)
        self._sys(f"Debugtooltip: {msg3}")
        self._sys(
            "Hover over empires in the diplomacy screen to see their console IDs."
        )

    def _save_model_override(self):
        model = self.var_model.get().strip()
        self.cfg["model_override"] = model
        save_config(self.cfg)
        llm_client._model_override = model
        if model:
            self._sys(f"Model override set: {model}")
        else:
            self._sys("Model override cleared — using provider default.")

    def _toggle_mock(self):
        self.mock_mode = self.var_mock.get()
        state = (
            "ON — responses are local stubs, no API used."
            if self.mock_mode
            else "OFF — live API."
        )
        self._sys(f"Mock mode {state}")

    def _save_api_key(self):
        key = self.var_api.get().strip()
        if not key and not self.mock_mode:
            messagebox.showwarning(
                "No Key", "Paste your API key or type 'ollama' for local."
            )
            return
        self.cfg["api_key"] = key
        provider = detect_provider(key)
        self.cfg["provider"] = provider
        save_config(self.cfg)
        self._apply_api_key()
        pname = PROVIDERS[provider]["name"]
        self._sys(f"Provider detected: {pname}  ✓")
        if hasattr(self, "var_provider_lbl"):
            self.var_provider_lbl.set(f"✓  {pname}")
        self.var_status.set(f"Connected: {pname}. Load a save file to begin.")
        save_dir = self.var_save_dir.get().strip()
        if save_dir:
            self._auto_load_newest(save_dir)

    def _apply_api_key(self):
        key = self.cfg.get("api_key", "").strip()
        self.provider = detect_provider(key)
        llm_client._current_provider = self.provider
        llm_client._model_override = self.cfg.get("model_override", "")
        try:
            self.client = build_client(self.provider, key)
        except Exception as e:
            print(f"Client build warning: {e}", file=sys.stderr)

    def _browse_dir(self):
        d = filedialog.askdirectory(title="Select Stellaris save games folder")
        if d:
            self.var_save_dir.set(d)
            self.cfg["save_dir"] = d
            save_config(self.cfg)
            self._auto_load_newest(d)

    def _manual_reload(self):
        self._auto_load_newest(self.var_save_dir.get().strip())

    def _auto_load_newest(self, save_dir: str):
        if not save_dir or not self.client:
            return
        path = newest_save(save_dir)
        if not path:
            self.var_status.set(f"No .sav files found in: {save_dir}")
            return
        try:
            mtime = Path(path).stat().st_mtime
        except Exception:
            mtime = 0
        if path == self._last_sav and mtime == self._last_mtime:
            return
        self._last_sav = path
        self._last_mtime = mtime
        self.cfg["save_dir"] = save_dir
        save_config(self.cfg)
        threading.Thread(target=self._load_thread, args=(path,), daemon=True).start()

    def _load_thread(self, path: str):
        from save_parser import peek_date

        new_date = peek_date(path)
        if new_date and new_date == self._last_parsed_date:
            return

        self.root.after(0, lambda: self.var_status.set(f"Parsing {Path(path).name}…"))
        try:
            data = parse_save(path)
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            self.root.after(
                0, lambda err=str(e): self.var_status.set(f"Parse error: {err}")
            )
            self.root.after(0, lambda t=tb: self._sys(f"Parse traceback:\n{t}"))
            return
        self._last_parsed_date = data.get("date", "")
        try:
            self.root.after(0, lambda: self._apply_data(data))
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            self.root.after(
                0, lambda err=str(e): self.var_status.set(f"Apply error: {err}")
            )
            self.root.after(0, lambda t=tb: self._sys(f"Apply traceback:\n{t}"))

    def _apply_data(self, data: dict):
        self.game_data = data
        self.empires = {e["name"]: e for e in data["empires"]}
        self.met_tags = data.get("met_tags", set())
        self.clr = {
            n: EMPIRE_COLORS[i % len(EMPIRE_COLORS)] for i, n in enumerate(self.empires)
        }
        with self._lock:
            for n in self.empires:
                if n not in self.histories:
                    self.histories[n] = []

        self.ironman = data.get("ironman", False)
        if self.ironman:
            self.var_injection.set(False)
            self.injection_enabled = False
            self.chk_injection.config(state="disabled")
            self.btn_contact_all.config(state="disabled")
            self.var_status.set(
                "⚠  Ironman save detected — console injection disabled."
            )
            self._sys(
                "Ironman mode: console injection is disabled. Achievements will not be affected."
            )
        else:
            self.var_injection.set(True)
            self.injection_enabled = True
            self.chk_injection.config(state="normal")
            self.btn_contact_all.config(state="normal")

        for w in self.frm_empire_btns.winfo_children():
            w.destroy()
        names = list(self.empires.keys())
        self.cmb_empire["values"] = names
        for name in names:
            empire = self.empires[name]
            met = empire["tag"] in self.met_tags
            col = self.clr[name] if met else GOLD_DIM
            self.chat.tag_config(name, foreground=col, font=self.F_LABEL_B)
            if name not in self.empire_enabled:
                self.empire_enabled[name] = tk.BooleanVar(value=met)
            row = tk.Frame(self.frm_empire_btns, bg=BG_PANEL)
            row.pack(fill="x", pady=1)
            tk.Checkbutton(
                row,
                variable=self.empire_enabled[name],
                bg=BG_PANEL,
                fg=GOLD_DIM,
                selectcolor=BG_INPUT,
                activebackground=BG_PANEL,
                cursor="hand2",
                command=self._refresh_all_var,
            ).pack(side="left")
            tk.Label(
                row, text="■" if met else "□", bg=BG_PANEL, fg=col, font=("Segoe UI", 8)
            ).pack(side="left")
            btn_text = name[:18] if met else f"? {name[:15]}"
            tk.Button(
                row,
                text=btn_text,
                bg=BG_PANEL,
                fg=TEXT if met else TEXT_DIM,
                relief="flat",
                font=self.F_SMALL,
                anchor="w",
                activebackground=ACCENT,
                activeforeground=GOLD,
                cursor="hand2",
                command=lambda n=name: self._select(n),
            ).pack(side="left", fill="x", expand=True)

        self.lbl_date.config(text=f"STARDATE  {data['date']}")
        sav_name = Path(data["path"]).name
        self.var_status.set(
            f"  {data['player'].get('name', '?')}   ·   "
            f"{len(self.empires)} known power(s)   ·   {sav_name}"
        )
        self._sys(
            f"Uplink established — Stardate {data['date']}. "
            f"{len(self.empires)} diplomatic channel(s) available."
        )

    def _poll_for_new_save(self):
        def _poll():
            while True:
                time.sleep(30)
                save_dir = self.var_save_dir.get().strip()
                if save_dir and self.client:
                    self.root.after(0, lambda: self._auto_load_newest(save_dir))

        threading.Thread(target=_poll, daemon=True).start()

    def _select(self, name: str):
        self.selected = name
        self.var_empire.set(name)

    def _on_empire_pick(self, _=None):
        self.selected = self.var_empire.get()

    def _append(self, sender: str, text: str, tag: str = "sys", intent: dict = None):
        self.chat.config(state="normal")
        ts = datetime.now().strftime("%H:%M")
        if tag == "sys":
            self.chat.insert("end", f"  {ts}  ·  {text}\n", "sys")
        elif tag == "you":
            self.chat.insert("end", f"\n  {ts}  ", "ts")
            self.chat.insert("end", f"▶ {sender}\n", "you")
            self.chat.insert("end", f"  {text}\n", "body")
        else:
            self.chat.insert("end", f"\n  {ts}  ", "ts")
            self.chat.insert("end", "─── INCOMING TRANSMISSION ───\n", "divider")
            self.chat.insert("end", f"  {sender}\n", tag)
            self.chat.insert("end", f"  {text}\n", "body")
            if intent:
                det = intent.get("intent", "NONE")
                conf = intent.get("confidence", "?")
                raw = intent.get("raw_intent", "NONE")
                if det != "NONE" and conf in ("high", "medium"):
                    self._sys(
                        f"⚡ Classifier: {raw} → {det}  [{conf}]  {intent.get('reason', '')}"
                    )
                if (
                    det != "NONE"
                    and intent.get("command")
                    and conf in ("high", "medium")
                ):
                    self._embed_intent_badge(intent, sender)
            self.chat.insert("end", "  ─────────────────────────────\n", "divider")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _embed_intent_badge(self, intent: dict, empire_name: str):
        if self.ironman:
            return
        label = intent.get("label", "Action")
        command = intent.get("command", "")
        conf = intent.get("confidence", "medium")
        conf_col = GOLD_TEXT if conf == "high" else "#c87a30"

        frame = tk.Frame(self.chat, bg=ACCENT, relief="flat", bd=0, padx=4, pady=2)

        tk.Label(
            frame, text=f"  ⚡ {label}", bg=ACCENT, fg=conf_col, font=self.F_SMALL
        ).pack(side="left")
        tk.Label(
            frame, text=f"  [{conf}]  ", bg=ACCENT, fg=GOLD_DIM, font=self.F_SMALL
        ).pack(side="left")

        def on_apply(cmd=command, name=empire_name, lbl=label):
            frame.destroy()
            if self.injection_enabled and not self.mock_mode and not self.ironman:

                def _cb(ok, msg, lbl=lbl, name=name):
                    prefix = "[DRY RUN] " if self.var_dry_run.get() else ""
                    if ok:
                        self._sys(f"{prefix}Injected: {lbl} → {name}  | {msg}")
                    else:
                        self._sys(f"Injection failed: {msg}")

                self._queue_inject(cmd, callback=_cb)
            else:
                self._sys(f"[Mock] Would inject: {cmd}")

        def on_dismiss():
            frame.destroy()

        tk.Button(
            frame,
            text="APPLY",
            bg=BTN_GREEN,
            fg=GOLD_TEXT,
            relief="flat",
            font=self.F_SMALL,
            padx=6,
            cursor="hand2",
            command=on_apply,
        ).pack(side="left", padx=(6, 2))
        tk.Button(
            frame,
            text="✕",
            bg=ACCENT,
            fg=GOLD_DIM,
            relief="flat",
            font=self.F_SMALL,
            padx=4,
            cursor="hand2",
            command=on_dismiss,
        ).pack(side="left")

        self.chat.insert("end", "  ")
        self.chat.window_create("end", window=frame)
        self.chat.insert("end", "\n")

    def _sys(self, text: str):
        self._append("SYSTEM", text, "sys")

    def _send(self):
        text = self.var_msg.get().strip()
        if not text:
            return
        if not self.client and not self.mock_mode:
            messagebox.showwarning(
                "No API Key",
                "Enter and save your API key in ⚙ Settings — or enable Mock Mode.",
            )
            return
        if not self.selected or self.selected not in self.empires:
            messagebox.showwarning(
                "No Empire Selected", "Pick an empire from the sidebar first."
            )
            return
        empire = self.empires[self.selected]
        if empire["tag"] not in self.met_tags and self.met_tags:
            if not messagebox.askyesno(
                "Unknown Empire",
                f"{self.selected} has not been contacted yet in-game.\n\n"
                "Send transmission anyway? (breaks immersion)",
            ):
                return
        self.var_msg.set("")
        player_name = self.game_data.get("player", {}).get("name", "Chancellor")
        self._append(f"▶ {player_name}", text, "you")
        with self._lock:
            self.histories[self.selected].append(
                {
                    "role": "user",
                    "content": "[3 sentences max. Sign-off at end only. No bullet points. Stay in character.] "
                    + text,
                }
            )
        threading.Thread(
            target=self._respond, args=(self.selected,), daemon=True
        ).start()

    def _respond(self, name: str):
        if self.mock_mode:
            time.sleep(0.4)
            reply = f"[MOCK] {random.choice(MOCK_RESPONSES)}"
            self.root.after(0, lambda r=reply, n=name: self._append(n, r, n))
            return
        if not self.client:
            self.root.after(
                0,
                lambda: self._sys(
                    "ERROR: No client — did you save your API key in ⚙ Settings?"
                ),
            )
            return
        empire = self.empires.get(name)
        if not empire:
            self.root.after(0, lambda: self._sys(f"ERROR: Empire not found: {name}"))
            return

        try:
            with self._lock:
                history_now = list(self.histories.get(name, []))
                ruler_name_cache = self.ruler_names.get(name, "")

            last_player_msg = next(
                (m["content"] for m in reversed(history_now) if m["role"] == "user"), ""
            )
            msg_lower = last_player_msg.lower()
            player_intent = None
            if any(kw in msg_lower for kw in _KW_PLAYER_INSULT):
                player_intent = "OPINION_DOWN"
            elif any(kw in msg_lower for kw in _KW_WAR):
                player_intent = "WAR_DECLARED"
            if (
                player_intent
                and self.injection_enabled
                and not self.mock_mode
                and not self.ironman
            ):
                cmd_tmpl, label = INTENT_MAP.get(player_intent, (None, None))
                if cmd_tmpl:
                    cmd = cmd_tmpl.format(tag=empire["tag"])
                    self._queue_inject(
                        cmd,
                        callback=lambda ok, msg, l=label, n=name: self.root.after(
                            0, lambda: self._sys(f"⚡ Player action — {l} → {n}")
                        ),
                    )
        except Exception:
            pass

        player = self.game_data.get("player", {})
        date = self.game_data.get("date", "???")
        if name not in self.ruler_names:
            self.ruler_names[name] = _generate_ruler_name(empire)

        ruler_name_for_prompt = self.ruler_names[name]
        known = list(self.empires.keys())

        with self._lock:
            system = build_system_prompt(
                empire,
                player,
                date,
                history=list(self.histories.get(name, [])),
                ruler_name=ruler_name_for_prompt,
                known_empires=known,
            )
            messages = [{"role": "system", "content": system}] + list(
                self.histories.get(name, [])
            )

        with self._llm_sem:
            try:
                reply = call_llm(
                    self.client,
                    self.provider,
                    "chat",
                    messages,
                    max_tokens=MAX_TOKENS_CHAT,
                )
            except Exception as e:
                err_str = str(e)
                if "rate_limit_exceeded" in err_str or "429" in err_str:
                    wait_m = re.search(r"try again in ([\d.]+)m([\d.]+)s", err_str)
                    wait_s = re.search(r"try again in ([\d.]+)s", err_str)
                    if wait_m:
                        wait = float(wait_m.group(1)) * 60 + float(wait_m.group(2))
                    elif wait_s:
                        wait = float(wait_s.group(1))
                    else:
                        wait = 30
                    wait = min(wait + 2, 120)
                    self.root.after(
                        0,
                        lambda w=int(wait), n=name: self._sys(
                            f"Rate limit reached — retrying {n} in {w}s…"
                        ),
                    )
                    time.sleep(wait)
                    try:
                        reply = call_llm(
                            self.client,
                            self.provider,
                            "chat",
                            messages,
                            max_tokens=MAX_TOKENS_CHAT,
                        )
                    except Exception as e2:
                        self.root.after(
                            0,
                            lambda err=str(e2), p=self.provider: self._sys(
                                f"{PROVIDERS[p]['name']} error (retry): {err}"
                            ),
                        )
                        return
                else:
                    import traceback

                    tb = traceback.format_exc()
                    self.root.after(
                        0, lambda err=err_str, t=tb: self._sys(f"LLM error: {err}\n{t}")
                    )
                    return

        with self._lock:
            self.histories[name].append({"role": "assistant", "content": reply})
        self._trim(name)

        llm_client._current_provider = self.provider

        intent = {"intent": "NONE", "command": None, "label": None}
        try:
            intent = detect_intent(
                self.client,
                name,
                empire["tag"],
                reply,
                empire_civics_list=empire.get("civics", []),
                cache=self._intent_cache,
                cache_times=self._intent_cache_times,
                max_age=300,
            )
        except Exception as e:
            self.root.after(
                0, lambda err=str(e): self._sys(f"Intent classifier error: {err}")
            )
            logger.exception(f"Intent classifier error for {name}:")

        self.root.after(
            0, lambda r=reply, n=name, i=intent: self._append(n, r, n, intent=i)
        )

    def _enabled_empires(self) -> list:
        with self._lock:
            return [n for n, v in self.empire_enabled.items() if v.get()]

    def _toggle_all_empires(self):
        state = self.var_all.get()
        for v in self.empire_enabled.values():
            v.set(state)

    def _refresh_all_var(self):
        enabled = self._enabled_empires()
        total = len(self.empire_enabled)
        self.var_all.set(len(enabled) == total)

    def _toggle_auto(self):
        if self.auto_on:
            self.auto_on = False
            self.btn_auto.config(text="▶  AUTO", bg=BTN_GRAY, fg=GOLD)
            self._sys("Auto-comms deactivated.")
        else:
            if not self.empires:
                messagebox.showwarning("No Save", "Load a save file first.")
                return
            if not self.client and not self.mock_mode:
                messagebox.showwarning(
                    "No API Key",
                    "Enter your API key in ⚙ Settings — or enable Mock Mode.",
                )
                return
            if not self._enabled_empires():
                messagebox.showwarning(
                    "No Empires Enabled", "Enable at least one empire in the sidebar."
                )
                return
            self.auto_on = True
            self.btn_auto.config(text="⏹  STOP", bg=BTN_RED, fg=TEXT)
            interval = self.var_interval.get()
            self._sys(f"Auto-comms active — broadcasting every ~{interval}s.")
            threading.Thread(target=self._auto_loop, daemon=True).start()

    def _fire_now(self):
        if not self.empires or (not self.client and not self.mock_mode):
            return
        pool = [
            n
            for n in self._enabled_empires()
            if self.empires.get(n, {}).get("tag") in self.met_tags
        ]
        if not pool:
            return
        name = random.choice(pool)
        threading.Thread(target=self._auto_broadcast, args=(name,), daemon=True).start()

    def _auto_loop(self):
        while self.auto_on:
            pool = [
                n
                for n in self._enabled_empires()
                if self.empires.get(n, {}).get("tag") in self.met_tags
            ]
            if not pool:
                time.sleep(2)
                continue
            name = random.choice(pool)
            threading.Thread(
                target=self._auto_broadcast, args=(name,), daemon=True
            ).start()
            base = self.var_interval.get()
            jitter = int(base * 0.2)
            sleep_t = base + random.randint(-jitter, jitter)
            slept = 0
            while self.auto_on and slept < sleep_t:
                time.sleep(1)
                slept += 1

    def _auto_broadcast(self, name: str):
        if self.mock_mode:
            time.sleep(0.4)
            reply = f"[MOCK] {random.choice(MOCK_RESPONSES)}"
            self.root.after(0, lambda n=name, r=reply: self._append(n, r, n))
            return
        empire = self.empires.get(name)
        if not empire:
            return
        player = self.game_data.get("player", {})
        date = self.game_data.get("date", "???")

        if name not in self.ruler_names:
            with self._lock:
                if name not in self.ruler_names:
                    self.ruler_names[name] = _generate_ruler_name(empire)

        known = list(self.empires.keys())

        with self._lock:
            history_copy = list(self.histories.get(name, []))
            ruler_name_val = self.ruler_names.get(name, "Unknown")

        system = build_system_prompt(
            empire,
            player,
            date,
            history=history_copy,
            ruler_name=ruler_name_val,
            known_empires=known,
        )
        prompt = random.choice(AUTO_PROMPTS)

        with self._lock:
            msgs = (
                [{"role": "system", "content": system}]
                + list(self.histories.get(name, []))
                + [
                    {
                        "role": "user",
                        "content": "[3 sentences max. Sign-off at end only. No bullet points. Stay in character.] "
                        + prompt,
                    }
                ]
            )
        reply = None
        for attempt in range(2):
            try:
                with self._llm_sem:
                    reply = call_llm(
                        self.client,
                        self.provider,
                        "chat",
                        msgs,
                        max_tokens=MAX_TOKENS_CHAT,
                    )
                break
            except Exception as e:
                err_str = str(e)
                if (
                    "rate_limit_exceeded" in err_str or "429" in err_str
                ) and attempt == 0:
                    wait_m = re.search(r"try again in ([\d.]+)m([\d.]+)s", err_str)
                    wait_s = re.search(r"try again in ([\d.]+)s", err_str)
                    if wait_m:
                        wait = float(wait_m.group(1)) * 60 + float(wait_m.group(2))
                    elif wait_s:
                        wait = float(wait_s.group(1))
                    else:
                        wait = 30
                    wait = min(wait + 2, 120)
                    self.root.after(
                        0,
                        lambda w=int(wait): self._sys(
                            f"Rate limit — retrying in {w}s…"
                        ),
                    )
                    time.sleep(wait)
                    continue
                self.root.after(
                    0, lambda err=str(e), n=name: self._sys(f"Auto error [{n}]: {err}")
                )
                logger.exception(f"Auto-broadcast error for {name}:")
                return
        if not reply:
            return

        with self._lock:
            self.histories[name].append({"role": "user", "content": prompt})
            self.histories[name].append({"role": "assistant", "content": reply})
        self._trim(name)

        empire = self.empires.get(name, {})
        intent = detect_intent(
            self.client,
            name,
            empire.get("tag", "0"),
            reply,
            empire_civics_list=empire.get("civics", []),
            cache=self._intent_cache,
            cache_times=self._intent_cache_times,
            max_age=300,
        )
        self.root.after(
            0, lambda n=name, r=reply, i=intent: self._append(n, r, n, intent=i)
        )

    def _contact_all(self):
        if not self.empires:
            messagebox.showwarning("No Save", "Load a save file first.")
            return
        if self.ironman:
            self._sys(
                "Ironman save — cannot use console injection. Use non‑Ironman for this feature."
            )
            return
        if self.mock_mode or not self.injection_enabled:
            with self._lock:
                self.met_tags = {e["tag"] for e in self.empires.values()}
            self._rebuild_sidebar()
            self._sys(
                "Contact All: sidebar unlocked (no injection — mock/injection disabled)."
            )
            return

        self._sys(f"Contact All: queuing 'contact' command…")

        def _cb(ok, msg):
            self._sys(f"Contact All: {msg}")
            with self._lock:
                self.met_tags = {e["tag"] for e in self.empires.values()}
            self._sys(
                f"Contact All: unlocking {len(self.met_tags)} empires in sidebar."
            )
            self.root.after(600, self._rebuild_sidebar)

        self._queue_inject("contact", callback=_cb)

    def _rebuild_sidebar(self):
        with self._lock:
            met_tags_copy = self.met_tags.copy()
        for w in self.frm_empire_btns.winfo_children():
            w.destroy()
        names = list(self.empires.keys())
        self.cmb_empire["values"] = names
        for name in names:
            empire = self.empires[name]
            met = empire["tag"] in met_tags_copy
            col = self.clr[name] if met else GOLD_DIM
            self.chat.tag_config(name, foreground=col, font=self.F_LABEL_B)
            if name not in self.empire_enabled:
                with self._lock:
                    if name not in self.empire_enabled:
                        self.empire_enabled[name] = tk.BooleanVar(value=met)
            row = tk.Frame(self.frm_empire_btns, bg=BG_PANEL)
            row.pack(fill="x", pady=1)
            tk.Checkbutton(
                row,
                variable=self.empire_enabled[name],
                bg=BG_PANEL,
                fg=GOLD_DIM,
                selectcolor=BG_INPUT,
                activebackground=BG_PANEL,
                cursor="hand2",
                command=self._refresh_all_var,
            ).pack(side="left")
            tk.Label(
                row, text="■" if met else "□", bg=BG_PANEL, fg=col, font=("Segoe UI", 8)
            ).pack(side="left")
            btn_text = name[:18] if met else f"? {name[:15]}"
            tk.Button(
                row,
                text=btn_text,
                bg=BG_PANEL,
                fg=TEXT if met else TEXT_DIM,
                relief="flat",
                font=self.F_SMALL,
                anchor="w",
                activebackground=ACCENT,
                activeforeground=GOLD,
                cursor="hand2",
                command=lambda n=name: self._select(n),
            ).pack(side="left", fill="x", expand=True)

    def _broadcast_all(self):
        text = self.var_msg.get().strip()
        if not text:
            messagebox.showwarning(
                "Empty Message", "Type a message before broadcasting to all empires."
            )
            return
        if not self.client and not self.mock_mode:
            messagebox.showwarning(
                "No API Key", "Enter your API key — or enable Mock Mode."
            )
            return

        with self._lock:
            met_tags_copy = self.met_tags.copy()
            enabled_names = [n for n, v in self.empire_enabled.items() if v.get()]

        pool = [
            n
            for n in enabled_names
            if self.empires.get(n, {}).get("tag") in met_tags_copy
        ]
        if not pool:
            messagebox.showwarning(
                "No Known Empires",
                "You haven't made contact with any enabled empires yet.",
            )
            return
        self.var_msg.set("")
        player_name = self.game_data.get("player", {}).get("name", "Chancellor")
        self._append(f"▶ {player_name}  [BROADCAST × {len(pool)}]", text, "you")

        for name in pool:
            with self._lock:
                self.histories[name].append(
                    {
                        "role": "user",
                        "content": "[3 sentences max. Sign-off at end only. No bullet points. Stay in character.] "
                        + text,
                    }
                )
            threading.Thread(target=self._respond, args=(name,), daemon=True).start()

    def _trim(self, name: str, max_pairs: int = 14):
        with self._lock:
            if name not in self.histories:
                return
            h = self.histories[name]
            if len(h) > max_pairs * 2:
                kept = max(2, len(h) - (max_pairs * 2 - 2))
                trimmed = h[:2] + h[kept:]
                self.histories[name] = trimmed

    def _browse_game_dir(self):
        path = filedialog.askdirectory(
            title="Select Stellaris Game Directory",
            initialdir=self.var_game_dir.get() or str(DEFAULT_SAVE_DIR.parent),
        )
        if path:
            self.var_game_dir.set(path)
            self._validate_game_dir()

    def _validate_game_dir(self):
        path = self.var_game_dir.get().strip()
        if not path:
            messagebox.showinfo("Game Directory", "Enter or select a path first.")
            return

        from config import validate_game_dir

        is_valid, diag = validate_game_dir(path)

        if is_valid:
            messagebox.showinfo("Valid", diag)
            self.cfg["game_dir"] = path
            save_config(self.cfg)
            logger.info(f"Game directory validated and saved: {path}")
        else:
            messagebox.showerror("Invalid", diag)
            logger.warning(f"Game directory validation failed: {diag}")
