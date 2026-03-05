"""
Tests for transcription module.
"""

import pytest
import os
import tempfile
from transcribe import (
    Transcript,
    TranscriptSegment,
    format_timestamp,
    parse_timestamp,
)


class TestTimestampFormatting:
    """Test timestamp conversion functions."""
    
    def test_format_timestamp_simple(self):
        assert format_timestamp(0) == "00:00:00.000"
        assert format_timestamp(1.5) == "00:00:01.500"
        assert format_timestamp(65.123) == "00:01:05.123"
    
    def test_format_timestamp_hours(self):
        assert format_timestamp(3661.5) == "01:01:01.500"
        assert format_timestamp(7200) == "02:00:00.000"
    
    def test_parse_timestamp_simple(self):
        assert parse_timestamp("00:00:00.000") == 0.0
        assert parse_timestamp("00:00:01.500") == 1.5
        assert parse_timestamp("00:01:05.123") == pytest.approx(65.123, rel=1e-3)
    
    def test_parse_timestamp_hours(self):
        assert parse_timestamp("01:01:01.500") == 3661.5
        assert parse_timestamp("02:00:00.000") == 7200.0
    
    def test_roundtrip(self):
        """Test that format -> parse -> format is stable."""
        original = 3723.456
        formatted = format_timestamp(original)
        parsed = parse_timestamp(formatted)
        assert parsed == pytest.approx(original, rel=1e-3)


class TestTranscript:
    """Test Transcript dataclass methods."""
    
    def test_to_text(self, sample_transcript):
        text = sample_transcript.to_text()
        assert "Hey everyone" in text
        assert "welcome back" in text
        assert len(text) > 100
    
    def test_to_timestamped_text(self, sample_transcript):
        text = sample_transcript.to_timestamped_text()
        assert "[00:00:00.000" in text
        assert "Hey everyone" in text
        # Should have timestamps for each segment
        lines = text.strip().split("\n")
        assert len(lines) == len(sample_transcript.segments)
    
    def test_duration(self, sample_transcript):
        assert sample_transcript.duration == 115.0
    
    def test_language(self, sample_transcript):
        assert sample_transcript.language == "en"


class TestTranscriptSegment:
    """Test individual transcript segments."""
    
    def test_segment_creation(self):
        seg = TranscriptSegment(10.5, 15.3, "Hello world")
        assert seg.start == 10.5
        assert seg.end == 15.3
        assert seg.text == "Hello world"
    
    def test_segment_duration(self):
        seg = TranscriptSegment(10.0, 20.0, "Test")
        duration = seg.end - seg.start
        assert duration == 10.0


# Note: Actual transcription tests require whisper and audio files
# These are integration tests that should be run separately

class TestTranscriptionIntegration:
    """Integration tests for actual transcription (requires whisper)."""
    
    @pytest.mark.skipif(
        not os.environ.get("RUN_INTEGRATION_TESTS"),
        reason="Integration tests disabled"
    )
    def test_transcribe_audio_file(self):
        """Test transcribing an actual audio file."""
        from transcribe import transcribe_audio
        
        # This would need a real audio file
        # For CI, we'd provide a small test audio file
        pass
