"""Tests for delivery.py — render preset management."""

import os
import pytest
from unittest.mock import MagicMock


class TestPlatformPresets:
    def test_five_presets_exist(self):
        from delivery import PLATFORM_PRESETS
        expected = {"youtube_1080p", "youtube_4k",
                    "tiktok_vertical", "instagram_square", "proxy_540p"}
        assert expected.issubset(PLATFORM_PRESETS.keys())

    def test_vertical_preset_is_vertical(self):
        from delivery import PLATFORM_PRESETS
        p = PLATFORM_PRESETS["tiktok_vertical"]
        assert p["FormatWidth"] == 1080
        assert p["FormatHeight"] == 1920

    def test_square_preset_is_square(self):
        from delivery import PLATFORM_PRESETS
        p = PLATFORM_PRESETS["instagram_square"]
        assert p["FormatWidth"] == p["FormatHeight"] == 1080

    def test_all_presets_have_required_keys(self):
        from delivery import PLATFORM_PRESETS
        for name, p in PLATFORM_PRESETS.items():
            for k in ("FormatWidth", "FormatHeight", "VideoCodec", "AudioCodec"):
                assert k in p, f"{name} missing {k}"


class TestListOurPresets:
    def test_returns_list_of_dicts(self):
        from delivery import list_our_presets
        out = list_our_presets()
        assert isinstance(out, list)
        assert len(out) >= 5
        for entry in out:
            assert "id" in entry
            assert "label" in entry


class TestQueueRender:
    def test_unknown_preset_errors(self):
        from delivery import queue_render
        project = MagicMock()
        result = queue_render(project, preset_id="doesnt_exist")
        assert "error" in result

    def test_sets_target_dir(self, tmp_path):
        from delivery import queue_render
        project = MagicMock()
        project.SetRenderSettings.return_value = True
        project.AddRenderJob.return_value = "job_123"
        result = queue_render(
            project,
            preset_id="youtube_1080p",
            output_dir=str(tmp_path),
            filename="test",
        )
        assert result["ok"] is True
        assert result["job_id"] == "job_123"
        # Confirm we passed the right settings to Resolve
        call_settings = project.SetRenderSettings.call_args[0][0]
        assert call_settings["TargetDir"] == str(tmp_path)
        assert call_settings["FormatWidth"] == 1920
        assert call_settings["CustomName"] == "test"

    def test_filename_strips_extension(self, tmp_path):
        from delivery import queue_render
        project = MagicMock()
        project.SetRenderSettings.return_value = True
        project.AddRenderJob.return_value = "j1"
        result = queue_render(
            project,
            preset_id="youtube_1080p",
            output_dir=str(tmp_path),
            filename="my_video.mp4",
        )
        # Resolve adds the extension itself; we should pass base name only
        call_settings = project.SetRenderSettings.call_args[0][0]
        assert call_settings["CustomName"] == "my_video"

    def test_default_filename_uses_timeline_name(self, tmp_path):
        from delivery import queue_render
        project = MagicMock()
        project.SetRenderSettings.return_value = True
        project.AddRenderJob.return_value = "j1"
        tl = MagicMock()
        tl.GetName.return_value = "My Cool Timeline"
        project.GetCurrentTimeline.return_value = tl

        result = queue_render(
            project,
            preset_id="tiktok_vertical",
            output_dir=str(tmp_path),
        )
        call_settings = project.SetRenderSettings.call_args[0][0]
        assert "My Cool Timeline" in call_settings["CustomName"]
        assert "tiktok_vertical" in call_settings["CustomName"]

    def test_add_render_job_failure(self, tmp_path):
        from delivery import queue_render
        project = MagicMock()
        project.SetRenderSettings.return_value = True
        project.AddRenderJob.return_value = None  # empty id
        result = queue_render(project, preset_id="youtube_1080p", output_dir=str(tmp_path))
        assert "error" in result

    def test_set_render_settings_failure(self, tmp_path):
        from delivery import queue_render
        project = MagicMock()
        project.SetRenderSettings.return_value = False
        result = queue_render(project, preset_id="youtube_1080p", output_dir=str(tmp_path))
        assert "error" in result


class TestStartRenders:
    def test_all_jobs(self):
        from delivery import start_renders
        project = MagicMock()
        project.StartRendering.return_value = True
        result = start_renders(project)
        assert result["ok"] is True
        assert result["started"] == "all"

    def test_specific_jobs_passed_through(self):
        from delivery import start_renders
        project = MagicMock()
        project.StartRendering.return_value = True
        start_renders(project, ["a", "b"])
        project.StartRendering.assert_called_once_with("a", "b")

    def test_failure(self):
        from delivery import start_renders
        project = MagicMock()
        project.StartRendering.return_value = False
        result = start_renders(project)
        assert result["ok"] is False


class TestRenderStatus:
    def test_no_jobs(self):
        from delivery import render_status
        project = MagicMock()
        project.IsRenderingInProgress.return_value = False
        project.GetRenderJobList.return_value = []
        result = render_status(project)
        assert result["rendering"] is False
        assert result["jobs"] == []

    def test_with_jobs(self):
        from delivery import render_status
        project = MagicMock()
        project.IsRenderingInProgress.return_value = True
        project.GetRenderJobList.return_value = [{"JobId": "abc"}]
        project.GetRenderJobStatus.return_value = {"JobStatus": "Rendering", "CompletionPercentage": 42}
        result = render_status(project)
        assert result["rendering"] is True
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["JobId"] == "abc"
        assert result["jobs"][0]["CompletionPercentage"] == 42
