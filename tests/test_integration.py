"""
Integration tests for the full workflow.
These tests require external services (Whisper, Claude) and are skipped by default.
"""

import pytest
import os
import json
import tempfile


# Skip all tests in this file unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Integration tests disabled. Set RUN_INTEGRATION_TESTS=1 to run."
)


class TestFullWorkflow:
    """Test the complete workflow from video to markers."""
    
    def test_transcribe_and_analyze(self, sample_transcript):
        """Test analysis with a pre-made transcript (no whisper needed)."""
        from analyze import analyze_transcript
        
        options = {
            "add_highlights": True,
            "mark_dead_air": True,
            "find_shorts": True,
        }
        
        markers = analyze_transcript(sample_transcript, options)
        
        # Should return some markers
        assert len(markers) > 0
        
        # Markers should have valid types
        from analyze import MarkerType
        for marker in markers:
            assert marker.marker_type in MarkerType
            assert marker.start_seconds >= 0
            assert marker.end_seconds > marker.start_seconds
            assert marker.label
    
    def test_cli_transcribe(self):
        """Test CLI transcribe command."""
        # Would need a real video file
        pass
    
    def test_cli_analyze(self):
        """Test CLI analyze command."""
        # Would need a real video or transcript file
        pass


class TestCLICommands:
    """Test CLI command parsing and execution."""
    
    def test_help_output(self):
        """Test that CLI shows help without errors."""
        import subprocess
        import sys
        
        result = subprocess.run(
            [sys.executable, "src/cli.py", "--help"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )
        
        assert result.returncode == 0
        assert "AI Edit Assistant" in result.stdout
    
    def test_transcribe_help(self):
        """Test transcribe subcommand help."""
        import subprocess
        import sys
        
        result = subprocess.run(
            [sys.executable, "src/cli.py", "transcribe", "--help"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )
        
        assert result.returncode == 0
        assert "video" in result.stdout.lower()
    
    def test_analyze_help(self):
        """Test analyze subcommand help."""
        import subprocess
        import sys
        
        result = subprocess.run(
            [sys.executable, "src/cli.py", "analyze", "--help"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )
        
        assert result.returncode == 0
        assert "transcript" in result.stdout.lower()


class TestMarkerExportImport:
    """Test marker data serialization."""
    
    def test_export_markers_to_json(self):
        """Test exporting markers to JSON file."""
        from analyze import EditMarker, MarkerType
        
        markers = [
            EditMarker(10.0, 20.0, MarkerType.HIGHLIGHT, "Test", "Note", 0.9),
            EditMarker(30.0, 35.0, MarkerType.DEAD_AIR, "Silence", "", 1.0),
        ]
        
        data = [
            {
                "start": m.start_seconds,
                "end": m.end_seconds,
                "type": m.marker_type.value,
                "label": m.label,
                "note": m.note,
                "confidence": m.confidence
            }
            for m in markers
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            temp_path = f.name
        
        try:
            # Read it back
            with open(temp_path) as f:
                loaded = json.load(f)
            
            assert len(loaded) == 2
            assert loaded[0]["type"] == "highlight"
            assert loaded[1]["type"] == "dead_air"
        finally:
            os.unlink(temp_path)
    
    def test_import_markers_from_json(self):
        """Test importing markers from JSON file."""
        from analyze import EditMarker, MarkerType
        
        data = [
            {
                "start": 10.0,
                "end": 20.0,
                "type": "highlight",
                "label": "Good part",
                "note": "Keep",
                "confidence": 0.95
            }
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            temp_path = f.name
        
        try:
            with open(temp_path) as f:
                loaded = json.load(f)
            
            markers = [
                EditMarker(
                    start_seconds=m["start"],
                    end_seconds=m["end"],
                    marker_type=MarkerType(m["type"]),
                    label=m["label"],
                    note=m.get("note", ""),
                    confidence=m.get("confidence", 1.0)
                )
                for m in loaded
            ]
            
            assert len(markers) == 1
            assert markers[0].marker_type == MarkerType.HIGHLIGHT
            assert markers[0].confidence == 0.95
        finally:
            os.unlink(temp_path)
