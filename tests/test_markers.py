"""
Tests for markers module.
"""

import pytest
from analyze import EditMarker, MarkerType
from markers import (
    seconds_to_frames,
    apply_markers,
    clear_markers,
    get_markers_by_type,
)


class TestFrameConversion:
    """Test frame/second conversion."""
    
    def test_seconds_to_frames_24fps(self):
        assert seconds_to_frames(0, 24.0) == 0
        assert seconds_to_frames(1.0, 24.0) == 24
        assert seconds_to_frames(10.0, 24.0) == 240
    
    def test_seconds_to_frames_30fps(self):
        assert seconds_to_frames(1.0, 30.0) == 30
        assert seconds_to_frames(2.5, 30.0) == 75
    
    def test_seconds_to_frames_60fps(self):
        assert seconds_to_frames(1.0, 60.0) == 60
    
    def test_fractional_seconds(self):
        # 0.5 seconds at 24fps = 12 frames
        assert seconds_to_frames(0.5, 24.0) == 12
        # 1.5 seconds at 24fps = 36 frames
        assert seconds_to_frames(1.5, 24.0) == 36


class TestApplyMarkers:
    """Test applying markers to timeline."""
    
    def test_apply_single_marker(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(
                start_seconds=10.0,
                end_seconds=15.0,
                marker_type=MarkerType.HIGHLIGHT,
                label="Test marker",
                note="Test note"
            )
        ]
        
        added = apply_markers(timeline, markers)
        
        assert added == 1
        assert len(timeline.GetMarkers()) == 1
        
        # Check marker was added at correct frame (10s * 24fps = 240)
        assert 240 in timeline.GetMarkers()
        
        marker_data = timeline.GetMarkers()[240]
        assert marker_data["color"] == "Green"
        assert marker_data["name"] == "Test marker"
        assert marker_data["note"] == "Test note"
    
    def test_apply_multiple_markers(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "Intro"),
            EditMarker(10, 12, MarkerType.DEAD_AIR, "Silence"),
            EditMarker(20, 30, MarkerType.SHORT_CLIP, "Good clip"),
        ]
        
        added = apply_markers(timeline, markers)
        
        assert added == 3
        assert len(timeline.GetMarkers()) == 3
    
    def test_marker_colors(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "Green"),
            EditMarker(10, 15, MarkerType.DEAD_AIR, "Red"),
            EditMarker(20, 25, MarkerType.SHORT_CLIP, "Blue"),
            EditMarker(30, 35, MarkerType.REVIEW, "Yellow"),
        ]
        
        apply_markers(timeline, markers)
        
        all_markers = timeline.GetMarkers()
        assert all_markers[0]["color"] == "Green"
        assert all_markers[240]["color"] == "Red"
        assert all_markers[480]["color"] == "Blue"
        assert all_markers[720]["color"] == "Yellow"
    
    def test_marker_duration(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        # 5 second marker at 24fps = 120 frames duration
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "5 seconds"),
        ]
        
        apply_markers(timeline, markers)
        
        marker_data = timeline.GetMarkers()[0]
        assert marker_data["duration"] == 120  # 5 * 24


class TestClearMarkers:
    """Test clearing markers from timeline."""
    
    def test_clear_all_markers(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        # Add some markers
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "One"),
            EditMarker(10, 15, MarkerType.DEAD_AIR, "Two"),
        ]
        apply_markers(timeline, markers)
        assert len(timeline.GetMarkers()) == 2
        
        # Clear all
        removed = clear_markers(timeline)
        assert removed == 2
        assert len(timeline.GetMarkers()) == 0
    
    def test_clear_by_color(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "Green1"),
            EditMarker(10, 15, MarkerType.HIGHLIGHT, "Green2"),
            EditMarker(20, 25, MarkerType.DEAD_AIR, "Red1"),
        ]
        apply_markers(timeline, markers)
        assert len(timeline.GetMarkers()) == 3
        
        # Clear only green markers
        removed = clear_markers(timeline, color="Green")
        assert removed == 2
        assert len(timeline.GetMarkers()) == 1
        
        # Remaining marker should be red
        remaining = list(timeline.GetMarkers().values())[0]
        assert remaining["color"] == "Red"


class TestGetMarkersByType:
    """Test filtering markers by type."""
    
    def test_get_highlights(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "H1"),
            EditMarker(10, 15, MarkerType.DEAD_AIR, "D1"),
            EditMarker(20, 25, MarkerType.HIGHLIGHT, "H2"),
        ]
        apply_markers(timeline, markers)
        
        highlights = get_markers_by_type(timeline, MarkerType.HIGHLIGHT)
        assert len(highlights) == 2
    
    def test_get_dead_air(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "H1"),
            EditMarker(10, 15, MarkerType.DEAD_AIR, "D1"),
            EditMarker(20, 25, MarkerType.DEAD_AIR, "D2"),
        ]
        apply_markers(timeline, markers)
        
        dead_air = get_markers_by_type(timeline, MarkerType.DEAD_AIR)
        assert len(dead_air) == 2
    
    def test_get_nonexistent_type(self, mock_resolve):
        timeline = mock_resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        
        markers = [
            EditMarker(0, 5, MarkerType.HIGHLIGHT, "H1"),
        ]
        apply_markers(timeline, markers)
        
        shorts = get_markers_by_type(timeline, MarkerType.SHORT_CLIP)
        assert len(shorts) == 0
