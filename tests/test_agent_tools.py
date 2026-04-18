"""Tests for agent_tools.py — tool dispatcher and individual tool behaviors."""

import pytest
from unittest.mock import MagicMock


# ---------- Shared mock context ----------

@pytest.fixture
def mock_ctx(sample_transcript, tmp_path, monkeypatch):
    """Build an AgentContext wired to mock Resolve objects."""
    import memory
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path / "memory"))

    from agent_tools import AgentContext

    # In-memory marker store
    markers_store = {}

    timeline = MagicMock()
    timeline.GetName.return_value = "Test Timeline"
    timeline.GetSetting.return_value = "24"
    timeline.GetStartFrame.return_value = 0
    timeline.GetEndFrame.return_value = 2760  # 115s @ 24fps

    def _add_marker(frame, color, name, note, duration, custom):
        markers_store[frame] = {
            "color": color, "name": name, "note": note, "duration": duration,
        }
        return True

    def _get_markers():
        return dict(markers_store)

    def _delete(frame):
        return markers_store.pop(frame, None) is not None

    timeline.AddMarker.side_effect = _add_marker
    timeline.GetMarkers.side_effect = _get_markers
    timeline.DeleteMarkerAtFrame.side_effect = _delete
    timeline.GetItemListInTrack.return_value = []
    timeline.GetTrackCount.return_value = 1

    project = MagicMock()
    project.GetCurrentTimeline.return_value = timeline

    resolve = MagicMock()
    resolve.GetProjectManager.return_value.GetCurrentProject.return_value = project

    ctx = AgentContext(
        resolve=resolve,
        timeline=timeline,
        project=project,
        transcript=sample_transcript,
    )
    return ctx


# ---------- Tool schema sanity ----------

class TestToolSchemas:
    def test_all_tools_have_valid_schema(self):
        from agent_tools import TOOL_SCHEMAS
        for tool in TOOL_SCHEMAS:
            assert "name" in tool, f"tool missing name: {tool}"
            assert "description" in tool
            assert "input_schema" in tool
            # schema must declare object type
            assert tool["input_schema"].get("type") == "object"

    def test_every_schema_has_impl(self):
        from agent_tools import TOOL_SCHEMAS, _TOOL_IMPLS
        schema_names = {t["name"] for t in TOOL_SCHEMAS}
        impl_names = set(_TOOL_IMPLS.keys())
        # Every schema needs an impl (or is 'finish' which is agent-level)
        missing = schema_names - impl_names - {"finish"}
        assert not missing, f"Schemas without implementations: {missing}"

    def test_no_orphan_impls(self):
        """Every impl should have a matching schema so the LLM knows about it."""
        from agent_tools import TOOL_SCHEMAS, _TOOL_IMPLS
        schema_names = {t["name"] for t in TOOL_SCHEMAS}
        orphans = set(_TOOL_IMPLS.keys()) - schema_names
        assert not orphans, f"Impls without schemas: {orphans}"


# ---------- Search ----------

class TestSearchTranscript:
    def test_keyword_match(self, mock_ctx):
        from agent_tools import tool_search_transcript
        result = tool_search_transcript(mock_ctx, {"query": "AI coding"})
        assert result["results"], "Expected at least one match"
        top = result["results"][0]
        # The sample transcript has "AI coding assistants" in seg 2
        assert "AI coding" in top["text"] or "ai" in top["text"].lower()

    def test_empty_query_returns_empty(self, mock_ctx):
        from agent_tools import tool_search_transcript
        assert tool_search_transcript(mock_ctx, {"query": ""})["results"] == []

    def test_max_results_respected(self, mock_ctx):
        from agent_tools import tool_search_transcript
        result = tool_search_transcript(mock_ctx, {"query": "the", "max_results": 2})
        assert len(result["results"]) <= 2


# ---------- Timeline info ----------

class TestTimelineInfo:
    def test_returns_name_fps_duration(self, mock_ctx):
        from agent_tools import tool_get_timeline_info
        info = tool_get_timeline_info(mock_ctx, {})
        assert info["name"] == "Test Timeline"
        assert info["fps"] == 24.0
        assert info["duration_seconds"] > 0


# ---------- Markers ----------

class TestAddMarker:
    def test_add_marker_green(self, mock_ctx):
        from agent_tools import tool_add_marker
        result = tool_add_marker(mock_ctx, {
            "start_seconds": 10.0,
            "end_seconds": 12.0,
            "color": "Green",
            "label": "Key moment",
        })
        assert result["ok"] is True
        markers = mock_ctx.timeline.GetMarkers()
        # Frame 240 = 10.0s * 24fps
        assert 240 in markers
        assert markers[240]["color"] == "Green"
        assert markers[240]["name"] == "Key moment"

    def test_invalid_color_rejected(self, mock_ctx):
        from agent_tools import tool_add_marker
        result = tool_add_marker(mock_ctx, {
            "start_seconds": 5.0, "end_seconds": 6.0,
            "color": "Magenta",  # not in VALID_COLORS
            "label": "test",
        })
        assert result["ok"] is False
        assert "Invalid color" in result["error"]

    def test_add_marker_records_undo(self, mock_ctx):
        from agent_tools import tool_add_marker
        tool_add_marker(mock_ctx, {
            "start_seconds": 1.0, "end_seconds": 2.0,
            "color": "Red", "label": "x",
        })
        assert len(mock_ctx.undo_log) == 1
        assert mock_ctx.undo_log[0].op_type == "add"


class TestListMarkers:
    def test_empty_timeline(self, mock_ctx):
        from agent_tools import tool_list_markers
        result = tool_list_markers(mock_ctx, {})
        assert result["markers"] == []
        assert result["count"] == 0

    def test_color_filter(self, mock_ctx):
        from agent_tools import tool_add_marker, tool_list_markers
        tool_add_marker(mock_ctx, {"start_seconds": 1, "end_seconds": 2, "color": "Red", "label": "a"})
        tool_add_marker(mock_ctx, {"start_seconds": 10, "end_seconds": 11, "color": "Green", "label": "b"})
        greens = tool_list_markers(mock_ctx, {"color": "Green"})
        assert greens["count"] == 1
        assert greens["markers"][0]["color"] == "Green"


class TestClearMarkers:
    def test_clear_all(self, mock_ctx):
        from agent_tools import tool_add_marker, tool_clear_markers, tool_list_markers
        tool_add_marker(mock_ctx, {"start_seconds": 1, "end_seconds": 2, "color": "Red", "label": "a"})
        tool_add_marker(mock_ctx, {"start_seconds": 10, "end_seconds": 11, "color": "Green", "label": "b"})
        result = tool_clear_markers(mock_ctx, {})
        assert result["removed"] == 2
        assert tool_list_markers(mock_ctx, {})["count"] == 0

    def test_clear_by_color(self, mock_ctx):
        from agent_tools import tool_add_marker, tool_clear_markers, tool_list_markers
        tool_add_marker(mock_ctx, {"start_seconds": 1, "end_seconds": 2, "color": "Red", "label": "a"})
        tool_add_marker(mock_ctx, {"start_seconds": 10, "end_seconds": 11, "color": "Green", "label": "b"})
        result = tool_clear_markers(mock_ctx, {"color": "Red"})
        assert result["removed"] == 1
        remaining = tool_list_markers(mock_ctx, {})
        assert remaining["count"] == 1
        assert remaining["markers"][0]["color"] == "Green"


class TestUndoLast:
    def test_undo_nothing_errors(self, mock_ctx):
        from agent_tools import tool_undo_last
        result = tool_undo_last(mock_ctx, {})
        assert result["ok"] is False

    def test_undo_add_marker(self, mock_ctx):
        from agent_tools import tool_add_marker, tool_undo_last, tool_list_markers
        tool_add_marker(mock_ctx, {
            "start_seconds": 5, "end_seconds": 6, "color": "Red", "label": "x",
        })
        assert tool_list_markers(mock_ctx, {})["count"] == 1
        tool_undo_last(mock_ctx, {})
        assert tool_list_markers(mock_ctx, {})["count"] == 0

    def test_undo_clear_restores(self, mock_ctx):
        from agent_tools import tool_add_marker, tool_clear_markers, tool_undo_last, tool_list_markers
        tool_add_marker(mock_ctx, {"start_seconds": 1, "end_seconds": 2, "color": "Red", "label": "a"})
        tool_add_marker(mock_ctx, {"start_seconds": 10, "end_seconds": 11, "color": "Green", "label": "b"})
        tool_clear_markers(mock_ctx, {})
        assert tool_list_markers(mock_ctx, {})["count"] == 0
        tool_undo_last(mock_ctx, {})
        # Both markers should be back
        assert tool_list_markers(mock_ctx, {})["count"] == 2


class TestRememberForgetRecall:
    def test_remember_then_recall(self, mock_ctx):
        from agent_tools import tool_remember, tool_recall
        tool_remember(mock_ctx, {"key": "preference", "value": "user hates fades"})
        data = tool_recall(mock_ctx, {})
        assert data["pinned"]["preference"] == "user hates fades"

    def test_forget_existing(self, mock_ctx):
        from agent_tools import tool_remember, tool_forget, tool_recall
        tool_remember(mock_ctx, {"key": "transient", "value": "soon gone"})
        result = tool_forget(mock_ctx, {"key": "transient"})
        assert result["existed"] is True
        assert "transient" not in tool_recall(mock_ctx, {})["pinned"]


class TestSubmitPlan:
    def test_unknown_tool_in_plan_rejected(self, mock_ctx):
        from agent_tools import tool_submit_plan
        result = tool_submit_plan(mock_ctx, {
            "description": "bad plan",
            "actions": [{"tool": "does_not_exist", "args": {}}],
        })
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]

    def test_empty_plan_rejected(self, mock_ctx):
        from agent_tools import tool_submit_plan
        result = tool_submit_plan(mock_ctx, {
            "description": "empty",
            "actions": [],
        })
        assert result["ok"] is False

    def test_approved_plan_executes(self, mock_ctx):
        """When plan_approval_cb returns True, actions run in order."""
        from agent_tools import tool_submit_plan, tool_list_markers
        mock_ctx.plan_approval_cb = lambda desc, actions: True
        result = tool_submit_plan(mock_ctx, {
            "description": "mark two moments",
            "actions": [
                {"tool": "add_marker", "args": {
                    "start_seconds": 3, "end_seconds": 4,
                    "color": "Green", "label": "one",
                }},
                {"tool": "add_marker", "args": {
                    "start_seconds": 20, "end_seconds": 21,
                    "color": "Blue", "label": "two",
                }},
            ],
        })
        assert result["ok"] is True
        assert result["approved"] is True
        assert result["executed_count"] == 2
        assert tool_list_markers(mock_ctx, {})["count"] == 2

    def test_rejected_plan_does_not_execute(self, mock_ctx):
        from agent_tools import tool_submit_plan, tool_list_markers
        mock_ctx.plan_approval_cb = lambda desc, actions: False
        result = tool_submit_plan(mock_ctx, {
            "description": "rejected",
            "actions": [{"tool": "add_marker", "args": {
                "start_seconds": 5, "end_seconds": 6,
                "color": "Red", "label": "nope",
            }}],
        })
        assert result["approved"] is False
        # No marker was added
        assert tool_list_markers(mock_ctx, {})["count"] == 0

    def test_no_approval_cb_defaults_to_approve(self, mock_ctx):
        """When running without a UI attached (CLI mode), plans just execute."""
        from agent_tools import tool_submit_plan, tool_list_markers
        mock_ctx.plan_approval_cb = None
        result = tool_submit_plan(mock_ctx, {
            "description": "headless",
            "actions": [{"tool": "add_marker", "args": {
                "start_seconds": 7, "end_seconds": 8,
                "color": "Red", "label": "cli",
            }}],
        })
        assert result["approved"] is True
        assert tool_list_markers(mock_ctx, {})["count"] == 1


# ---------- Dispatcher ----------

class TestExecuteTool:
    def test_unknown_tool(self, mock_ctx):
        from agent_tools import execute_tool
        result = execute_tool(mock_ctx, "totally_fake_tool", {})
        assert "error" in result

    def test_finish_returns_summary(self, mock_ctx):
        from agent_tools import execute_tool
        result = execute_tool(mock_ctx, "finish", {"summary": "all done"})
        assert result["summary"] == "all done"
