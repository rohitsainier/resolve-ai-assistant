"""Tests for memory.py — per-timeline session journal + pinned facts."""

import os
import pytest


@pytest.fixture
def tmp_memory_dir(tmp_path, monkeypatch):
    import memory
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path / "memory"))
    return tmp_path


class TestSessionRecording:
    def test_record_appends_entry(self, tmp_memory_dir):
        from memory import record_session, recall
        record_session("My TL", "do a thing", "did the thing", ["list_markers"])
        data = recall("My TL")
        assert len(data["matching_sessions"]) == 1
        assert data["matching_sessions"][0]["user_request"] == "do a thing"
        assert "list_markers" in data["matching_sessions"][0]["tools_used"]

    def test_empty_timeline_name_no_crash(self, tmp_memory_dir):
        from memory import record_session
        # Should just silently skip
        record_session("", "req", "summary", [])
        record_session(None, "req", "summary", [])

    def test_sessions_trim_to_max(self, tmp_memory_dir, monkeypatch):
        """Journal never grows past MAX_TOTAL_SESSIONS entries."""
        import memory
        monkeypatch.setattr(memory, "MAX_TOTAL_SESSIONS", 3)
        for i in range(5):
            memory.record_session("TL", f"request {i}", f"summary {i}", [])
        data = memory.recall("TL")
        assert len(data["matching_sessions"]) == 3
        # The last 3 should be kept
        assert data["matching_sessions"][0]["user_request"] == "request 2"
        assert data["matching_sessions"][-1]["user_request"] == "request 4"


class TestPinnedFacts:
    def test_remember_and_recall(self, tmp_memory_dir):
        from memory import remember_fact, recall
        remember_fact("TL", "tone", "always punchy")
        data = recall("TL")
        assert data["pinned"]["tone"] == "always punchy"

    def test_remember_overwrites(self, tmp_memory_dir):
        from memory import remember_fact, recall
        remember_fact("TL", "key", "v1")
        remember_fact("TL", "key", "v2")
        assert recall("TL")["pinned"]["key"] == "v2"

    def test_forget_existing(self, tmp_memory_dir):
        from memory import remember_fact, forget_fact, recall
        remember_fact("TL", "transient", "value")
        assert forget_fact("TL", "transient") is True
        assert "transient" not in recall("TL")["pinned"]

    def test_forget_missing_returns_false(self, tmp_memory_dir):
        from memory import forget_fact
        assert forget_fact("TL", "never_existed") is False

    def test_values_get_truncated(self, tmp_memory_dir):
        """Values over 400 chars get clipped to protect prompt size."""
        from memory import remember_fact, recall
        long_value = "x" * 500
        remember_fact("TL", "big", long_value)
        stored = recall("TL")["pinned"]["big"]
        assert len(stored) <= 400


class TestIsolation:
    """Memory is per-timeline, not global."""

    def test_different_timelines_different_memory(self, tmp_memory_dir):
        from memory import remember_fact, recall
        remember_fact("Timeline A", "fact", "a-value")
        remember_fact("Timeline B", "fact", "b-value")
        assert recall("Timeline A")["pinned"]["fact"] == "a-value"
        assert recall("Timeline B")["pinned"]["fact"] == "b-value"

    def test_session_recorded_only_on_named_timeline(self, tmp_memory_dir):
        from memory import record_session, recall
        record_session("TL-1", "req", "summary", [])
        assert len(recall("TL-1")["matching_sessions"]) == 1
        assert len(recall("TL-2")["matching_sessions"]) == 0


class TestRecallSearch:
    def test_recall_without_query_returns_recent(self, tmp_memory_dir):
        from memory import record_session, recall
        for i in range(4):
            record_session("TL", f"req {i}", f"summary {i}", [])
        results = recall("TL")["matching_sessions"]
        assert len(results) == 4

    def test_recall_query_filters_sessions(self, tmp_memory_dir):
        from memory import record_session, recall
        record_session("TL", "make a rough cut", "created rough cut timeline", [])
        record_session("TL", "mark highlights", "added 3 green markers", [])
        record_session("TL", "rough cut again", "made another rough cut", [])
        matches = recall("TL", query="rough cut")["matching_sessions"]
        assert len(matches) == 2
        for m in matches:
            assert "rough" in m["user_request"].lower() or "rough" in m["agent_summary"].lower()

    def test_recall_max_results_limit(self, tmp_memory_dir):
        from memory import record_session, recall
        for i in range(10):
            record_session("TL", f"req {i}", "summary", [])
        assert len(recall("TL", max_results=3)["matching_sessions"]) == 3


class TestPromptBlock:
    def test_empty_when_no_memory(self, tmp_memory_dir):
        from memory import build_memory_prompt_block
        # Never wrote anything for this timeline
        assert build_memory_prompt_block("empty-tl") == ""

    def test_includes_pinned_facts(self, tmp_memory_dir):
        from memory import remember_fact, build_memory_prompt_block
        remember_fact("TL", "preference", "user likes hard cuts")
        block = build_memory_prompt_block("TL")
        assert "preference" in block
        assert "hard cuts" in block

    def test_includes_recent_sessions(self, tmp_memory_dir):
        from memory import record_session, build_memory_prompt_block
        record_session("TL", "mark highlights", "added 3 markers", ["search_transcript", "add_marker"])
        block = build_memory_prompt_block("TL")
        assert "mark highlights" in block
        assert "added 3 markers" in block

    def test_session_limit_in_prompt(self, tmp_memory_dir, monkeypatch):
        """Only the last N sessions should appear in the prompt block."""
        import memory
        monkeypatch.setattr(memory, "MAX_SESSIONS_IN_PROMPT", 2)
        for i in range(5):
            memory.record_session("TL", f"request {i}", "summary", [])
        block = memory.build_memory_prompt_block("TL")
        # Only 2 most recent requests should appear
        assert "request 3" in block
        assert "request 4" in block
        assert "request 0" not in block
