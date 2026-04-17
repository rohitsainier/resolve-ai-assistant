#!/usr/bin/env python3
"""Tkinter-based UI for AI Edit Assistant.

Used in place of the Fusion UIManager (which is unavailable in Resolve Free).
Same workflow: configure -> analyze -> review markers -> apply.
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class AssistantDialog:
    """Main configuration + progress dialog."""

    WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]

    def __init__(self, timeline_name: str, duration_min: float, est_cost: float):
        self.root = tk.Tk()
        self.root.title("AI Edit Assistant")
        self.root.geometry("520x680")
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

        # Output state
        self.cancelled = True  # default to cancelled unless Analyze clicked
        self.options = {}
        self.analyze_clicked = False
        self._on_analyze: Optional[Callable] = None
        self._closing = False
        # Thread-safe queue: workers push (pct, status, eta) tuples;
        # Tk polls and applies on the main thread.
        self._ui_queue: "queue.Queue[tuple]" = queue.Queue()

        self._build(timeline_name, duration_min, est_cost)
        # Start polling
        self.root.after(100, self._drain_queue)

    def _build(self, timeline_name, duration_min, est_cost):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="🎬 AI Edit Assistant",
                  font=("", 16, "bold")).pack(pady=(0, 8))
        ttk.Label(main, text="🟢 Highlight   🔴 Dead Air   🔵 Short Clip   🟡 Chapter").pack()

        sep = ttk.Separator(main, orient="horizontal")
        sep.pack(fill="x", pady=8)

        info = ttk.Frame(main)
        info.pack(fill="x", **pad)
        ttk.Label(info, text=f"Timeline:  {timeline_name}").pack(anchor="w")
        ttk.Label(info, text=f"Duration:  {duration_min:.1f} min     Est. cost: ${est_cost:.3f}").pack(anchor="w")

        # Whisper model
        wm = ttk.Frame(main)
        wm.pack(fill="x", **pad)
        ttk.Label(wm, text="Whisper model:").pack(side="left")
        self.whisper_var = tk.StringVar(value="base")
        cb = ttk.Combobox(wm, textvariable=self.whisper_var,
                          values=self.WHISPER_MODELS, state="readonly", width=10)
        cb.pack(side="left", padx=8)

        # Analysis options
        ttk.Label(main, text="Analysis options:", font=("", 11, "bold")).pack(anchor="w", pady=(8, 0), padx=10)
        self.var_highlights = tk.BooleanVar(value=True)
        self.var_deadair = tk.BooleanVar(value=True)
        self.var_shorts = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="Find highlights (green markers)",
                        variable=self.var_highlights).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Mark dead air (red markers)",
                        variable=self.var_deadair).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Identify shorts (blue markers)",
                        variable=self.var_shorts).pack(anchor="w", padx=20)

        # Actions
        ttk.Label(main, text="Actions:", font=("", 11, "bold")).pack(anchor="w", pady=(8, 0), padx=10)
        self.var_shorts_tl = tk.BooleanVar(value=False)
        self.var_rough_cut = tk.BooleanVar(value=False)
        self.var_fillers = tk.BooleanVar(value=False)
        self.var_chapters = tk.BooleanVar(value=False)
        self.var_subs = tk.BooleanVar(value=False)
        ttk.Checkbutton(main, text="Create separate Shorts timeline",
                        variable=self.var_shorts_tl).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Generate rough cut (dead air removed)",
                        variable=self.var_rough_cut).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Detect filler words (um, uh, like)",
                        variable=self.var_fillers).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Generate chapters + YouTube description",
                        variable=self.var_chapters).pack(anchor="w", padx=20)
        ttk.Checkbutton(main, text="Export subtitles (.srt + .vtt)",
                        variable=self.var_subs).pack(anchor="w", padx=20)

        self.var_use_cache = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="Use cached transcript if available",
                        variable=self.var_use_cache).pack(anchor="w", padx=20, pady=(8, 0))

        # Status + progress
        self.status_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.status_var,
                  foreground="#225").pack(pady=(10, 2))
        self.progress = ttk.Progressbar(main, length=440, mode="determinate", maximum=100)
        self.progress.pack(pady=2)
        self.eta_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.eta_var,
                  foreground="#666", font=("", 9)).pack()

        # Buttons row 1
        btns = ttk.Frame(main)
        btns.pack(fill="x", pady=(12, 0))
        self.analyze_btn = ttk.Button(btns, text="🔍 Analyze",
                                      command=self._on_analyze_click)
        self.analyze_btn.pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(btns, text="Close",
                   command=self._close).pack(side="left", expand=True, fill="x", padx=4)

        # Buttons row 2 — marker management
        btns2 = ttk.Frame(main)
        btns2.pack(fill="x", pady=(6, 0))
        self.clear_all_btn = ttk.Button(btns2, text="🗑 Clear ALL markers",
                                        command=self._on_clear_all)
        self.clear_all_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.clear_color_btn = ttk.Button(btns2, text="Clear by color…",
                                          command=self._on_clear_color)
        self.clear_color_btn.pack(side="left", expand=True, fill="x", padx=4)

        # Hooks for outer code to override
        self._on_clear_all_cb: Optional[Callable] = None
        self._on_clear_color_cb: Optional[Callable] = None

        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _on_analyze_click(self):
        self.options = {
            "whisper_model": self.whisper_var.get(),
            "use_cache": self.var_use_cache.get(),
            "add_highlights": self.var_highlights.get(),
            "mark_dead_air": self.var_deadair.get(),
            "find_shorts": self.var_shorts.get(),
            "create_shorts_timeline": self.var_shorts_tl.get(),
            "create_rough_cut": self.var_rough_cut.get(),
            "detect_fillers": self.var_fillers.get(),
            "generate_chapters": self.var_chapters.get(),
            "export_subs": self.var_subs.get(),
        }
        self.analyze_clicked = True
        self.cancelled = False
        self.analyze_btn.configure(state="disabled")
        if self._on_analyze:
            # Run analysis on a worker thread; UI stays responsive.
            threading.Thread(target=self._on_analyze, daemon=True).start()

    def _close(self):
        self._closing = True
        try:
            self.root.destroy()
        except Exception:
            pass

    # ----- public API (thread-safe; just enqueue) -----
    def set_status(self, text: str):
        self._ui_queue.put(("status", text))

    def set_progress(self, pct: int):
        self._ui_queue.put(("progress", pct))

    def set_eta(self, text: str):
        self._ui_queue.put(("eta", text))

    def update_all(self, pct: int, status: str = None, eta: str = None):
        # Single atomic enqueue so the three values land together
        self._ui_queue.put(("update_all", pct, status, eta))

    def reenable(self):
        self._ui_queue.put(("reenable",))

    def _drain_queue(self):
        """Run on Tk main thread — apply any queued UI updates."""
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "progress":
                    self.progress.configure(value=msg[1])
                elif kind == "eta":
                    self.eta_var.set(msg[1])
                elif kind == "update_all":
                    _, pct, status, eta = msg
                    if status is not None:
                        self.status_var.set(status)
                    if eta is not None:
                        self.eta_var.set(eta)
                    self.progress.configure(value=pct)
                elif kind == "reenable":
                    self.analyze_btn.configure(state="normal")
                elif kind == "run_main":
                    # Execute arbitrary callable on main thread
                    try:
                        msg[1]()
                    except Exception as e:
                        print(f"main-thread task failed: {e}")
        except queue.Empty:
            pass
        finally:
            if not self._closing:
                self.root.after(50, self._drain_queue)

    def run_on_main(self, fn: Callable):
        """Schedule a callable to run on the Tk main thread."""
        self._ui_queue.put(("run_main", fn))

    def on_analyze(self, callback: Callable):
        """Register the callback that runs when Analyze is clicked.
        Callback runs on a worker thread so the UI stays responsive."""
        self._on_analyze = callback

    def on_clear_all(self, callback: Callable):
        self._on_clear_all_cb = callback

    def on_clear_color(self, callback: Callable):
        self._on_clear_color_cb = callback

    def _on_clear_all(self):
        if self._on_clear_all_cb:
            self._on_clear_all_cb()

    def _on_clear_color(self):
        if self._on_clear_color_cb:
            self._on_clear_color_cb()

    def run(self):
        """Block until window closed."""
        self.root.mainloop()


def show_marker_preview(markers) -> list:
    """Show modal marker review window. Returns list of selected indices.

    Returns [] if user cancelled.
    """
    color_emoji = {"HIGHLIGHT": "🟢", "DEAD_AIR": "🔴",
                   "SHORT_CLIP": "🔵", "REVIEW": "🟡"}

    win = tk.Toplevel()
    win.title("Review Markers")
    win.geometry("560x520")
    try:
        win.attributes("-topmost", True)
        win.lift()
        win.grab_set()
    except Exception:
        pass

    ttk.Label(win, text=f"Found {len(markers)} markers. Pick the ones to apply:",
              font=("", 11, "bold")).pack(pady=8)

    list_frame = ttk.Frame(win)
    list_frame.pack(fill="both", expand=True, padx=10)

    sb = ttk.Scrollbar(list_frame)
    sb.pack(side="right", fill="y")

    lb = tk.Listbox(list_frame, selectmode="multiple",
                    yscrollcommand=sb.set, font=("Menlo", 11),
                    activestyle="none", height=20)
    lb.pack(side="left", fill="both", expand=True)
    sb.config(command=lb.yview)

    for m in markers:
        emoji = color_emoji.get(m.marker_type.name, "⚪")
        time_str = f"{int(m.start_seconds // 60)}:{int(m.start_seconds % 60):02d}"
        lb.insert("end", f"{emoji}  [{time_str}]  {m.label}")

    # Select all by default
    for i in range(len(markers)):
        lb.selection_set(i)

    result = {"indices": [], "cancelled": True}

    def on_apply():
        result["indices"] = list(lb.curselection())
        result["cancelled"] = False
        win.destroy()

    def on_cancel():
        win.destroy()

    def select_all():
        lb.selection_set(0, "end")

    def select_none():
        lb.selection_clear(0, "end")

    btns = ttk.Frame(win)
    btns.pack(fill="x", pady=10, padx=10)
    ttk.Button(btns, text="Select All", command=select_all).pack(side="left", padx=2)
    ttk.Button(btns, text="Select None", command=select_none).pack(side="left", padx=2)
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right", padx=2)
    ttk.Button(btns, text="✅ Apply Selected", command=on_apply).pack(side="right", padx=2)

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    win.wait_window()

    if result["cancelled"]:
        return []
    return result["indices"]


def prompt_clear_color() -> Optional[str]:
    """Modal dropdown to pick a marker color to clear."""
    win = tk.Toplevel()
    win.title("Clear by color")
    win.geometry("280x140")
    try:
        win.attributes("-topmost", True)
        win.lift()
        win.grab_set()
    except Exception:
        pass

    ttk.Label(win, text="Pick marker color to clear:").pack(pady=8)
    var = tk.StringVar(value="Red")
    colors = ["Green", "Red", "Blue", "Yellow", "Cyan", "Purple",
              "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
              "Sand", "Cocoa", "Cream"]
    ttk.Combobox(win, textvariable=var, values=colors,
                 state="readonly").pack(pady=4)

    result = {"color": None}

    def on_ok():
        result["color"] = var.get()
        win.destroy()

    def on_cancel():
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(pady=8)
    ttk.Button(btns, text="Clear", command=on_ok).pack(side="left", padx=4)
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="left", padx=4)

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    win.wait_window()
    return result["color"]
