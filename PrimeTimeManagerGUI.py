#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, date
from dataclasses import dataclass
import threading
import re

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError as e:
    raise SystemExit(
        "Could not found Tkinter/Tk (libtk8.6.so).\n"
        "Install with your paketmanager, e.c.:\n"
        "  Debian/Ubuntu: sudo apt install python3-tk tk8.6\n"
        "  Arch:          sudo pacman -S tk\n"
        "  Fedora:        sudo dnf install python3-tkinter tk\n"
        f"\nFailure: {e}"
    )

# intern imports
from utils.logger import Logger
from utils.source import LoadData
from PrimeTimeManagerApp import initial_logger, show_simulcast, open_url, is_session_active


@dataclass
class WatchlistRow:
    line_index: int
    active: bool
    sep: str
    date_s: str
    episodes_s: str
    rank_s: str
    name_s: str
    url_s: str


class PrimeTimeManagerGUI(tk.Tk):
    WATCH_COLS = ("Active", "Date", "Episodes", "Rank", "Name", "URL")

    def __init__(self):
        super().__init__()
        self.title("PrimeTimeManager")

        # initialize logger
        self.log = Logger()
        initial_logger(self.log)
        self.data = LoadData(self.log)

        self._ui_built = False

        self._save_job = None  # delayed save (config)
        self.config_vars: dict[str, tk.Variable] = {}

        self._app_icon_imgs: list[tk.PhotoImage] = []
        self._set_app_icon()

        # Extra-Config (only config.txt)
        self._extra_config: dict[str, str] = {}

        # Startup-Gate position save (debounced)
        self._gate_pos_job = None
        self._gate_pos_ready = False
        self._gate_last_xy: tuple[int, int] | None = None

        # Default fallback
        self.geometry("1100x750")
        self.resizable(True, True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Watchlist-Editor state
        self._watchlist_lines: list[str] = []
        self._watchlist_rows: list[WatchlistRow] = []
        self._visible_row_ids: list[int] = []  # mapping: tree iid -> index in _watchlist_rows
        self._edit_widget: tk.Entry | None = None
        self._edit_info: tuple[str, str] | None = None  # (item_iid, col_id)

        # Filter (Default: Active)
        self.watch_filter_var = tk.StringVar(value="Active")

        self._watchlist_reload_on_config_change = {
            "showAll",
            "showSimulcast",
            "showSimulcastAdditionalPast",
            "showSimulcastDaysPast",
            "showSimulcastAdditionalFuture",
            "showSimulcastDaysFuture",
            "showWildcard",
        }
        self._watchlist_reload_job = None

        self._did_autofix_watchlist = False

        # Autostart / Startup-Gate State
        self._autostart_job = None
        self._startup_gate_active = False
        self._startup_gate_triggered = False
        self._startup_gate_bind_ids: list[tuple[str, str]] = []  # (sequence, funcid)
        self._startup_gate_win: tk.Toplevel | None = None
        self._startup_gate_label: ttk.Label | None = None

        # Startup-Gate: hide GUI, start timer, user input shows GUI
        self.after_idle(self._start_startup_gate)

    def _ensure_main_ui(self) -> None:
        """Build GUI one time."""
        if self._ui_built:
            return
        self._build_frames()
        self._ui_built = True

    def _set_app_icon(self) -> None:
        """
        Set window and taskbar icon via PNG.
        """
        candidates = [
            "icon_16.png",
            "icon_32.png",
            "icon_48.png",
            "icon_64.png",
            "icon_128.png",
            "icon_256.png",
        ]

        imgs: list[tk.PhotoImage] = []
        for name in candidates:
            try:
                p = self.data.BASE_DIR / "icon" / name
                if not p.exists():
                    continue
                imgs.append(tk.PhotoImage(file=str(p)))
            except Exception:
                continue

        if not imgs:
            return

        # hold icon reference
        self._app_icon_imgs = imgs

        try:
            self.iconphoto(True, *imgs)
        except Exception:
            pass

    def _apply_icon_to_toplevel(self, win: tk.Toplevel) -> None:
        if not self._app_icon_imgs:
            return
        try:
            win.iconphoto(True, *self._app_icon_imgs)
        except Exception:
            pass

    def _restore_window_geometry_from_config(self) -> None:
        raw = self.data.getConfigValue("windowGeometry")
        if not raw:
            return
        geom = str(raw).strip()

        # simple validate: "<w>x<h>+<x>+<y>"
        if not re.match(r"^\d+x\d+\+\-?\d+\+\-?\d+$", geom):
            return
        try:
            self.geometry(geom)
        except Exception:
            pass

    def _on_root_configure(self, _event=None) -> None:
        # only root window
        if self._win_geom_job:
            try:
                self.after_cancel(self._win_geom_job)
            except Exception:
                pass
            self._win_geom_job = None

        self._win_geom_job = self.after(300, self._save_window_geometry_to_config)

    def _save_window_geometry_to_config(self) -> None:
        self._win_geom_job = None
        try:
            geom = self.winfo_geometry()
        except Exception:
            return

        # save in additional config.txt while using save_config_to_file
        self._extra_config["windowGeometry"] = geom
        self.delayed_save()

    def _on_close(self) -> None:
        # flush before closing
        try:
            self.save_config_to_file()
        except Exception:
            pass
        self.destroy()

    def _restore_startup_gate_position_from_config(self, win: tk.Toplevel) -> bool:
        raw_x = self.data.getConfigValue("startupGatePosX")
        raw_y = self.data.getConfigValue("startupGatePosY")
        if raw_x is None or raw_y is None:
            return False
        try:
            x = int(str(raw_x).strip())
            y = int(str(raw_y).strip())
        except Exception:
            return False

        try:
            win.geometry(f"+{x}+{y}")  # only position
            return True
        except Exception:
            return False

    def _center_startup_gate_over_root(self, win: tk.Toplevel) -> None:
        try:
            self.update_idletasks()
            win.update_idletasks()

            w = win.winfo_width()
            h = win.winfo_height()

            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            root_w = self.winfo_width()
            root_h = self.winfo_height()

            x = root_x + (root_w - w) // 2
            y = root_y + (root_h - h) // 3
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _apply_startup_gate_position_after_map(self) -> None:
        win = self._startup_gate_win
        if win is None or not win.winfo_exists():
            return

        # save position
        self._gate_pos_ready = True

        restored = self._restore_startup_gate_position_from_config(win)
        if not restored:
            self._center_startup_gate_over_root(win)

        # poll position
        self._start_startup_gate_position_polling()

    def _start_startup_gate_position_polling(self) -> None:
        if self._gate_pos_job:
            return
        self._gate_last_xy = None
        self._gate_pos_job = self.after(250, self._poll_startup_gate_position)

    def _stop_startup_gate_position_polling(self) -> None:
        if self._gate_pos_job:
            try:
                self.after_cancel(self._gate_pos_job)
            except Exception:
                pass
        self._gate_pos_job = None
        self._gate_last_xy = None

    def _poll_startup_gate_position(self) -> None:
        self._gate_pos_job = None

        win = self._startup_gate_win
        if not self._gate_pos_ready or win is None or not win.winfo_exists():
            return

        try:
            x = int(win.winfo_rootx())
            y = int(win.winfo_rooty())
        except Exception:
            # nochmal versuchen
            self._gate_pos_job = self.after(250, self._poll_startup_gate_position)
            return

        current = (x, y)
        if self._gate_last_xy != current:
            self._gate_last_xy = current
            self._extra_config["startupGatePosX"] = str(x)
            self._extra_config["startupGatePosY"] = str(y)
            self.delayed_save()

        # polling
        self._gate_pos_job = self.after(250, self._poll_startup_gate_position)


    def _on_startup_gate_configure(self, _event=None) -> None:
        # save gate position (debounced)
        if not self._gate_pos_ready:
            return
        if not self._startup_gate_win or not self._startup_gate_win.winfo_exists():
            return

        if self._gate_pos_job:
            try:
                self.after_cancel(self._gate_pos_job)
            except Exception:
                pass
            self._gate_pos_job = None

        self._gate_pos_job = self.after(300, self._save_startup_gate_position_to_config)

    def _save_startup_gate_position_to_config(self) -> None:
        self._gate_pos_job = None
        win = self._startup_gate_win
        if win is None or not win.winfo_exists():
            return

        try:
            x = int(win.winfo_rootx())
            y = int(win.winfo_rooty())
        except Exception:
            return

        self._extra_config["startupGatePosX"] = str(x)
        self._extra_config["startupGatePosY"] = str(y)
        self.delayed_save()

    # =====================================================
    # Auto-Save (Config): with delay
    # =====================================================
    def delayed_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(500, self.save_config_to_file)

    def save_config_to_file(self):
        config_path = self.data.BASE_DIR / "config.txt"

        desired: dict[str, str] = {}

        for key, var in self.config_vars.items():
            val = var.get()
            if isinstance(var, tk.BooleanVar):
                val = "true" if val else "false"
            desired[key] = str(val)

        for key, val in self._extra_config.items():
            if key in self.config_vars:
                continue
            desired[key] = str(val)

        # read existing date
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                old_lines = f.readlines()
        except FileNotFoundError:
            old_lines = []

        # merge line by line: ignore empty or uncommented lines, replace keys
        new_lines: list[str] = []
        seen_keys: set[str] = set()

        for line in old_lines:
            raw = line.rstrip("\n")
            stripped = raw.strip()

            # use unchanged lines
            if not stripped or stripped.startswith("#"):
                new_lines.append(line if line.endswith("\n") else (line + "\n"))
                continue

            # touch only "key = value"
            if "=" not in raw:
                new_lines.append(line if line.endswith("\n") else (line + "\n"))
                continue

            left, _right = raw.split("=", 1)
            key = left.strip()

            # replace key
            if key in desired:
                new_lines.append(f"{key} = {desired[key]}\n")
                seen_keys.add(key)
            else:
                new_lines.append(line if line.endswith("\n") else (line + "\n"))

        # add missing keys
        missing = [k for k in desired.keys() if k not in seen_keys]
        if missing:
            if new_lines and (not new_lines[-1].strip()):
                pass
            elif new_lines:
                new_lines.append("\n")
            new_lines.append("# --- saved by PrimeTimeManager GUI ---\n")
            for k in missing:
                new_lines.append(f"{k} = {desired[k]}\n")

        # write
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    def _start_startup_gate(self):
        """
        Verhalten:
          - Root-GUI starting "invisible"
          - show up only gate window, which accepts inputs
          - if: input is in time of autoStartSeconds: show GUI, cancel autostart
          - else: run PrimeTime logic and dont show GUI
        """
        if self._startup_gate_triggered:
            return

        raw = self.data.getConfigValue("autoStartSeconds")
        try:
            seconds = int(str(raw).strip())
        except Exception:
            seconds = 0

        if seconds <= 0:
            # No Gate: show GUI
            self._ensure_main_ui()
            try:
                self.deiconify()
            except Exception:
                pass
            return

        # hide instantly Root, no window flashing
        try:
            self.withdraw()
        except Exception:
            pass

        self._startup_gate_active = True

        # show gate window (only)
        self._show_startup_gate_window(seconds)

        # set timer
        if self._autostart_job:
            try:
                self.after_cancel(self._autostart_job)
            except Exception:
                pass
            self._autostart_job = None

        self._autostart_job = self.after(seconds * 1000, self._startup_gate_autostart_fire)


    def _show_startup_gate_window(self, seconds: int):
        # if already running: reuse
        if self._startup_gate_win is None or not self._startup_gate_win.winfo_exists():
            win = tk.Toplevel(self)
            win.title("PrimeTimeManager – Autostart")
            win.resizable(False, False)
            self._apply_icon_to_toplevel(win)

            frm = ttk.Frame(win, padding=14)
            frm.pack(fill="both", expand=True)

            lbl = ttk.Label(frm, text="", justify="center")
            lbl.pack()

            ttk.Label(
                frm,
                text="Drücke eine Taste oder klicke, um die GUI zu öffnen.",
                justify="center",
            ).pack(pady=(8, 0))

            self._startup_gate_win = win
            self._startup_gate_label = lbl

            # Accept inputs inside gate window
            win.bind("<KeyPress>", lambda _e: self._startup_gate_user_interaction())
            win.bind("<ButtonPress>", lambda _e: self._startup_gate_user_interaction())
            win.bind("<Escape>", lambda _e: self._startup_gate_user_interaction())

            # force focus
            try:
                win.attributes("-topmost", True)
            except Exception:
                pass

            # gate positioning
            try:
                self.update_idletasks()
                win.update_idletasks()

                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                w = win.winfo_width()
                h = win.winfo_height()

                x = max(0, (sw - w) // 2)
                y = max(0, (sh - h) // 3)
                win.geometry(f"+{x}+{y}")
            except Exception:
                pass

            try:
                win.deiconify()
                win.lift()
                win.focus_force()
            except Exception:
                pass

                # Use the window position and start polling while showing
            try:
                win.after_idle(self._apply_startup_gate_position_after_map)
                win.after(120, self._apply_startup_gate_position_after_map)
            except Exception:
                pass

                # undo topmost
            try:
                win.after(500, lambda: win.attributes("-topmost", False))
            except Exception:
                pass

                # set countdown text
            self._update_startup_gate_countdown(seconds, seconds * 1000)

    def _update_startup_gate_countdown(self, total_seconds: int, remaining_ms: int):
        if not self._startup_gate_active or self._startup_gate_triggered:
            return
        if self._startup_gate_label is None or self._startup_gate_win is None:
            return
        if not self._startup_gate_win.winfo_exists():
            return

        remaining_s = max(0, (remaining_ms + 999) // 1000)
        self._startup_gate_label.config(
            text=f"Autostart in {remaining_s} seconds…\n(without input open automatically)"
        )

        if remaining_ms <= 0:
            return
        self.after(200, lambda: self._update_startup_gate_countdown(total_seconds, remaining_ms - 200))

    def _close_startup_gate_window(self):
        self._stop_startup_gate_position_polling()
        self._gate_pos_ready = False

        if self._startup_gate_win is not None and self._startup_gate_win.winfo_exists():
            try:
                self._startup_gate_win.destroy()
            except Exception:
                pass
        self._startup_gate_win = None
        self._startup_gate_label = None

    def _startup_gate_user_interaction(self):
        """
        First user interaction inside running timer => cancel Autostart, show GUI
        """
        if not self._startup_gate_active or self._startup_gate_triggered:
            return

        self._startup_gate_triggered = True
        self._startup_gate_active = False

        # cancel timer
        if self._autostart_job:
            try:
                self.after_cancel(self._autostart_job)
            except Exception:
                pass
            self._autostart_job = None

        # close Gate window
        self._close_startup_gate_window()

        # show GUI
        self._ensure_main_ui()
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _startup_gate_autostart_fire(self):
        if self._startup_gate_triggered:
            return

        self._startup_gate_triggered = True
        self._startup_gate_active = False
        self._autostart_job = None

        # close gate window
        self._close_startup_gate_window()

        def worker():
            try:
                self._run_main()
            finally:
                try:
                    self.after(0, self.destroy)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _bind_startup_gate_inputs(self):
        if self._startup_gate_bind_ids:
            return

        def handler(_event=None):
            self._startup_gate_user_interaction()

        for seq in ("<KeyPress>", "<ButtonPress>", "<Motion>"):
            funcid = self.bind_all(seq, handler, add="+")
            self._startup_gate_bind_ids.append((seq, funcid))

    def _unbind_startup_gate_inputs(self):
        for seq, funcid in self._startup_gate_bind_ids:
            try:
                self.unbind_all(seq, funcid)
            except Exception:
                pass
        self._startup_gate_bind_ids.clear()

    # =====================================================
    # Layout structure (2 main columns: Config + Watchlist)
    # =====================================================
    def _build_frames(self):
        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=2)
        container.rowconfigure(1, weight=3)
        container.columnconfigure(0, weight=1)

        # --- Config Frame (oben) ---
        self.config_frame = ttk.LabelFrame(container, text="Configuration", padding=10)
        self.config_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self._build_config_ui()

        # --- Watchlist Frame (unten) ---
        self.watch_frame = ttk.LabelFrame(container, text="Filtered Watchlist", padding=10)
        self.watch_frame.grid(row=1, column=0, sticky="nsew")
        self._build_watchlist_ui()

    # =====================================================
    # Config UI with left and right column
    # =====================================================
    def _build_config_ui(self):
        config = self.data.config
        self.config_vars = {}

        # uneditable keys inside UI
        readonly_keys = {"dateSeperatorAllowed", "dateFormats"}

        hidden_keys = {
            "startupGatePosX",
            "startupGatePosY",
            "windowGeometry",
        }

        left_frame = ttk.Frame(self.config_frame)
        right_frame = ttk.Frame(self.config_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))

        normal_items = [
            (k, v)
            for k, v in config.items()
            if not k.lower().startswith("printdebug") and k not in hidden_keys
        ]
        debug_items = [
            (k, v)
            for k, v in config.items()
            if k.lower().startswith("printdebug") and k not in hidden_keys
        ]

        for idx, (key, value) in enumerate(normal_items):
            ttk.Label(left_frame, text=key, anchor="w", width=30).grid(
                row=idx, column=0, sticky="w", padx=4, pady=2
            )

            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                cb = ttk.Checkbutton(
                    left_frame,
                    variable=var,
                    command=lambda k=key: self._on_config_var_changed(k),
                )
                cb.grid(row=idx, column=1, sticky="w")
                var.trace_add("write", lambda *_args, _k=key: self._on_config_var_changed(_k))

                if key in readonly_keys:
                    cb.state(["disabled"])
            else:
                var = tk.StringVar(value=str(value))
                entry = ttk.Entry(left_frame, textvariable=var, width=35)
                entry.grid(row=idx, column=1, sticky="w")
                var.trace_add("write", lambda *_args, _k=key: self._on_config_var_changed(_k))

                if key in readonly_keys:
                    entry.state(["readonly"])

            self.config_vars[key] = var

        for idx, (key, value) in enumerate(debug_items):
            if key == "printDebugToConsole":
                continue

            ttk.Label(right_frame, text=key, anchor="w", width=30).grid(
                row=idx, column=0, sticky="w", padx=4, pady=2
            )

            var = tk.BooleanVar(value=value)
            cb = ttk.Checkbutton(
                right_frame,
                variable=var,
                command=lambda k=key: self._on_config_var_changed(k),
            )
            cb.grid(row=idx, column=1, sticky="w")
            var.trace_add("write", lambda *_args, _k=key: self._on_config_var_changed(_k))

            if key in readonly_keys:
                cb.state(["disabled"])

            self.config_vars[key] = var

    def _on_config_var_changed(self, key: str):
        """
        1) save config (delayed)
        2) while significant keys: reload watchlist (delayed)
        """
        self.delayed_save()

        if key in self._watchlist_reload_on_config_change:
            self._delayed_watchlist_reload()

    def _delayed_watchlist_reload(self):
        if self._watchlist_reload_job:
            self.after_cancel(self._watchlist_reload_job)
        self._watchlist_reload_job = self.after(250, self._reload_watchlist_after_config_change)

    def _reload_watchlist_after_config_change(self):
        self._watchlist_reload_job = None

        # refresh config inside self.data.config
        for k, var in self.config_vars.items():
            val = var.get()
            if str(val).lower() == "true":
                val = True
            elif str(val).lower() == "false":
                val = False
            elif str(val).isdigit():
                val = int(val)
            self.data.config[k] = val

        # reload the watchlist inside the backend
        try:
            self.data.loadWatchDict()
        except Exception as e:
            messagebox.showerror("Watchlist reload failed", str(e))
            return

        # reload UI watchlist table (from the file and the filter)
        self.reload_watchlist()

    # =====================================================
    # Watchlist UI
    # =====================================================
    def _build_watchlist_ui(self):
        top = ttk.Frame(self.watch_frame)
        top.pack(fill="x", pady=(0, 8))

        ttk.Button(top, text="+", width=3, command=self.add_watchlist_entry).pack(side="left")
        ttk.Button(top, text="-", width=3, command=self.open_delete_menu).pack(side="left", padx=(4, 0))

        ttk.Button(top, text="Reload Watchlist", command=self.reload_watchlist).pack(side="left", padx=(6, 0))

        ttk.Label(top, text=" ").pack(side="left", padx=(6, 0))  # kleiner Spacer

        ttk.Label(top, text="Filter:").pack(side="left", padx=(0, 4))
        filter_cb = ttk.Combobox(
            top,
            textvariable=self.watch_filter_var,
            values=["All", "Active", "Inactive"],
            state="readonly",
            width=10,
        )
        filter_cb.pack(side="left")
        filter_cb.bind("<<ComboboxSelected>>", lambda _e: self._populate_watchlist_tree())

        ttk.Label(top, text=" ").pack(side="left", padx=(6, 0))  # kleiner Spacer
        ttk.Label(top, text="Edit lines with double click").pack(side="left")

        ttk.Frame(top).pack(side="left", fill="x", expand=True)

        ttk.Button(top, text="Open in Browser", command=self.open_visible_in_browser).pack(side="right")

        table_frame = ttk.Frame(self.watch_frame)
        table_frame.pack(fill="both", expand=True)

        self.watch_tree = ttk.Treeview(
            table_frame,
            columns=self.WATCH_COLS,
            show="headings",
            selectmode="browse",
        )
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.watch_tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.watch_tree.xview)
        self.watch_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.watch_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        for col in self.WATCH_COLS:
            self.watch_tree.heading(col, text=col)
            if col == "Active":
                self.watch_tree.column(col, width=70, anchor="center")
            elif col == "Name":
                self.watch_tree.column(col, width=320, anchor="w")
            elif col == "URL":
                self.watch_tree.column(col, width=420, anchor="w")
            elif col == "Episodes":
                self.watch_tree.column(col, width=90, anchor="center")
            elif col == "Rank":
                self.watch_tree.column(col, width=70, anchor="center")
            else:
                self.watch_tree.column(col, width=120, anchor="center")

        self.watch_tree.bind("<Double-1>", self._on_tree_double_click)
        self.watch_tree.bind("<Button-1>", self._on_tree_click_anywhere)

        self.reload_watchlist()

    def add_watchlist_entry(self):
        """
        add a new line ahead the watchlist
        After that reload
        """
        watch_path = self.data.BASE_DIR / "watchlist.txt"

        # Simple defaults
        today_s = date.today().strftime("%d-%m-%Y")
        new_line = f"active;{today_s};1;A;New Title;https://example.com\n"

        try:
            with open(watch_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            lines.insert(0, new_line)
            with open(watch_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            messagebox.showerror("Add Entry failed", str(e))
            return

        # Reload
        self._did_autofix_watchlist = True
        self.reload_watchlist()

        try:
            first = self.watch_tree.get_children("")[0]
            self.watch_tree.selection_set(first)
            self.watch_tree.focus(first)
            self.watch_tree.see(first)
        except Exception:
            pass

    def open_delete_menu(self):
        """
        input box
        - delete marked element
        - delete all inactive elements
        """
        win = tk.Toplevel(self)
        win.title("Delete")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="What do you want to delete?").pack(anchor="w", pady=(0, 8))

        ttk.Button(frm, text="Delete marked element", command=lambda: self._delete_marked_and_close(win)).pack(
            fill="x", pady=4
        )
        ttk.Button(frm, text="Delete all inactive elements", command=lambda: self._delete_all_inactive_and_close(win)).pack(
            fill="x", pady=4
        )

        ttk.Separator(frm).pack(fill="x", pady=10)
        ttk.Button(frm, text="Cancel", command=win.destroy).pack(fill="x")

    def _delete_marked_and_close(self, win: tk.Toplevel):
        win.destroy()
        self.delete_marked_element()

    def _delete_all_inactive_and_close(self, win: tk.Toplevel):
        win.destroy()
        self.delete_all_inactive_elements()

    def delete_marked_element(self):
        """
        delete marked element (physically)
        """
        sel = self.watch_tree.selection()
        if not sel:
            messagebox.showinfo("Delete", "No element selected.")
            return

        tree_iid = sel[0]
        try:
            visible_idx = int(tree_iid)
        except ValueError:
            return
        if visible_idx < 0 or visible_idx >= len(self._visible_row_ids):
            return

        row_idx = self._visible_row_ids[visible_idx]
        row = self._watchlist_rows[row_idx]

        if not messagebox.askyesno("Confirm delete", f"Delete: {row.name_s}?"):
            return

        watch_path = self.data.BASE_DIR / "watchlist.txt"
        try:
            with open(watch_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if 0 <= row.line_index < len(lines):
                del lines[row.line_index]
            with open(watch_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
            return

        self.reload_watchlist()

    def delete_all_inactive_elements(self):
        """
        delete all marked as inactive lines
        """
        if not messagebox.askyesno("Confirm delete", "Delete ALL inactive elements from watchlist.txt?"):
            return

        watch_path = self.data.BASE_DIR / "watchlist.txt"
        try:
            with open(watch_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            kept: list[str] = []
            for line in lines:
                stripped = line.lstrip()
                if stripped.lower().startswith("inactive;"):
                    continue
                kept.append(line)

            with open(watch_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
            return

        self.reload_watchlist()

    def reload_watchlist(self):
        try:
            self._load_watchlist_lines_and_rows()
        except Exception as e:
            messagebox.showerror("Loading watchlist failed", str(e))
            return

        # set all series to inactive if episodes==0 or session expired
        if not self._did_autofix_watchlist:
            try:
                changed = self._autofix_active_entries_on_start()
                self._did_autofix_watchlist = True
                if changed > 0:
                    self._load_watchlist_lines_and_rows()
            except Exception as e:
                messagebox.showerror("Auto-Fix watchlist failed", str(e))
                self._did_autofix_watchlist = True

        self._populate_watchlist_tree()

    def _update_data_config_from_ui(self):
        for k, var in self.config_vars.items():
            val = var.get()
            if str(val).lower() == "true":
                val = True
            elif str(val).lower() == "false":
                val = False
            elif str(val).isdigit():
                val = int(val)
            self.data.config[k] = val

    def _in_simulcast_window(self, start_date_obj: date, today: date) -> bool:
        """
        similar to show_simulcast(), which trigger:
        - weekday == today
        - or AdditionalPast/AdditionalFuture window
        """
        if start_date_obj.weekday() == today.weekday():
            return True

        if self.data.getConfigValue("showSimulcastAdditionalPast"):
            for offset in range(1, int(self.data.getConfigValue("showSimulcastDaysPast")) + 1):
                if start_date_obj.weekday() == (today - timedelta(days=offset)).weekday():
                    return True

        if self.data.getConfigValue("showSimulcastAdditionalFuture"):
            for offset in range(1, int(self.data.getConfigValue("showSimulcastDaysFuture")) + 1):
                if start_date_obj.weekday() == (today + timedelta(days=offset)).weekday():
                    return True

        return False

    def _compute_result_row_indices(self) -> list[int]:
        """
        Take Indices (in self._watchlist_rows), from PrimeTime-Logik as results (URLs öffnen)

        Use only active lines
        """
        self._update_data_config_from_ui()

        today = date.today()
        result_indices: list[int] = []
        already_added_urls: set[str] = set()

        for idx, row in enumerate(self._watchlist_rows):
            if not row.active:
                continue

            # parse episodes
            try:
                episodes = int(str(row.episodes_s).strip())
            except ValueError:
                continue

            # Wildcard: -1 => without session check
            if episodes == -1:
                if self.data.getConfigValue("showWildcard"):
                    url = str(row.url_s).strip()
                    if url and url not in already_added_urls:
                        result_indices.append(idx)
                        already_added_urls.add(url)
                continue

            # episodes==0 => equivalent as disabled
            if episodes == 0:
                continue

            # parse date
            try:
                start_d = self.data.parseDate(str(row.date_s).strip())
            except Exception:
                continue

            # expired session
            if not is_session_active(start_d, episodes, today=today):
                continue

            url = str(row.url_s).strip()
            if not url:
                continue

            show_simulcast_cfg = bool(self.data.getConfigValue("showSimulcast"))
            show_all_cfg = bool(self.data.getConfigValue("showAll"))

            # showSimulcast: add URLs if simulcast
            if show_simulcast_cfg:
                if self._in_simulcast_window(start_d, today):
                    if url not in already_added_urls:
                        result_indices.append(idx)
                        already_added_urls.add(url)

            # showAll: (a) add simulcast if showSimulcast
            if show_all_cfg:
                if not show_simulcast_cfg:
                    if self._in_simulcast_window(start_d, today):
                        if url not in already_added_urls:
                            result_indices.append(idx)
                            already_added_urls.add(url)

                if start_d.weekday() != today.weekday():
                    skip = False

                    if self.data.getConfigValue("showSimulcastAdditionalPast"):
                        for offset in range(1, int(self.data.getConfigValue("showSimulcastDaysPast")) + 1):
                            if start_d.weekday() == (today - timedelta(days=offset)).weekday():
                                skip = True
                    if skip:
                        continue

                    if self.data.getConfigValue("showSimulcastAdditionalFuture"):
                        for offset in range(1, int(self.data.getConfigValue("showSimulcastDaysFuture")) + 1):
                            if start_d.weekday() == (today + timedelta(days=offset)).weekday():
                                skip = True
                    if skip:
                        continue

                    if url not in already_added_urls:
                        result_indices.append(idx)
                        already_added_urls.add(url)

        return result_indices

    def _autofix_active_entries_on_start(self) -> int:
        """
        Reflag active elements to inactive if:
          - episodes == -1: Wildcard -> do not reflag
          - episodes == 0: everytime -> inactive
          - episodes > 0: if Session expired -> inactive
        """
        watch_path = self.data.BASE_DIR / "watchlist.txt"

        with open(watch_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        changed = 0
        for row in self._watchlist_rows:
            if not row.active:
                continue

            try:
                episodes = int(str(row.episodes_s).strip())
            except ValueError:
                continue

            # do not touch wildcard
            if episodes == -1:
                continue

            # episodes==0 => inactive
            if episodes == 0:
                should_inactivate = True
            else:
                # episodes > 0: check with the helper class
                try:
                    start_d = self.data.parseDate(str(row.date_s).strip())
                except Exception:
                    continue
                should_inactivate = not is_session_active(start_d, episodes)

            if not should_inactivate:
                continue

            row.active = False
            sep = ";"
            new_line = (
                f"inactive{sep}{row.date_s}{sep}{row.episodes_s}{sep}{row.rank_s}{sep}{row.name_s}{sep}{row.url_s}\n"
            )

            if 0 <= row.line_index < len(lines):
                if not lines[row.line_index].lstrip().lower().startswith("inactive;"):
                    lines[row.line_index] = new_line
                    changed += 1

        if changed > 0:
            with open(watch_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            self._watchlist_lines = lines

        return changed

    def _try_parse_watchlist_line(self, line: str) -> tuple[bool, str, str, str, str, str] | None:
        """
        Expect:
          active;DATE;EP;RANK;NAME;URL
          inactive;DATE;EP;RANK;NAME;URL

        Fallback (Altformat):
          DATE;EP;RANK;NAME;URL => active=True
        """
        parts = [p.strip() for p in line.split(";", 5)]

        # 6 Columns with keys
        if len(parts) == 6:
            keyword, date_s, episodes_s, rank_s, name_s, url_s = parts
            kw = keyword.lower()
            if kw not in {"active", "inactive"}:
                return None
            active = (kw == "active")
            return active, date_s, episodes_s, rank_s, name_s, url_s

        # 5 Columns with keys -> active
        if len(parts) == 5:
            date_s, episodes_s, rank_s, name_s, url_s = parts
            return True, date_s, episodes_s, rank_s, name_s, url_s

        return None

    def _load_watchlist_lines_and_rows(self):
        watch_path = self.data.BASE_DIR / "watchlist.txt"
        with open(watch_path, "r", encoding="utf-8") as f:
            self._watchlist_lines = f.readlines()

        rows: list[WatchlistRow] = []
        for idx, raw in enumerate(self._watchlist_lines):
            original = raw.rstrip("\n")
            stripped = original.strip()
            if not stripped:
                continue

            # ignore comments
            if stripped.startswith("#"):
                continue

            parsed = self._try_parse_watchlist_line(stripped)
            if not parsed:
                continue

            active, date_s, episodes_s, rank_s, name_s, url_s = parsed
            rows.append(
                WatchlistRow(
                    line_index=idx,
                    active=active,
                    sep=";",
                    date_s=date_s,
                    episodes_s=episodes_s,
                    rank_s=rank_s,
                    name_s=name_s,
                    url_s=url_s,
                )
            )

        self._watchlist_rows = rows

    def open_visible_in_browser(self):
        """
        Open url of handled lines in browser
        """
        urls: list[str] = []
        for tree_iid in self.watch_tree.get_children(""):
            visible_idx = int(tree_iid)
            if visible_idx < 0 or visible_idx >= len(self._visible_row_ids):
                continue
            row_idx = self._visible_row_ids[visible_idx]
            row = self._watchlist_rows[row_idx]
            if row.url_s:
                urls.append(row.url_s)

        if not urls:
            messagebox.showinfo("Open in Browser", "No URL to open (empty).")
            return

        open_url(urls)

    def _populate_watchlist_tree(self):
        self._cancel_inline_edit()

        for item in self.watch_tree.get_children():
            self.watch_tree.delete(item)

        # Recalculate result-line (PrimeTime Output)
        result_row_indices = set(self._compute_result_row_indices())

        self._visible_row_ids = []
        filter_value = self.watch_filter_var.get()  # "All" | "Active" | "Inactive"

        for row_idx, row in enumerate(self._watchlist_rows):
            if filter_value == "Active":
                # Active mirroring result
                if not row.active:
                    continue
                if row_idx not in result_row_indices:
                    continue

            elif filter_value == "Inactive":
                if row.active:
                    continue

            # "All" shows all from the file
            iid = str(len(self._visible_row_ids))
            self._visible_row_ids.append(row_idx)

            active_mark = "☑" if row.active else "☐"
            self.watch_tree.insert(
                "",
                "end",
                iid=iid,
                values=(active_mark, row.date_s, row.episodes_s, row.rank_s, row.name_s, row.url_s),
            )

    def _on_tree_click_anywhere(self, event):
        # Cancel editing by click outside
        if self._edit_widget is not None:
            self._commit_inline_edit()

        # Toggle active while clicking on active
        region = self.watch_tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.watch_tree.identify_row(event.y)
        col_id = self.watch_tree.identify_column(event.x)  # '#1'..'#6'
        if not row_id or not col_id:
            return

        col_index = int(col_id.lstrip("#")) - 1
        if col_index != 0:
            return

        visible_idx = int(row_id)
        if visible_idx < 0 or visible_idx >= len(self._visible_row_ids):
            return
        row_idx = self._visible_row_ids[visible_idx]

        self._toggle_row_active(row_id, row_idx)

    def _toggle_row_active(self, tree_iid: str, row_idx: int):
        row = self._watchlist_rows[row_idx]
        row.active = not row.active

        # Refresh UI
        self.watch_tree.set(tree_iid, "Active", "☑" if row.active else "☐")

        # Refresh file
        try:
            self._write_watchlist_row_back(row_idx)
        except Exception as e:
            messagebox.showerror("Speichern fehlgeschlagen", str(e))

        # If the filter is active, hide the line
        current_filter = self.watch_filter_var.get()
        if (current_filter == "Aktiv" and not row.active) or (current_filter == "Inaktiv" and row.active):
            self._populate_watchlist_tree()

    def _on_tree_double_click(self, event):
        region = self.watch_tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.watch_tree.identify_row(event.y)
        col_id = self.watch_tree.identify_column(event.x)
        if not row_id or not col_id:
            return

        col_index = int(col_id.lstrip("#")) - 1
        if col_index < 0 or col_index >= len(self.WATCH_COLS):
            return

        # toggle column only by click, not inline editing
        if self.WATCH_COLS[col_index] == "Active":
            return

        if self._edit_widget is not None:
            self._commit_inline_edit()

        bbox = self.watch_tree.bbox(row_id, col_id)
        if not bbox:
            return

        x, y, w, h = bbox
        value = self.watch_tree.set(row_id, self.WATCH_COLS[col_index])

        self._edit_info = (row_id, col_id)
        self._edit_widget = tk.Entry(self.watch_tree)
        self._edit_widget.insert(0, value)
        self._edit_widget.select_range(0, "end")
        self._edit_widget.focus_set()
        self._edit_widget.place(x=x, y=y, width=w, height=h)

        self._edit_widget.bind("<Return>", lambda _e: self._commit_inline_edit())
        self._edit_widget.bind("<Escape>", lambda _e: self._cancel_inline_edit())
        self._edit_widget.bind("<FocusOut>", lambda _e: self._commit_inline_edit())

    def _cancel_inline_edit(self):
        if self._edit_widget is not None:
            self._edit_widget.destroy()
        self._edit_widget = None
        self._edit_info = None

    def _commit_inline_edit(self):
        if self._edit_widget is None or self._edit_info is None:
            return

        tree_iid, col_id = self._edit_info
        col_index = int(col_id.lstrip("#")) - 1
        col_name = self.WATCH_COLS[col_index]
        new_value = self._edit_widget.get().strip()

        self._cancel_inline_edit()

        self.watch_tree.set(tree_iid, col_name, new_value)

        visible_idx = int(tree_iid)
        if visible_idx < 0 or visible_idx >= len(self._visible_row_ids):
            return
        row_idx = self._visible_row_ids[visible_idx]
        row = self._watchlist_rows[row_idx]

        if col_name == "Episodes":
            if new_value and not (new_value.lstrip("-").isdigit()):
                messagebox.showwarning("Ungültiger Wert", "Episodes muss eine Zahl sein (z.B. 12, 0, -1).")
                self.watch_tree.set(tree_iid, col_name, row.episodes_s)
                return

        if col_name == "Date":
            row.date_s = new_value
        elif col_name == "Episodes":
            row.episodes_s = new_value
        elif col_name == "Rank":
            row.rank_s = new_value
        elif col_name == "Name":
            row.name_s = new_value
        elif col_name == "URL":
            row.url_s = new_value

        try:
            self._write_watchlist_row_back(row_idx)
        except Exception as e:
            messagebox.showerror("Speichern fehlgeschlagen", str(e))

    def _write_watchlist_row_back(self, row_idx: int):
        watch_path = self.data.BASE_DIR / "watchlist.txt"
        row = self._watchlist_rows[row_idx]

        sep = ";"
        keyword = "active" if row.active else "inactive"
        new_line = f"{keyword}{sep}{row.date_s}{sep}{row.episodes_s}{sep}{row.rank_s}{sep}{row.name_s}{sep}{row.url_s}\n"

        with open(watch_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if row.line_index < 0 or row.line_index >= len(lines):
            raise RuntimeError("Interner Fehler: Zeilenindex passt nicht mehr zur Datei. Bitte Reload drücken.")

        lines[row.line_index] = new_line

        with open(watch_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        self._watchlist_lines = lines

    # =====================================================
    # Start thread for main logic
    # =====================================================
    def _run_main_threaded(self):
        threading.Thread(target=self._run_main, daemon=True).start()

    # =====================================================
    # Main logic (CLI → GUI)
    # =====================================================
    def _run_main(self):
        # use GUI inputs
        for key, var in self.config_vars.items():
            val = var.get()
            if str(val).lower() == "true":
                val = True
            elif str(val).lower() == "false":
                val = False
            elif str(val).isdigit():
                val = int(val)
            self.data.config[key] = val

        # reinitialize logger
        self.log = Logger()
        initial_logger(self.log)
        self.data.log = self.log

        url_list = []
        watchlist = self.data.watchlist
        data = self.data

        for item in watchlist:
            simulcast_date = data.getWatchlistValue(item, "Date")
            simulcast_delta = timedelta(weeks=int(data.getWatchlistValue(item, "Episodes")))

            if (data.getWatchlistValue(item, "Episodes") == -1) and not data.getConfigValue("showWildcard"):
                continue
            elif (data.getWatchlistValue(item, "Episodes") == -1) and data.getConfigValue("showWildcard"):
                url_list.append(item["URL"])
                continue

            if (simulcast_date + simulcast_delta) >= date.today():
                if data.getConfigValue("showSimulcast"):
                    show_simulcast(self.log, data, item, url_list)
                if data.getConfigValue("showAll"):
                    if not data.getConfigValue("showSimulcast"):
                        show_simulcast(self.log, data, item, url_list)

                    if not (simulcast_date.weekday() == date.today().weekday()):
                        skip = False
                        if data.getConfigValue("showSimulcastAdditionalPast"):
                            for offset in range(1, int(data.getConfigValue("showSimulcastDaysPast")) + 1):
                                if simulcast_date.weekday() == (date.today() - timedelta(days=offset)).weekday():
                                    skip = True
                        if skip:
                            continue
                        if data.getConfigValue("showSimulcastAdditionalFuture"):
                            for offset in range(1, int(data.getConfigValue("showSimulcastDaysFuture")) + 1):
                                if simulcast_date.weekday() == (date.today() + timedelta(days=offset)).weekday():
                                    skip = True
                        if skip:
                            continue
                        url_list.append(item["URL"])

        open_url(url_list)

if __name__ == "__main__":
    app = PrimeTimeManagerGUI()
    app.mainloop()