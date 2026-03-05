"""
Pytest fixtures for Resolve AI Assistant tests.
"""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def sample_transcript():
    """Create a sample transcript for testing."""
    from transcribe import Transcript, TranscriptSegment
    
    return Transcript(
        segments=[
            TranscriptSegment(0.0, 3.5, "Hey everyone, welcome back to the channel."),
            TranscriptSegment(4.0, 12.0, "Today we're going to look at something really exciting about AI coding assistants."),
            TranscriptSegment(12.5, 25.0, "So I just discovered this amazing feature in Claude Code and I literally cannot believe how well it works."),
            TranscriptSegment(25.5, 35.0, "Let me show you exactly how to set this up step by step."),
            # Gap here - dead air
            TranscriptSegment(42.0, 55.0, "First, you need to install the CLI tool. It's super simple, just one command."),
            TranscriptSegment(55.5, 70.0, "And boom, you're ready to go. Now let's look at a real example."),
            TranscriptSegment(70.5, 90.0, "I'm going to ask it to refactor this function and watch what happens. This is the part that blew my mind."),
            TranscriptSegment(90.5, 105.0, "See how it understood the context? It didn't just change the code, it improved the whole structure."),
            TranscriptSegment(105.5, 115.0, "Alright, that's going to wrap up today's video. Let me know in the comments what you want to see next."),
        ],
        language="en",
        duration=115.0
    )


@pytest.fixture
def sample_transcript_with_silence():
    """Transcript with obvious silence gaps."""
    from transcribe import Transcript, TranscriptSegment
    
    return Transcript(
        segments=[
            TranscriptSegment(0.0, 5.0, "Hello and welcome."),
            # 10 second gap
            TranscriptSegment(15.0, 20.0, "Sorry about that, had some technical issues."),
            TranscriptSegment(20.5, 30.0, "Anyway, let's continue with the tutorial."),
            # 5 second gap
            TranscriptSegment(35.0, 45.0, "Here's the important part you need to know."),
        ],
        language="en",
        duration=45.0
    )


@pytest.fixture
def mock_resolve():
    """Mock DaVinci Resolve objects for testing."""
    
    class MockTimeline:
        def __init__(self):
            self.name = "Test Timeline"
            self.markers = {}
            self.frame_rate = 24.0
            self.start_frame = 0
        
        def GetName(self):
            return self.name
        
        def GetSetting(self, key):
            if key == "timelineFrameRate":
                return str(self.frame_rate)
            return None
        
        def GetStartFrame(self):
            return self.start_frame
        
        def AddMarker(self, frame, color, name, note, duration, custom_data=""):
            self.markers[frame] = {
                "color": color,
                "name": name,
                "note": note,
                "duration": duration,
            }
            return True
        
        def GetMarkers(self):
            return self.markers
        
        def DeleteMarkerAtFrame(self, frame):
            if frame in self.markers:
                del self.markers[frame]
                return True
            return False
        
        def GetItemListInTrack(self, track_type, index):
            return []
    
    class MockProject:
        def __init__(self):
            self.timeline = MockTimeline()
        
        def GetCurrentTimeline(self):
            return self.timeline
    
    class MockProjectManager:
        def __init__(self):
            self.project = MockProject()
        
        def GetCurrentProject(self):
            return self.project
    
    class MockResolve:
        def __init__(self):
            self.pm = MockProjectManager()
        
        def GetProjectManager(self):
            return self.pm
        
        def Fusion(self):
            return None
    
    return MockResolve()
