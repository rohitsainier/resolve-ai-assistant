"""Tests for env_loader.py — zero-dep .env parser."""

import os
import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Strip any vars we might set in tests so re-runs are clean."""
    for k in ("TEST_RAA_KEY1", "TEST_RAA_KEY2", "TEST_RAA_QUOTED", "TEST_RAA_EXPORT",
              "TEST_RAA_INLINE", "TEST_RAA_EMPTY_VAL"):
        monkeypatch.delenv(k, raising=False)


class TestParser:
    def test_simple_key_value(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text("TEST_RAA_KEY1=hello\n")
        parsed = _parse_env_file(env)
        assert parsed == {"TEST_RAA_KEY1": "hello"}

    def test_ignores_comments_and_blanks(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text(
            "# comment\n"
            "\n"
            "TEST_RAA_KEY1=val\n"
            "    # indented comment also ignored\n"
            "TEST_RAA_KEY2=other\n"
        )
        parsed = _parse_env_file(env)
        assert parsed == {"TEST_RAA_KEY1": "val", "TEST_RAA_KEY2": "other"}

    def test_strips_quotes(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text('TEST_RAA_QUOTED="with spaces"\n')
        parsed = _parse_env_file(env)
        assert parsed == {"TEST_RAA_QUOTED": "with spaces"}

    def test_export_prefix_accepted(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text("export TEST_RAA_EXPORT=42\n")
        parsed = _parse_env_file(env)
        assert parsed == {"TEST_RAA_EXPORT": "42"}

    def test_inline_comment_stripped_for_unquoted(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text("TEST_RAA_INLINE=value # trailing note\n")
        parsed = _parse_env_file(env)
        assert parsed["TEST_RAA_INLINE"] == "value"

    def test_inline_comment_preserved_in_quoted(self, clean_env, tmp_path):
        from env_loader import _parse_env_file
        env = tmp_path / ".env"
        env.write_text('TEST_RAA_QUOTED="value # not a comment"\n')
        parsed = _parse_env_file(env)
        assert parsed["TEST_RAA_QUOTED"] == "value # not a comment"

    def test_missing_file_returns_empty(self, tmp_path):
        from env_loader import _parse_env_file
        parsed = _parse_env_file(tmp_path / "does_not_exist.env")
        assert parsed == {}


class TestLoadEnv:
    def test_loads_from_home(self, clean_env, tmp_path, monkeypatch):
        """The ~/.resolve-ai-assistant/.env path is checked first."""
        from env_loader import load_env
        # Redirect HOME so we don't touch the user's real .env
        monkeypatch.setenv("HOME", str(tmp_path))
        home_env_dir = tmp_path / ".resolve-ai-assistant"
        home_env_dir.mkdir()
        (home_env_dir / ".env").write_text("TEST_RAA_KEY1=from_home\n")

        applied = load_env()
        assert applied.get("TEST_RAA_KEY1") == "from_home"
        assert os.environ.get("TEST_RAA_KEY1") == "from_home"

    def test_real_env_vars_win(self, clean_env, tmp_path, monkeypatch):
        """load_env must NEVER overwrite an already-set environment variable."""
        from env_loader import load_env
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("TEST_RAA_KEY1", "real_value")
        home_env_dir = tmp_path / ".resolve-ai-assistant"
        home_env_dir.mkdir()
        (home_env_dir / ".env").write_text("TEST_RAA_KEY1=file_value\n")

        load_env()
        assert os.environ["TEST_RAA_KEY1"] == "real_value"

    def test_first_file_wins_across_paths(self, clean_env, tmp_path, monkeypatch):
        """Home .env beats repo .env which beats cwd .env."""
        from env_loader import load_env
        monkeypatch.setenv("HOME", str(tmp_path))
        home_dir = tmp_path / ".resolve-ai-assistant"
        home_dir.mkdir()
        (home_dir / ".env").write_text("TEST_RAA_KEY1=from_home\n")

        cwd_dir = tmp_path / "cwd"
        cwd_dir.mkdir()
        (cwd_dir / ".env").write_text("TEST_RAA_KEY1=from_cwd\n")
        monkeypatch.chdir(cwd_dir)

        applied = load_env()
        assert applied["TEST_RAA_KEY1"] == "from_home"
