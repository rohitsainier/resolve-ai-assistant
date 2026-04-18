#!/usr/bin/env python3
"""Tiny HTTP server for the HTML-based UI.

Serves web/index.html and exposes JSON API endpoints that Resolve-side
code processes. Uses only the Python stdlib.
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class SharedState:
    """Thread-safe shared state between the server and the Resolve side."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = "Ready"
        self._pct = 0
        self._preview_markers = None  # when set, frontend shows modal
        self._preview_result: Optional[list] = None  # filled by frontend
        self._preview_event = threading.Event()
        self._plan_pending = None  # {description, actions} when awaiting approval
        self._plan_result = None   # True / False after user decides
        self._plan_event = threading.Event()
        self.info = {}  # timeline/provider info
        self._handlers = {}  # {endpoint: callable(body_dict) -> dict}

    # --- progress ---
    def set_status(self, text: str = None, pct: int = None):
        with self._lock:
            if text is not None:
                self._status = text
            if pct is not None:
                self._pct = max(0, min(100, int(pct)))

    def get_status(self):
        with self._lock:
            out = {"text": self._status, "pct": self._pct}
            if self._preview_markers is not None:
                out["preview"] = self._preview_markers
                # Deliver only once — clear after sending
                self._preview_markers = None
            if self._plan_pending is not None:
                out["plan"] = self._plan_pending
                # Deliver only once — frontend will POST its decision
                self._plan_pending = None
            return out

    # --- marker preview: worker blocks on the event until frontend replies ---
    def request_preview(self, markers: list, timeout: float = 600) -> list:
        """Called from worker thread. Returns list of selected indices."""
        payload = [
            {
                "start": m.start_seconds,
                "end": m.end_seconds,
                "type": m.marker_type.name,
                "label": m.label,
                "note": m.note,
            }
            for m in markers
        ]
        with self._lock:
            self._preview_markers = payload
            self._preview_result = None
            self._preview_event.clear()
        self._preview_event.wait(timeout=timeout)
        with self._lock:
            return self._preview_result or []

    def submit_preview(self, indices: list):
        with self._lock:
            self._preview_result = indices
        self._preview_event.set()

    # --- plan approval: parallel to marker preview but for agent plans ---
    def __post_init_plan__(self):
        # Helpers populated lazily; we just declare attributes via get/setattr
        pass

    def request_plan_approval(self, description: str, actions: list,
                              timeout: float = 600) -> bool:
        """Ask the UI to approve a plan. Blocks until the user clicks approve/reject."""
        with self._lock:
            self._plan_pending = {
                "description": description,
                "actions": actions,
            }
            self._plan_result = None
            self._plan_event = threading.Event()
        self._plan_event.wait(timeout=timeout)
        with self._lock:
            approved = bool(self._plan_result)
            self._plan_pending = None
            self._plan_result = None
            return approved

    def submit_plan_decision(self, approved: bool):
        with self._lock:
            self._plan_result = approved
            ev = getattr(self, "_plan_event", None)
        if ev:
            ev.set()

    def get_pending_plan(self):
        with self._lock:
            return getattr(self, "_plan_pending", None)

    # --- endpoint handlers ---
    def register(self, name: str, handler: Callable):
        self._handlers[name] = handler

    def call(self, name: str, body: dict) -> dict:
        h = self._handlers.get(name)
        if not h:
            return {"error": f"Unknown endpoint: {name}"}
        try:
            return h(body) or {}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"{type(e).__name__}: {e}"}


def _build_handler(state: SharedState):
    class Handler(BaseHTTPRequestHandler):
        # Silence default stdout access logging
        def log_message(self, fmt, *args):
            pass

        def _send_json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: str, content_type: str):
            try:
                with open(path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "/index.html":
                self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
                return

            if path.startswith("/api/"):
                name = path[len("/api/"):]
                if name == "status":
                    self._send_json(state.get_status())
                    return
                if name == "info":
                    self._send_json(state.info)
                    return
                self._send_json({"error": "use POST"}, code=405)
                return

            # Static file fallback (if we add CSS/JS later)
            safe_path = os.path.normpath(path.lstrip("/"))
            full = os.path.join(WEB_DIR, safe_path)
            if os.path.isfile(full) and full.startswith(WEB_DIR):
                if full.endswith(".html"):
                    ct = "text/html; charset=utf-8"
                elif full.endswith(".css"):
                    ct = "text/css"
                elif full.endswith(".js"):
                    ct = "application/javascript"
                else:
                    ct = "application/octet-stream"
                self._send_file(full, ct)
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            body_bytes = self.rfile.read(length) if length else b""
            try:
                body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                body = {}

            name = parsed.path[len("/api/"):]

            if name == "apply_preview":
                indices = body.get("indices") or []
                state.submit_preview(list(indices))
                self._send_json({"ok": True})
                return

            if name == "approve_plan":
                approved = bool(body.get("approved"))
                state.submit_plan_decision(approved)
                self._send_json({"ok": True, "approved": approved})
                return

            # Dispatch to a registered handler — run on a worker thread so
            # long-running tasks (analyze, prompt) don't block the HTTP server.
            def run():
                return state.call(name, body)

            if name in ("analyze", "prompt"):
                # Fire-and-forget: frontend polls /api/status for progress
                threading.Thread(target=run, daemon=True).start()
                self._send_json({"started": True})
                return

            # Synchronous endpoints (clear_markers, etc.)
            self._send_json(state.call(name, body))

    return Handler


def find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port available")


def start_server(state: SharedState, port: Optional[int] = None) -> tuple:
    """Start the HTTP server on a background thread. Returns (server, port)."""
    if port is None:
        port = find_free_port()
    handler = _build_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port
