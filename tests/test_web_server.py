"""Tests for web_server.py — SharedState + preview/plan handshakes + HTTP API."""

import json
import socket
import threading
import time
import urllib.request

import pytest


@pytest.fixture
def state():
    from web_server import SharedState
    return SharedState()


class TestStatus:
    def test_initial_ready(self, state):
        s = state.get_status()
        assert s["text"] == "Ready"
        assert s["pct"] == 0

    def test_set_status(self, state):
        state.set_status("working", 42)
        s = state.get_status()
        assert s["text"] == "working"
        assert s["pct"] == 42

    def test_pct_clamped(self, state):
        state.set_status(None, 999)
        assert state.get_status()["pct"] == 100
        state.set_status(None, -5)
        assert state.get_status()["pct"] == 0


class TestPreviewHandshake:
    def test_submit_unblocks_request(self, state):
        from analyze import EditMarker, MarkerType

        markers = [EditMarker(
            start_seconds=1.0, end_seconds=2.0,
            marker_type=MarkerType.HIGHLIGHT, label="x",
        )]

        result = {"indices": None}
        done = threading.Event()

        def worker():
            result["indices"] = state.request_preview(markers, timeout=5)
            done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        # Give worker a tick to register the request
        time.sleep(0.05)
        # Poll status — should include "preview" exactly once
        s = state.get_status()
        assert "preview" in s
        assert s["preview"][0]["label"] == "x"

        # Submit a decision
        state.submit_preview([0])
        assert done.wait(timeout=3)
        assert result["indices"] == [0]

    def test_preview_only_delivered_once(self, state):
        from analyze import EditMarker, MarkerType
        markers = [EditMarker(
            start_seconds=0, end_seconds=1,
            marker_type=MarkerType.HIGHLIGHT, label="x",
        )]
        # Start a request, then check status twice
        threading.Thread(
            target=lambda: state.request_preview(markers, timeout=1),
            daemon=True,
        ).start()
        time.sleep(0.05)
        first = state.get_status()
        second = state.get_status()
        assert "preview" in first
        assert "preview" not in second  # should be cleared after first delivery
        state.submit_preview([])  # cleanup


class TestPlanHandshake:
    def test_approve_unblocks(self, state):
        result = {"approved": None}
        done = threading.Event()

        def worker():
            result["approved"] = state.request_plan_approval(
                "make markers", [{"tool": "add_marker", "args": {}}], timeout=5,
            )
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        time.sleep(0.05)

        s = state.get_status()
        assert "plan" in s
        assert s["plan"]["description"] == "make markers"
        assert len(s["plan"]["actions"]) == 1

        state.submit_plan_decision(True)
        assert done.wait(timeout=3)
        assert result["approved"] is True

    def test_reject_returns_false(self, state):
        done = threading.Event()
        outcome = {"approved": None}

        def worker():
            outcome["approved"] = state.request_plan_approval("x", [{"tool": "y", "args": {}}], timeout=5)
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        time.sleep(0.05)
        state.submit_plan_decision(False)
        assert done.wait(timeout=3)
        assert outcome["approved"] is False

    def test_plan_delivered_once(self, state):
        threading.Thread(
            target=lambda: state.request_plan_approval("x", [{"tool": "y", "args": {}}], timeout=1),
            daemon=True,
        ).start()
        time.sleep(0.05)
        first = state.get_status()
        second = state.get_status()
        assert "plan" in first
        assert "plan" not in second
        state.submit_plan_decision(False)  # cleanup


class TestHandlerRegistration:
    def test_call_unknown_endpoint(self, state):
        result = state.call("does_not_exist", {})
        assert "error" in result

    def test_call_registered_handler(self, state):
        state.register("echo", lambda body: {"echoed": body.get("msg")})
        result = state.call("echo", {"msg": "hello"})
        assert result == {"echoed": "hello"}

    def test_handler_crash_is_caught(self, state):
        def boom(body):
            raise ValueError("oops")
        state.register("boom", boom)
        result = state.call("boom", {})
        assert "error" in result
        assert "oops" in result["error"]


class TestHttpServer:
    """End-to-end: start the real server, hit it over HTTP."""

    def test_server_serves_status_json(self):
        from web_server import SharedState, start_server, find_free_port
        state = SharedState()
        state.set_status("hello", 50)

        server, port = start_server(state, port=find_free_port(8800))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
                body = json.loads(r.read().decode("utf-8"))
            assert body["text"] == "hello"
            assert body["pct"] == 50
        finally:
            server.shutdown()

    def test_server_returns_html_index(self):
        from web_server import SharedState, start_server, find_free_port
        state = SharedState()
        server, port = start_server(state, port=find_free_port(8830))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                html = r.read().decode("utf-8")
            assert "<html" in html.lower()
            assert "ai edit assistant" in html.lower()
        finally:
            server.shutdown()

    def test_post_apply_preview(self):
        from web_server import SharedState, start_server, find_free_port
        state = SharedState()
        server, port = start_server(state, port=find_free_port(8860))
        try:
            data = json.dumps({"indices": [0, 1]}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/apply_preview",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                body = json.loads(r.read().decode("utf-8"))
            assert body.get("ok") is True
        finally:
            server.shutdown()

    def test_find_free_port_returns_usable(self):
        from web_server import find_free_port
        port = find_free_port(9000)
        # Should actually be bindable
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
