"""Tests for prompt_editor.py — response formatting helpers."""


class TestShortHelpers:
    def test_short_truncates(self):
        from prompt_editor import _short
        assert _short("abc") == "abc"
        assert _short("x" * 100).endswith("...")
        assert len(_short("x" * 100)) == 40

    def test_short_result_error(self):
        from prompt_editor import _short_result
        assert "error" in _short_result({"error": "boom"})

    def test_short_result_ok_true(self):
        from prompt_editor import _short_result
        s = _short_result({"ok": True, "count": 3, "items": [1, 2, 3]})
        assert s.startswith("ok")

    def test_short_result_ok_false(self):
        """ok=False with no 'error' key should route to the 'failed: ...' branch."""
        from prompt_editor import _short_result
        s = _short_result({"ok": False, "note": "rejected"})
        assert "failed" in s
        assert "rejected" in s

    def test_short_result_error_takes_priority_over_ok(self):
        """When both 'error' and 'ok' are present, error wins for clarity."""
        from prompt_editor import _short_result
        s = _short_result({"ok": False, "error": "api down"})
        assert "error" in s
        assert "api down" in s

    def test_short_result_search_matches(self):
        from prompt_editor import _short_result
        s = _short_result({"results": [1, 2, 3], "total_matches": 10})
        assert "3 matches" in s
        assert "10" in s

    def test_short_result_markers(self):
        from prompt_editor import _short_result
        s = _short_result({"markers": [{}, {}, {}, {}]})
        assert "4 markers" in s

    def test_short_result_new_timeline(self):
        from prompt_editor import _short_result
        s = _short_result({"new_timeline": "My Rough Cut", "ok": True})
        assert "My Rough Cut" in s

    def test_short_result_removed(self):
        from prompt_editor import _short_result
        s = _short_result({"removed": 5})
        assert "5" in s
