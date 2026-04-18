"""Tests for analyze.py — filler detection, silence detection, llm_complete routing."""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestFillerDetection:
    def _transcript_with_words(self, segments):
        """Build a transcript with word-level timestamps for filler detection."""
        from transcribe import Transcript, TranscriptSegment, Word
        segs = []
        for start, end, text, words in segments:
            word_objs = [Word(w[0], w[1], w[2]) for w in words]
            segs.append(TranscriptSegment(start, end, text, words=word_objs))
        return Transcript(segments=segs, language="en", duration=segs[-1].end if segs else 0)

    def test_detects_single_filler(self):
        from analyze import analyze_for_fillers
        t = self._transcript_with_words([
            (0.0, 3.0, "So um yeah.", [
                (0.0, 0.3, "so"),
                (0.4, 0.8, "um"),
                (1.0, 1.5, "yeah"),
            ]),
        ])
        markers = analyze_for_fillers(t)
        assert len(markers) == 1
        assert "um" in markers[0].label.lower()

    def test_detects_multi_word_phrase(self):
        from analyze import analyze_for_fillers
        t = self._transcript_with_words([
            (0.0, 3.0, "you know what I mean", [
                (0.0, 0.3, "you"),
                (0.4, 0.6, "know"),
                (0.8, 1.0, "what"),
                (1.1, 1.3, "i"),
                (1.4, 1.7, "mean"),
            ]),
        ])
        markers = analyze_for_fillers(t)
        # "you know" AND "i mean" should both be detected
        labels = [m.label.lower() for m in markers]
        assert any("you know" in l for l in labels)
        assert any("i mean" in l for l in labels)

    def test_no_words_no_fillers(self):
        """If words aren't captured, filler detection simply returns empty."""
        from analyze import analyze_for_fillers
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(0, 5, "um uh like", words=None)],
            language="en", duration=5,
        )
        assert analyze_for_fillers(t) == []

    def test_custom_fillers_list(self):
        from analyze import analyze_for_fillers
        t = self._transcript_with_words([
            (0.0, 3.0, "the thing is weird", [
                (0.0, 0.3, "the"),
                (0.4, 0.8, "thing"),
                (0.9, 1.1, "is"),
                (1.2, 1.8, "weird"),
            ]),
        ])
        markers = analyze_for_fillers(t, fillers={"thing"})
        assert len(markers) == 1
        assert "thing" in markers[0].label.lower()


class TestSilenceDetection:
    def test_gap_exceeding_threshold(self, sample_transcript_with_silence):
        from analyze import analyze_for_silence
        markers = analyze_for_silence(sample_transcript_with_silence, threshold_seconds=3.0)
        assert len(markers) >= 1
        # First gap is 10 seconds (5.0 to 15.0)
        assert any(abs(m.end_seconds - m.start_seconds - 10.0) < 0.01 for m in markers)

    def test_gaps_below_threshold_ignored(self):
        from analyze import analyze_for_silence
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[
                TranscriptSegment(0, 5, "one"),
                TranscriptSegment(6, 10, "two"),  # 1s gap — ignored
                TranscriptSegment(10.5, 15, "three"),  # 0.5s gap — ignored
            ],
            language="en", duration=15,
        )
        markers = analyze_for_silence(t, threshold_seconds=3.0)
        assert markers == []

    def test_marker_type_is_dead_air(self):
        from analyze import analyze_for_silence, MarkerType
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[
                TranscriptSegment(0, 5, "one"),
                TranscriptSegment(15, 20, "two"),
            ],
            language="en", duration=20,
        )
        markers = analyze_for_silence(t, threshold_seconds=3.0)
        assert markers[0].marker_type == MarkerType.DEAD_AIR


class TestProviderDetection:
    def test_explicit_anthropic(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        assert _detect_provider() == "anthropic"

    def test_explicit_openai(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.setenv("AI_PROVIDER", "openai")
        assert _detect_provider() == "openai"

    def test_gpt_alias(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.setenv("AI_PROVIDER", "gpt")
        assert _detect_provider() == "openai"

    def test_openai_key_only(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert _detect_provider() == "openai"

    def test_anthropic_key_only(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert _detect_provider() == "anthropic"

    def test_default_is_anthropic(self, monkeypatch):
        from analyze import _detect_provider
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert _detect_provider() == "anthropic"


class TestDefaultModel:
    def test_anthropic_default(self, monkeypatch):
        from analyze import _default_model
        monkeypatch.delenv("CLAUDE_MODEL", raising=False)
        assert _default_model("anthropic") == "claude-sonnet-4-6"

    def test_openai_default(self, monkeypatch):
        from analyze import _default_model
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        assert _default_model("openai") == "gpt-4o"

    def test_env_var_override(self, monkeypatch):
        from analyze import _default_model
        monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-4-6")
        assert _default_model("anthropic") == "claude-opus-4-6"


class TestAnalyzeTranscriptFallback:
    """Full analyze_transcript path using mocked llm_complete."""

    def test_parses_markers_from_response(self, sample_transcript):
        from analyze import analyze_transcript, MarkerType
        canned = '''[
            {"start": "00:00:10.500", "end": "00:00:25.000",
             "type": "HIGHLIGHT", "label": "Big moment", "note": "note"}
        ]'''
        with patch("analyze.llm_complete", return_value=canned):
            markers = analyze_transcript(sample_transcript, {"add_highlights": True})
        assert len(markers) == 1
        assert markers[0].marker_type == MarkerType.HIGHLIGHT
        assert markers[0].label == "Big moment"

    def test_malformed_response_returns_empty(self, sample_transcript):
        from analyze import analyze_transcript
        with patch("analyze.llm_complete", return_value="not json {{{"):
            markers = analyze_transcript(sample_transcript, {"add_highlights": True})
        assert markers == []
