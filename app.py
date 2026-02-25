import json
import os
import subprocess
import sys
import tomllib
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import font
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Codex Session Manager"
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
HISTORY_FILE = CODEX_HOME / "history.jsonl"
NOTES_FILE = CODEX_HOME / "session_notes.json"
SESSIONS_DIR = CODEX_HOME / "sessions"
CONFIG_FILE = CODEX_HOME / "config.toml"
MODELS_CACHE_FILE = CODEX_HOME / "models_cache.json"
SKILLS_DIR = CODEX_HOME / "skills"
APP_DIR = Path(__file__).resolve().parent


@dataclass
class SessionItem:
    session_id: str
    ts: int
    text: str
    note: str
    history_count: int
    cwd: str
    model: str
    approval_policy: str
    sandbox_mode: str
    turn_id: str
    session_file: str


@dataclass
class McpItem:
    name: str
    command: str
    timeout: str
    env_count: int
    args: str


@dataclass
class SkillItem:
    name: str
    path: str
    has_scripts: bool
    summary: str


class SessionManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x760")
        self.root.minsize(1020, 620)

        self.items: list[SessionItem] = []
        self.item_by_id: dict[str, SessionItem] = {}
        self.session_notes: dict[str, str] = {}
        self.mcp_items: list[McpItem] = []
        self.skill_items: list[SkillItem] = []
        self.available_models: list[str] = []
        self._mcp_item_map: dict[str, McpItem] = {}
        self._skill_item_map: dict[str, SkillItem] = {}

        self.font_scale = 1.0
        self._base_fonts: dict[str, int] = {}
        self._col_fixed = {"time": 160, "count": 72, "model": 120, "approval": 95, "sandbox": 120}
        self._col_flex_weight = {"session_id": 2, "cwd": 2, "text": 4}

        self._build_ui()
        self._init_fonts()
        self._bind_shortcuts()
        self.refresh()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(top, text="Open Terminal", command=self.open_selected_admin).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="New Chat", command=self.open_new_chat).pack(side=tk.LEFT)
        ttk.Button(top, text="Open Folder", command=self.open_selected_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Open File", command=self.open_selected_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Delete", command=self.delete_selected).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)

        launch = ttk.LabelFrame(self.root, text="Launch Options (Only This Terminal)", padding=8)
        launch.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.model_var = tk.StringVar(value="")
        self.approval_var = tk.StringVar(value="default")
        self.sandbox_var = tk.StringVar(value="default")
        self.search_var = tk.BooleanVar(value=False)
        self.admin_var = tk.BooleanVar(value=True)
        self.show_last_text_var = tk.BooleanVar(value=True)
        self.use_global_defaults_var = tk.BooleanVar(value=True)
        self.use_proxy_var = tk.BooleanVar(value=True)
        self.proxy_scheme_var = tk.StringVar(value="socks5")
        self.proxy_host_var = tk.StringVar(value="127.0.0.1")
        self.proxy_port_var = tk.StringVar(value="7897")

        ttk.Label(launch, text="Model").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.model_box = ttk.Combobox(launch, textvariable=self.model_var, state="readonly", width=24)
        self.model_box["values"] = ("default",)
        self.model_box.current(0)
        self.model_box.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        ttk.Label(launch, text="Approval").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.approval_box = ttk.Combobox(launch, textvariable=self.approval_var, state="readonly", width=12)
        self.approval_box["values"] = ("default", "untrusted", "on-request", "never")
        self.approval_box.grid(row=0, column=3, sticky="w", padx=(0, 10))

        ttk.Label(launch, text="Sandbox").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.sandbox_box = ttk.Combobox(launch, textvariable=self.sandbox_var, state="readonly", width=14)
        self.sandbox_box["values"] = ("default", "read-only", "workspace-write", "danger-full-access")
        self.sandbox_box.grid(row=0, column=5, sticky="w", padx=(0, 10))

        self.search_check = ttk.Checkbutton(launch, text="Search", variable=self.search_var)
        self.search_check.grid(row=0, column=6, sticky="w", padx=(0, 10))
        ttk.Checkbutton(launch, text="Admin", variable=self.admin_var).grid(row=0, column=7, sticky="w")
        ttk.Checkbutton(
            launch,
            text="Show Last Text",
            variable=self.show_last_text_var,
            command=self._toggle_last_text_column,
        ).grid(row=0, column=8, sticky="w", padx=(10, 0))
        ttk.Checkbutton(
            launch,
            text="Use Global Defaults",
            variable=self.use_global_defaults_var,
            command=self._toggle_launch_overrides,
        ).grid(row=0, column=9, sticky="w", padx=(10, 0))

        self.use_proxy_check = ttk.Checkbutton(
            launch,
            text="Use Proxy",
            variable=self.use_proxy_var,
            command=self._toggle_proxy_controls,
        )
        self.use_proxy_check.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(launch, text="Type").grid(row=1, column=1, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_scheme_box = ttk.Combobox(launch, textvariable=self.proxy_scheme_var, state="readonly", width=10)
        self.proxy_scheme_box["values"] = ("http", "socks5")
        self.proxy_scheme_box.grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(launch, text="Host").grid(row=1, column=3, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_host_entry = ttk.Entry(launch, textvariable=self.proxy_host_var, width=20)
        self.proxy_host_entry.grid(row=1, column=4, sticky="ew", pady=(8, 0))
        ttk.Label(launch, text="Port").grid(row=1, column=5, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_port_entry = ttk.Entry(launch, textvariable=self.proxy_port_var, width=8)
        self.proxy_port_entry.grid(row=1, column=6, sticky="w", pady=(8, 0))

        launch.grid_columnconfigure(1, weight=1)
        launch.grid_columnconfigure(4, weight=1)

        table_wrap = ttk.Frame(self.root, padding=(8, 0, 8, 0))
        table_wrap.pack(fill=tk.BOTH, expand=True)

        columns = ("time", "session_id", "count", "model", "approval", "sandbox", "cwd", "text")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings")
        self.tree.heading("time", text="Time")
        self.tree.heading("session_id", text="Session ID")
        self.tree.heading("count", text="Records")
        self.tree.heading("model", text="Model")
        self.tree.heading("approval", text="Approval")
        self.tree.heading("sandbox", text="Sandbox")
        self.tree.heading("cwd", text="CWD")
        self.tree.heading("text", text="Last Text")

        self.tree.column("time", width=160, anchor=tk.W, stretch=False)
        self.tree.column("session_id", width=260, anchor=tk.W, stretch=True)
        self.tree.column("count", width=72, anchor=tk.CENTER, stretch=False)
        self.tree.column("model", width=120, anchor=tk.W, stretch=False)
        self.tree.column("approval", width=95, anchor=tk.W, stretch=False)
        self.tree.column("sandbox", width=120, anchor=tk.W, stretch=False)
        self.tree.column("cwd", width=220, anchor=tk.W, stretch=True)
        self.tree.column("text", width=360, anchor=tk.W, stretch=True)

        yscroll = ttk.Scrollbar(table_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda _e: self.open_selected_admin())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_details_panel())
        self.tree.bind("<Configure>", self._on_tree_resize)
        self.tree.bind("<Button-3>", self._show_context_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open Terminal", command=self.open_selected_admin)
        self.menu.add_command(label="Open File", command=self.open_selected_file)
        self.menu.add_command(label="Open Folder", command=self.open_selected_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Delete", command=self.delete_selected)

        detail_frame = ttk.LabelFrame(self.root, text="Details / MCP / Skills", padding=8)
        detail_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(8, 8))

        self.detail_tabs = ttk.Notebook(detail_frame)
        self.detail_tabs.pack(fill=tk.BOTH, expand=True)
        self._toggle_launch_overrides()
        self._toggle_proxy_controls()

        detail_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(detail_page, text="Session Details")
        self.details_text = tk.Text(detail_page, height=9, wrap=tk.WORD)
        self.details_text.pack(fill=tk.BOTH, expand=True)
        self.details_text.configure(state=tk.DISABLED)
        note_row = ttk.Frame(detail_page)
        note_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(note_row, text="Note").pack(side=tk.LEFT)
        self.note_var = tk.StringVar(value="")
        self.note_entry = ttk.Entry(note_row, textvariable=self.note_var)
        self.note_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(note_row, text="Save Note", command=self.save_selected_note).pack(side=tk.LEFT)
        ttk.Button(note_row, text="Clear", command=self.clear_selected_note).pack(side=tk.LEFT, padx=(6, 0))
        self.note_entry.bind("<Return>", lambda _e: self.save_selected_note())

        mcp_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(mcp_page, text="MCP")
        self.mcp_tree = ttk.Treeview(mcp_page, columns=("name", "command", "timeout", "env", "args"), show="headings", height=8)
        self.mcp_tree.heading("name", text="Name")
        self.mcp_tree.heading("command", text="Command")
        self.mcp_tree.heading("timeout", text="Timeout")
        self.mcp_tree.heading("env", text="Env")
        self.mcp_tree.heading("args", text="Args")
        self.mcp_tree.column("name", width=150, anchor=tk.W)
        self.mcp_tree.column("command", width=120, anchor=tk.W)
        self.mcp_tree.column("timeout", width=70, anchor=tk.CENTER)
        self.mcp_tree.column("env", width=60, anchor=tk.CENTER)
        self.mcp_tree.column("args", width=700, anchor=tk.W)
        mcp_scroll = ttk.Scrollbar(mcp_page, orient=tk.VERTICAL, command=self.mcp_tree.yview)
        self.mcp_tree.configure(yscrollcommand=mcp_scroll.set)
        self.mcp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        mcp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.mcp_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_mcp_details())

        self.mcp_details_text = tk.Text(mcp_page, height=5, wrap=tk.WORD)
        self.mcp_details_text.pack(fill=tk.X, expand=False, pady=(6, 0))
        self.mcp_details_text.configure(state=tk.DISABLED)

        skills_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(skills_page, text="Skills")
        self.skills_tree = ttk.Treeview(skills_page, columns=("name", "scripts", "path", "summary"), show="headings", height=8)
        self.skills_tree.heading("name", text="Name")
        self.skills_tree.heading("scripts", text="Scripts")
        self.skills_tree.heading("path", text="Path")
        self.skills_tree.heading("summary", text="Summary")
        self.skills_tree.column("name", width=160, anchor=tk.W)
        self.skills_tree.column("scripts", width=70, anchor=tk.CENTER)
        self.skills_tree.column("path", width=430, anchor=tk.W)
        self.skills_tree.column("summary", width=450, anchor=tk.W)
        skills_scroll = ttk.Scrollbar(skills_page, orient=tk.VERTICAL, command=self.skills_tree.yview)
        self.skills_tree.configure(yscrollcommand=skills_scroll.set)
        self.skills_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        skills_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.skills_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_skill_details())
        self.skills_tree.bind("<Double-1>", lambda _e: self._open_selected_skill_path())

        self.skill_details_text = tk.Text(skills_page, height=5, wrap=tk.WORD)
        self.skill_details_text.pack(fill=tk.X, expand=False, pady=(6, 0))
        self.skill_details_text.configure(state=tk.DISABLED)

    def _init_fonts(self) -> None:
        style = ttk.Style(self.root)
        default_font = font.nametofont("TkDefaultFont")
        heading_font = font.nametofont("TkHeadingFont")
        text_font = font.nametofont("TkTextFont")
        self._base_fonts = {
            "default": int(default_font.cget("size")),
            "heading": int(heading_font.cget("size")),
            "text": int(text_font.cget("size")),
        }
        style.configure("Treeview", rowheight=30, font=default_font)
        style.configure("Treeview.Heading", font=heading_font)
        self.details_text.configure(font=text_font, relief=tk.FLAT, bd=0, padx=8, pady=8)
        self.tree.tag_configure("odd", background="#f7f9fc")
        self.tree.tag_configure("even", background="#ffffff")

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel_windows)
        self.root.bind_all("<Control-Button-4>", self._on_ctrl_wheel_linux_up)
        self.root.bind_all("<Control-Button-5>", self._on_ctrl_wheel_linux_down)

    def _on_ctrl_wheel_windows(self, event: tk.Event) -> str:
        delta = 1 if getattr(event, "delta", 0) > 0 else -1
        self._apply_zoom(delta)
        return "break"

    def _on_ctrl_wheel_linux_up(self, _event: tk.Event) -> str:
        self._apply_zoom(1)
        return "break"

    def _on_ctrl_wheel_linux_down(self, _event: tk.Event) -> str:
        self._apply_zoom(-1)
        return "break"

    def _apply_zoom(self, delta: int) -> None:
        new_scale = max(0.8, min(1.8, self.font_scale + (0.1 * delta)))
        if abs(new_scale - self.font_scale) < 1e-6:
            return
        self.font_scale = new_scale
        style = ttk.Style(self.root)
        default_font = font.nametofont("TkDefaultFont")
        heading_font = font.nametofont("TkHeadingFont")
        text_font = font.nametofont("TkTextFont")
        default_font.configure(size=max(9, int(round(self._base_fonts["default"] * self.font_scale))))
        heading_font.configure(size=max(9, int(round(self._base_fonts["heading"] * self.font_scale))))
        text_font.configure(size=max(9, int(round(self._base_fonts["text"] * self.font_scale))))
        style.configure("Treeview", rowheight=max(24, int(round(30 * self.font_scale))), font=default_font)
        style.configure("Treeview.Heading", font=heading_font)
        self.details_text.configure(font=text_font)
        self.status_var.set(f"Zoom {int(self.font_scale * 100)}%")

    def _on_tree_resize(self, event: tk.Event) -> None:
        total = max(300, int(getattr(event, "width", 0)))
        fixed = sum(self._col_fixed.values())
        available = max(300, total - fixed - 28)
        flex_weights = dict(self._col_flex_weight)
        if not self.show_last_text_var.get():
            flex_weights["text"] = 0
        weight_sum = max(1, sum(flex_weights.values()))
        for name, weight in flex_weights.items():
            if name == "text" and not self.show_last_text_var.get():
                self.tree.column("text", width=0, minwidth=0, stretch=False)
                continue
            width = int(available * (weight / weight_sum))
            self.tree.column(name, width=max(120, width))

    def _toggle_last_text_column(self) -> None:
        if self.show_last_text_var.get():
            self.tree.heading("text", text="Last Text")
            self.tree.column("text", width=360, minwidth=80, stretch=True)
        else:
            self.tree.heading("text", text="")
            self.tree.column("text", width=0, minwidth=0, stretch=False)
        # Re-run layout after toggling the column.
        class E:
            width = self.tree.winfo_width()
        self._on_tree_resize(E())

    def _show_context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def refresh(self) -> None:
        try:
            self.session_notes = self._load_session_notes()
            self.items = self._load_sessions()
            self.item_by_id = {i.session_id: i for i in self.items}
            self.mcp_items = self._load_mcp_items()
            self.skill_items = self._load_skill_items()
            self.available_models = self._load_available_models()
            self._render_items()
            self._render_mcp_items()
            self._render_skill_items()
            self._render_models()
            self.status_var.set(
                f"Loaded sessions={len(self.items)} mcp={len(self.mcp_items)} skills={len(self.skill_items)}"
            )
        except Exception as exc:
            self.status_var.set("Load failed")
            messagebox.showerror("Error", f"Failed to load data:\n{exc}")

    def _load_session_notes(self) -> dict[str, str]:
        if not NOTES_FILE.exists():
            return {}
        try:
            raw = NOTES_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in obj.items():
                key = str(k).strip()
                if not key:
                    continue
                out[key] = str(v)
            return out
        except Exception:
            return {}

    def _save_session_notes(self) -> None:
        NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.session_notes, ensure_ascii=False, indent=2)
        NOTES_FILE.write_text(content, encoding="utf-8")

    def _load_sessions(self) -> list[SessionItem]:
        if not HISTORY_FILE.exists():
            raise FileNotFoundError(f"history file not found: {HISTORY_FILE}")

        latest: dict[str, dict[str, int | str]] = {}
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = obj.get("session_id")
                ts = int(obj.get("ts", 0))
                text = str(obj.get("text", ""))
                if not session_id:
                    continue
                prev = latest.get(session_id)
                if prev is None:
                    latest[session_id] = {"ts": ts, "text": text, "count": 1}
                else:
                    prev["count"] = int(prev["count"]) + 1
                    if ts >= int(prev["ts"]):
                        prev["ts"] = ts
                        prev["text"] = text

        items: list[SessionItem] = []
        for sid, data in latest.items():
            ts = int(data["ts"])
            text = str(data["text"])
            count = int(data["count"])
            session_file = self._find_session_file(sid)
            details = self._extract_session_details(session_file) if session_file else {}
            items.append(
                SessionItem(
                    session_id=sid,
                    ts=ts,
                    text=text,
                    note=self.session_notes.get(sid, ""),
                    history_count=count,
                    cwd=str(details.get("cwd", "")),
                    model=str(details.get("model", "")),
                    approval_policy=str(details.get("approval_policy", "")),
                    sandbox_mode=str(details.get("sandbox_mode", "")),
                    turn_id=str(details.get("turn_id", "")),
                    session_file=session_file or "",
                )
            )

        items.sort(key=lambda i: i.ts, reverse=True)
        return items

    def _load_mcp_items(self) -> list[McpItem]:
        items: list[McpItem] = []
        if not CONFIG_FILE.exists():
            return items
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            conf = tomllib.loads(raw)
        except Exception:
            return self._load_mcp_items_fallback()

        servers = conf.get("mcp_servers", {})
        if not isinstance(servers, dict):
            return items

        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            command = str(cfg.get("command", ""))
            timeout = str(cfg.get("startup_timeout_sec", ""))
            args_cfg = cfg.get("args", [])
            args = " ".join(str(x) for x in args_cfg) if isinstance(args_cfg, list) else str(args_cfg)
            env_cfg = cfg.get("env", {})
            env_count = len(env_cfg) if isinstance(env_cfg, dict) else 0
            items.append(
                McpItem(
                    name=str(name),
                    command=command,
                    timeout=timeout,
                    env_count=env_count,
                    args=args,
                )
            )

        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_mcp_items_fallback(self) -> list[McpItem]:
        # Fallback parser for non-strict TOML files; extracts MCP blocks by headers.
        text = CONFIG_FILE.read_text(encoding="utf-8-sig", errors="ignore")
        lines = text.splitlines()
        block: dict[str, dict[str, object]] = {}
        current = ""
        in_env = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                header = line[1:-1].strip()
                in_env = False
                current = ""
                if header.startswith("mcp_servers."):
                    parts = header.split(".")
                    if len(parts) >= 2:
                        current = parts[1]
                        in_env = len(parts) >= 3 and parts[2] == "env"
                        if current not in block:
                            block[current] = {
                                "command": "",
                                "timeout": "",
                                "args": "",
                                "env_count": 0,
                            }
                continue
            if not current or current not in block:
                continue
            item = block[current]
            if in_env:
                if "=" in line and not line.startswith("#"):
                    item["env_count"] = int(item["env_count"]) + 1
                continue
            if line.startswith("command"):
                item["command"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("startup_timeout_sec"):
                item["timeout"] = line.split("=", 1)[1].strip()
            elif line.startswith("args"):
                item["args"] = line.split("=", 1)[1].strip()

        items: list[McpItem] = []
        for name, obj in block.items():
            items.append(
                McpItem(
                    name=name,
                    command=str(obj.get("command", "")),
                    timeout=str(obj.get("timeout", "")),
                    env_count=int(obj.get("env_count", 0)),
                    args=str(obj.get("args", "")),
                )
            )
        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_skill_items(self) -> list[SkillItem]:
        items: list[SkillItem] = []
        if not SKILLS_DIR.exists():
            return items

        for skill_md in SKILLS_DIR.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            name = skill_dir.name
            has_scripts = (skill_dir / "scripts").exists()
            summary = ""
            try:
                with skill_md.open("r", encoding="utf-8") as f:
                    for line in f:
                        t = line.strip()
                        if t and not t.startswith("#"):
                            summary = t
                            break
            except Exception:
                summary = ""

            items.append(
                SkillItem(
                    name=name,
                    path=str(skill_dir),
                    has_scripts=has_scripts,
                    summary=summary,
                )
            )

        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_available_models(self) -> list[str]:
        models: list[str] = []
        if MODELS_CACHE_FILE.exists():
            try:
                with MODELS_CACHE_FILE.open("r", encoding="utf-8-sig", errors="ignore") as f:
                    data = json.load(f)
                raw_models = data.get("models", [])
                if isinstance(raw_models, list):
                    for item in raw_models:
                        if not isinstance(item, dict):
                            continue
                        visibility = str(item.get("visibility", ""))
                        if visibility and visibility != "list":
                            continue
                        slug = str(item.get("slug", "")).strip()
                        if slug:
                            models.append(slug)
            except Exception:
                models = []
        if not models:
            models = ["gpt-5.3-codex", "gpt-5"]
        # Keep unique order
        seen: set[str] = set()
        uniq: list[str] = []
        for m in models:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        return uniq

    def _render_models(self) -> None:
        values = ["default", *self.available_models]
        self.model_box["values"] = values
        current = self.model_var.get().strip()
        if not current or current not in values:
            self.model_var.set("default")

    def _find_session_file(self, session_id: str) -> str | None:
        if not SESSIONS_DIR.exists():
            return None
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for name in files:
                if session_id in name and name.endswith(".jsonl"):
                    return str(Path(root) / name)
        return None

    def _extract_session_details(self, session_file: str) -> dict[str, str]:
        if not session_file:
            return {}
        details: dict[str, str] = {
            "cwd": "",
            "model": "",
            "approval_policy": "",
            "sandbox_mode": "",
            "turn_id": "",
        }
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "turn_context":
                        payload = obj.get("payload", {})
                        details["cwd"] = str(payload.get("cwd", details["cwd"]))
                        details["model"] = str(payload.get("model", details["model"]))
                        details["approval_policy"] = str(payload.get("approval_policy", details["approval_policy"]))
                        sandbox_policy = payload.get("sandbox_policy", {})
                        if isinstance(sandbox_policy, dict):
                            details["sandbox_mode"] = str(sandbox_policy.get("type", details["sandbox_mode"]))
                        details["turn_id"] = str(payload.get("turn_id", details["turn_id"]))
        except OSError:
            return {}
        return details

    def _render_items(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for idx, item in enumerate(self.items):
            timestr = datetime.fromtimestamp(item.ts).strftime("%Y-%m-%d %H:%M:%S") if item.ts else ""
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert(
                "",
                tk.END,
                iid=item.session_id,
                values=(
                    timestr,
                    item.session_id,
                    item.history_count,
                    item.model,
                    item.approval_policy,
                    item.sandbox_mode,
                    item.cwd,
                    item.text.replace("\n", " "),
                ),
                tags=(tag,),
            )
        self._update_details_panel()

    def _render_mcp_items(self) -> None:
        for iid in self.mcp_tree.get_children():
            self.mcp_tree.delete(iid)
        self._mcp_item_map.clear()
        for idx, item in enumerate(self.mcp_items):
            tag = "even" if idx % 2 == 0 else "odd"
            iid = f"mcp_{idx}"
            self.mcp_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(item.name, item.command, item.timeout, item.env_count, item.args),
                tags=(tag,),
            )
            self._mcp_item_map[iid] = item
        self.mcp_tree.tag_configure("odd", background="#f7f9fc")
        self.mcp_tree.tag_configure("even", background="#ffffff")
        self._update_mcp_details()

    def _render_skill_items(self) -> None:
        for iid in self.skills_tree.get_children():
            self.skills_tree.delete(iid)
        self._skill_item_map.clear()
        for idx, item in enumerate(self.skill_items):
            tag = "even" if idx % 2 == 0 else "odd"
            iid = f"skill_{idx}"
            self.skills_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(item.name, "yes" if item.has_scripts else "no", item.path, item.summary),
                tags=(tag,),
            )
            self._skill_item_map[iid] = item
        self.skills_tree.tag_configure("odd", background="#f7f9fc")
        self.skills_tree.tag_configure("even", background="#ffffff")
        self._update_skill_details()

    def _update_mcp_details(self) -> None:
        sel = self.mcp_tree.selection()
        if not sel:
            text = "Select an MCP row to view details."
        else:
            item = self._mcp_item_map.get(sel[0])
            if not item:
                text = "No details."
            else:
                text = (
                    f"Name: {item.name}\n"
                    f"Command: {item.command or '-'}\n"
                    f"Timeout: {item.timeout or '-'}\n"
                    f"Env Vars: {item.env_count}\n"
                    f"Args: {item.args or '-'}\n"
                )
        self.mcp_details_text.configure(state=tk.NORMAL)
        self.mcp_details_text.delete("1.0", tk.END)
        self.mcp_details_text.insert("1.0", text)
        self.mcp_details_text.configure(state=tk.DISABLED)

    def _update_skill_details(self) -> None:
        sel = self.skills_tree.selection()
        if not sel:
            text = "Select a skill row to view details. Double-click to open its folder."
        else:
            item = self._skill_item_map.get(sel[0])
            if not item:
                text = "No details."
            else:
                text = (
                    f"Name: {item.name}\n"
                    f"Path: {item.path}\n"
                    f"Has scripts/: {'yes' if item.has_scripts else 'no'}\n"
                    f"Summary: {item.summary or '-'}\n"
                )
        self.skill_details_text.configure(state=tk.NORMAL)
        self.skill_details_text.delete("1.0", tk.END)
        self.skill_details_text.insert("1.0", text)
        self.skill_details_text.configure(state=tk.DISABLED)

    def _open_selected_skill_path(self) -> None:
        sel = self.skills_tree.selection()
        if not sel:
            return
        item = self._skill_item_map.get(sel[0])
        if not item:
            return
        p = Path(item.path)
        if p.exists():
            os.startfile(str(p))  # type: ignore[attr-defined]

    def _update_details_panel(self) -> None:
        item = self._selected_session()
        if not item:
            self.note_entry.configure(state="disabled")
            self.note_var.set("")
            content = "Select a session to view detailed metadata."
        else:
            self.note_entry.configure(state="normal")
            note = self.session_notes.get(item.session_id, item.note)
            item.note = note
            self.note_var.set(note)
            time_str = datetime.fromtimestamp(item.ts).strftime("%Y-%m-%d %H:%M:%S") if item.ts else ""
            content = (
                f"Session ID: {item.session_id}\n"
                f"Last Time: {time_str}\n"
                f"History Records: {item.history_count}\n"
                f"Model: {item.model or '-'}\n"
                f"Approval Policy: {item.approval_policy or '-'}\n"
                f"Sandbox Mode: {item.sandbox_mode or '-'}\n"
                f"Turn ID: {item.turn_id or '-'}\n"
                f"CWD: {item.cwd or '-'}\n"
                f"Note: {note or '-'}\n"
                f"Session File: {item.session_file or '-'}\n"
                f"Last Text:\n{item.text or '-'}\n"
            )
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", content)
        self.details_text.configure(state=tk.DISABLED)

    def save_selected_note(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        note = self.note_var.get().strip()
        if note:
            self.session_notes[item.session_id] = note
        else:
            self.session_notes.pop(item.session_id, None)
        item.note = note
        self._save_session_notes()
        self._update_details_panel()
        self.status_var.set(f"Saved note for {item.session_id}")

    def clear_selected_note(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        self.note_var.set("")
        self.session_notes.pop(item.session_id, None)
        item.note = ""
        self._save_session_notes()
        self._update_details_panel()
        self.status_var.set(f"Cleared note for {item.session_id}")

    def _selected_session(self) -> SessionItem | None:
        selected = self.tree.selection()
        if not selected:
            return None
        sid = selected[0]
        return self.item_by_id.get(sid)

    def _build_codex_override_args(self) -> list[str]:
        if self.use_global_defaults_var.get():
            return []
        args: list[str] = []
        model = self.model_var.get().strip()
        if model and model != "default":
            args.extend(["-m", model])

        approval = self.approval_var.get().strip()
        if approval and approval != "default":
            args.extend(["-a", approval])

        sandbox = self.sandbox_var.get().strip()
        if sandbox and sandbox != "default":
            args.extend(["-s", sandbox])

        if self.search_var.get():
            args.append("--search")
        return args

    def _build_codex_resume_args(self, item: SessionItem) -> list[str]:
        args: list[str] = ["codex.cmd", "resume", item.session_id]
        args.extend(self._build_codex_override_args())
        return args

    def _build_codex_new_args(self) -> list[str]:
        args: list[str] = ["codex.cmd"]
        args.extend(self._build_codex_override_args())
        return args

    def _toggle_launch_overrides(self) -> None:
        if self.use_global_defaults_var.get():
            state = "disabled"
        else:
            state = "readonly"
        self.model_box.configure(state=state)
        self.approval_box.configure(state=state)
        self.sandbox_box.configure(state=state)
        self.search_check.configure(state="disabled" if self.use_global_defaults_var.get() else "normal")

    def _to_ps_arg_string(self, args: list[str]) -> str:
        escaped: list[str] = []
        for a in args:
            escaped.append("'" + a.replace("'", "''") + "'")
        return " ".join(escaped)

    def _build_proxy_ps_prefix(self) -> str:
        if not self.use_proxy_var.get():
            return ""
        scheme = self.proxy_scheme_var.get().strip().lower() or "http"
        host = self.proxy_host_var.get().strip() or "127.0.0.1"
        port_text = self.proxy_port_var.get().strip()
        if not port_text.isdigit():
            raise ValueError("Proxy port must be an integer.")
        port = int(port_text)
        if port < 1 or port > 65535:
            raise ValueError("Proxy port must be between 1 and 65535.")
        proxy_url = f"{scheme}://{host}:{port}"
        proxy_escaped = proxy_url.replace("'", "''")
        no_proxy = "localhost,127.0.0.1,::1"
        no_proxy_escaped = no_proxy.replace("'", "''")
        return (
            f"$proxy='{proxy_escaped}'; "
            "$env:HTTP_PROXY=$proxy; $env:HTTPS_PROXY=$proxy; $env:ALL_PROXY=$proxy; "
            "$env:http_proxy=$proxy; $env:https_proxy=$proxy; $env:all_proxy=$proxy; "
            f"$env:NO_PROXY='{no_proxy_escaped}'; $env:no_proxy=$env:NO_PROXY; "
        )

    def _toggle_proxy_controls(self) -> None:
        proxy_controls_enabled = self.use_proxy_var.get()
        state = "readonly" if proxy_controls_enabled else "disabled"
        entry_state = "normal" if proxy_controls_enabled else "disabled"
        self.proxy_scheme_box.configure(state=state)
        self.proxy_host_entry.configure(state=entry_state)
        self.proxy_port_entry.configure(state=entry_state)
        self.use_proxy_check.configure(state="normal")

    def _build_terminal_ps_command(self, cwd: str, codex_args: list[str]) -> str:
        cwd_escaped = cwd.replace("'", "''")
        proxy_prefix = self._build_proxy_ps_prefix()
        return (
            "chcp 65001 > $null; "
            "$utf8 = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::InputEncoding = $utf8; "
            "[Console]::OutputEncoding = $utf8; "
            "$OutputEncoding = $utf8; "
            f"{proxy_prefix}"
            f"Set-Location -LiteralPath '{cwd_escaped}'; "
            f"& {self._to_ps_arg_string(codex_args)}"
        )

    def open_selected_admin(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        cwd = item.cwd or str(Path.home())

        codex_args = self._build_codex_resume_args(item)
        try:
            ps_command = self._build_terminal_ps_command(cwd, codex_args)
        except ValueError as exc:
            messagebox.showerror("Invalid Proxy", str(exc))
            return

        args = ["-NoExit", "-Command", ps_command]
        start_process = "Start-Process powershell "
        if self.admin_var.get():
            start_process += "-Verb RunAs "
        arg_items: list[str] = []
        for a in args:
            arg_items.append("'" + a.replace("'", "''") + "'")
        start_process += f"-ArgumentList @({','.join(arg_items)})"

        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_process])
            if self.use_proxy_var.get():
                net_text = "net=proxy"
            else:
                net_text = "net=direct"
            self.status_var.set(f"Started codex resume cwd={cwd} ({net_text})")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to start terminal:\n{exc}")

    def open_new_chat(self) -> None:
        target_dir = filedialog.askdirectory(
            title="Select working folder for new chat",
            initialdir=str(Path.home()),
            mustexist=True,
        )
        if not target_dir:
            return
        codex_args = self._build_codex_new_args()
        try:
            ps_command = self._build_terminal_ps_command(target_dir, codex_args)
        except ValueError as exc:
            messagebox.showerror("Invalid Proxy", str(exc))
            return
        args = ["-NoExit", "-Command", ps_command]
        start_process = "Start-Process powershell "
        if self.admin_var.get():
            start_process += "-Verb RunAs "
        arg_items: list[str] = []
        for a in args:
            arg_items.append("'" + a.replace("'", "''") + "'")
        start_process += f"-ArgumentList @({','.join(arg_items)})"

        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_process])
            mode_text = "global defaults" if self.use_global_defaults_var.get() else "custom options"
            if self.use_proxy_var.get():
                net_text = "net=proxy"
            else:
                net_text = "net=direct"
            self.status_var.set(f"Started new chat in {target_dir} ({mode_text}, {net_text})")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to start new chat:\n{exc}")

    def open_selected_file(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return
        if not item.session_file:
            messagebox.showwarning("Warning", "Session file not found.")
            return
        try:
            os.startfile(item.session_file)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open file:\n{exc}")

    def open_selected_folder(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        if item.cwd and Path(item.cwd).exists():
            folder = item.cwd
        elif item.session_file and Path(item.session_file).exists():
            folder = str(Path(item.session_file).parent)
        else:
            folder = str(APP_DIR)

        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open folder:\n{exc}")

    def delete_selected(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        ok = messagebox.askyesno(
            "Confirm Delete",
            f"Delete session {item.session_id}?\n\nThis removes it from history and deletes matching session files.",
        )
        if not ok:
            return

        try:
            self._delete_session(item.session_id)
            self.refresh()
            self.status_var.set(f"Deleted {item.session_id}")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to delete session:\n{exc}")

    def _delete_session(self, session_id: str) -> None:
        if session_id in self.session_notes:
            self.session_notes.pop(session_id, None)
            self._save_session_notes()

        if HISTORY_FILE.exists():
            lines_out: list[str] = []
            with HISTORY_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    if session_id not in line:
                        lines_out.append(line)
            with HISTORY_FILE.open("w", encoding="utf-8", newline="") as f:
                f.writelines(lines_out)

        if SESSIONS_DIR.exists():
            for root, _dirs, files in os.walk(SESSIONS_DIR):
                for name in files:
                    if session_id in name and name.endswith(".jsonl"):
                        p = Path(root) / name
                        try:
                            p.unlink()
                        except OSError:
                            pass


def main() -> int:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    SessionManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
