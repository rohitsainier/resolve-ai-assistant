"""
Tests for analysis module.
"""

import pytest
import json
from analyze import (
    MarkerType,
    EditMarker,
    get_marker_color,
    parse_timestamp,
    analyze_for_silence,
    parse_analysis_response,
)


class TestMarkerType:
    """Test marker type enum and colors."""
    
    def test_marker_types_exist(self):
        assert MarkerType.HIGHLIGHT
        assert MarkerType.DEAD_AIR
        assert MarkerType.SHORT_CLIP
        assert MarkerType.REVIEW
    
    def test_marker_colors(self):
        assert get_marker_color(MarkerType.HIGHLIGHT) == "Green"
        assert get_marker_color(MarkerType.DEAD_AIR) == "Red"
        assert get_marker_color(MarkerType.SHORT_CLIP) == "Blue"
        assert get_marker_color(MarkerType.REVIEW) == "Yellow"


class TestEditMarker:
    """Test EditMarker dataclass."""
    
    def test_marker_creation(self):
        marker = EditMarker(
            start_seconds=10.0,
            end_seconds=20.0,
            marker_type=MarkerType.HIGHLIGHT,
            label="Great moment",
            note="Keep this",
            confidence=0.95
        )
        
        assert marker.start_seconds == 10.0
        assert marker.end_seconds == 20.0
        assert marker.marker_type == MarkerType.HIGHLIGHT
        assert marker.label == "Great moment"
        assert marker.confidence == 0.95
    
    def test_marker_defaults(self):
        marker = EditMarker(
            start_seconds=0,
            end_seconds=5,
            marker_type=MarkerType.DEAD_AIR,
            label="Silence"
        )
        
        assert marker.note == ""
        assert marker.confidence == 1.0


class TestSilenceDetection:
    """Test automatic silence/gap detection."""
    
    def test_detect_silence_gaps(self, sample_transcript_with_silence):
        markers = analyze_for_silence(sample_transcript_with_silence)
        
        # Should find 2 gaps: 10s gap and 5s gap
        assert len(markers) == 2
        
        # First gap: 5.0 to 15.0 (10 seconds)
        assert markers[0].start_seconds == 5.0
        assert markers[0].end_seconds == 15.0
        assert markers[0].marker_type == MarkerType.DEAD_AIR
        
        # Second gap: 30.0 to 35.0 (5 seconds)
        assert markers[1].start_seconds == 30.0
        assert markers[1].end_seconds == 35.0
    
    def test_no_silence_below_threshold(self, sample_transcript):
        # Default threshold is 3 seconds
        # sample_transcript has a ~7s gap (35->42), should be detected
        markers = analyze_for_silence(sample_transcript, threshold_seconds=3.0)
        
        # Should find the gap between 35s and 42s
        gap_markers = [m for m in markers if m.start_seconds >= 35]
        assert len(gap_markers) >= 1
    
    def test_custom_threshold(self, sample_transcript_with_silence):
        # With 15s threshold, should only find the 10s gap... wait no
        # Actually with 15s threshold, neither gap qualifies
        markers = analyze_for_silence(sample_transcript_with_silence, threshold_seconds=15.0)
        assert len(markers) == 0


class TestResponseParsing:
    """Test parsing Claude's analysis response."""
    
    def test_parse_valid_json(self):
        response = '''```json
[
  {
    "start": "00:01:23.500",
    "end": "00:01:45.200",
    "type": "HIGHLIGHT",
    "label": "Great reaction",
    "note": "Good for thumbnail"
  },
  {
    "start": "00:02:00.000",
    "end": "00:02:10.000",
    "type": "DEAD_AIR",
    "label": "Silence",
    "note": ""
  }
]
```'''
        
        markers = parse_analysis_response(response)
        
        assert len(markers) == 2
        assert markers[0].marker_type == MarkerType.HIGHLIGHT
        assert markers[0].start_seconds == pytest.approx(83.5, rel=1e-2)
        assert markers[1].marker_type == MarkerType.DEAD_AIR
    
    def test_parse_without_code_blocks(self):
        response = '''[
  {
    "start": "00:00:10.000",
    "end": "00:00:20.000",
    "type": "SHORT_CLIP",
    "label": "Good clip"
  }
]'''
        
        markers = parse_analysis_response(response)
        assert len(markers) == 1
        assert markers[0].marker_type == MarkerType.SHORT_CLIP
    
    def test_parse_invalid_json(self):
        response = "This is not valid JSON at all"
        markers = parse_analysis_response(response)
        assert markers == []
    
    def test_parse_with_invalid_marker_type(self):
        response = '''[
  {
    "start": "00:00:00.000",
    "end": "00:00:05.000",
    "type": "INVALID_TYPE",
    "label": "Bad marker"
  },
  {
    "start": "00:00:10.000",
    "end": "00:00:15.000",
    "type": "HIGHLIGHT",
    "label": "Good marker"
  }
]'''
        
        markers = parse_analysis_response(response)
        # Should skip invalid, keep valid
        assert len(markers) == 1
        assert markers[0].label == "Good marker"


class TestTimestampParsing:
    """Test timestamp parsing in analyze module."""
    
    def test_parse_standard_format(self):
        assert parse_timestamp("00:01:30.500") == 90.5
        assert parse_timestamp("01:00:00.000") == 3600.0
    
    def test_parse_comma_decimal(self):
        # Some locales use comma
        assert parse_timestamp("00:01:30,500") == 90.5
    
    def test_parse_minutes_only(self):
        assert parse_timestamp("01:30.000") == 90.0
    
    def test_parse_seconds_only(self):
        assert parse_timestamp("90.5") == 90.5
