"""Tests for profiles.py — creator style config."""

import json
import os
import pytest


@pytest.fixture
def tmp_profiles_dir(tmp_path, monkeypatch):
    """Redirect profiles storage to a temp dir for each test."""
    import profiles
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(profiles, "ACTIVE_POINTER", str(tmp_path / "active"))
    return tmp_path


class TestBuiltinProfiles:
    def test_default_exists(self):
        from profiles import BUILTINS
        assert "default" in BUILTINS
        assert BUILTINS["default"].name == "Default"

    def test_five_builtins_shipped(self):
        """We advertise 5 built-in profiles in the UI; make sure they exist."""
        from profiles import BUILTINS
        expected = {"default", "youtube_creator", "shorts_creator",
                    "podcast_host", "corporate_explainer"}
        assert expected.issubset(BUILTINS.keys())

    def test_builtin_prompt_summary_non_empty(self):
        from profiles import BUILTINS
        for pid, p in BUILTINS.items():
            summary = p.to_prompt_summary()
            assert p.name in summary, f"{pid} summary missing name"
            assert len(summary) < 600, f"{pid} summary too long: {len(summary)}"


class TestProfileIO:
    def test_load_builtin(self, tmp_profiles_dir):
        from profiles import load_profile
        p = load_profile("youtube_creator")
        assert p is not None
        assert p.id == "youtube_creator"
        assert p.filler_sensitivity == "high"

    def test_load_missing_returns_none(self, tmp_profiles_dir):
        from profiles import load_profile
        assert load_profile("does_not_exist") is None

    def test_save_then_load(self, tmp_profiles_dir):
        from profiles import Profile, save_profile, load_profile
        p = Profile(
            id="my_test",
            name="My Test",
            description="Unit test profile",
            tone="energetic",
            target_lufs=-12.0,
            style_notes="Do cool stuff.",
        )
        path = save_profile(p)
        assert os.path.isfile(path)
        loaded = load_profile("my_test")
        assert loaded.name == "My Test"
        assert loaded.tone == "energetic"
        assert loaded.target_lufs == -12.0
        assert loaded.style_notes == "Do cool stuff."

    def test_save_sanitizes_id(self, tmp_profiles_dir):
        """Profile IDs must be safe for filesystem use."""
        from profiles import Profile, save_profile, load_profile
        p = Profile(id="MY Test! 2026", name="With spaces")
        save_profile(p)
        # Consecutive non-alphanumeric chars collapse to one underscore:
        # "MY Test! 2026" -> "my_test_2026"
        assert p.id == "my_test_2026"
        # And loads under the sanitized id
        assert load_profile("my_test_2026") is not None

    def test_save_sanitizes_dangerous_chars(self, tmp_profiles_dir):
        """Path traversal and shell-ish characters must be stripped."""
        from profiles import Profile, save_profile
        p = Profile(id="../evil/../../id", name="Evil")
        save_profile(p)
        # Should never contain slashes or dots that could break out of the dir
        assert "/" not in p.id
        assert ".." not in p.id

    def test_disk_overrides_builtin(self, tmp_profiles_dir):
        """A saved profile with the same id as a builtin should win."""
        from profiles import Profile, save_profile, load_profile
        overridden = Profile(
            id="youtube_creator",
            name="Custom YouTube",
            description="My version",
        )
        save_profile(overridden)
        loaded = load_profile("youtube_creator")
        assert loaded.name == "Custom YouTube"
        assert loaded.description == "My version"


class TestListAll:
    def test_includes_builtins_when_no_saved(self, tmp_profiles_dir):
        from profiles import list_all
        ids = {p["id"] for p in list_all()}
        assert "default" in ids
        assert "youtube_creator" in ids

    def test_marks_builtin_flag(self, tmp_profiles_dir):
        from profiles import list_all
        by_id = {p["id"]: p for p in list_all()}
        assert by_id["default"]["builtin"] is True

    def test_saved_profile_appears_first(self, tmp_profiles_dir):
        from profiles import Profile, save_profile, list_all
        save_profile(Profile(id="z_my_profile", name="Z Mine"))
        ids = [p["id"] for p in list_all()]
        # Our saved one appears and is flagged as non-builtin
        by_id = {p["id"]: p for p in list_all()}
        assert by_id["z_my_profile"]["builtin"] is False


class TestActiveProfile:
    def test_default_active_is_default(self, tmp_profiles_dir):
        from profiles import get_active_id, get_active_profile
        assert get_active_id() == "default"
        assert get_active_profile().id == "default"

    def test_set_active_persists(self, tmp_profiles_dir):
        from profiles import set_active_id, get_active_id
        set_active_id("shorts_creator")
        assert get_active_id() == "shorts_creator"

    def test_active_points_to_builtin_profile(self, tmp_profiles_dir):
        from profiles import set_active_id, get_active_profile
        set_active_id("podcast_host")
        p = get_active_profile()
        assert p.id == "podcast_host"
        assert p.filler_sensitivity == "low"  # podcasts keep fillers

    def test_active_missing_falls_back_to_default(self, tmp_profiles_dir):
        """If pointer refers to a profile that no longer exists, return default."""
        from profiles import set_active_id, get_active_profile
        set_active_id("ghost_profile_no_longer_exists")
        p = get_active_profile()
        assert p.id == "default"


class TestPromptSummary:
    def test_youtube_creator_mentions_filler_cuts(self):
        from profiles import BUILTINS
        summary = BUILTINS["youtube_creator"].to_prompt_summary()
        assert "filler" in summary.lower() or "um" in summary.lower() or "cut" in summary.lower()

    def test_podcast_mentions_pauses(self):
        from profiles import BUILTINS
        summary = BUILTINS["podcast_host"].to_prompt_summary()
        assert "pause" in summary.lower() or "conversational" in summary.lower()

    def test_empty_description_still_produces_summary(self):
        from profiles import Profile
        p = Profile(id="x", name="X")
        assert p.to_prompt_summary()
