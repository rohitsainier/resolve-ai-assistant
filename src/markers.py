#!/usr/bin/env python3
"""
Marker module for applying edit markers to DaVinci Resolve timeline.
"""

from typing import List
from analyze import EditMarker, MarkerType, get_marker_color


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to frame number."""
    return int(seconds * fps)


def apply_markers(timeline, markers: List[EditMarker]) -> int:
    """
    Apply edit markers to a DaVinci Resolve timeline.
    
    Args:
        timeline: DaVinci Resolve Timeline object
        markers: List of EditMarker objects
    
    Returns:
        Number of markers successfully added
    """
    fps = float(timeline.GetSetting("timelineFrameRate"))
    start_frame = timeline.GetStartFrame()
    
    added = 0
    
    for marker in markers:
        frame = start_frame + seconds_to_frames(marker.start_seconds, fps)
        duration_frames = seconds_to_frames(
            marker.end_seconds - marker.start_seconds, 
            fps
        )
        
        color = get_marker_color(marker.marker_type)
        
        # AddMarker(frameId, color, name, note, duration, customData)
        success = timeline.AddMarker(
            frame,
            color,
            marker.label,
            marker.note,
            duration_frames,
            ""  # customData
        )
        
        if success:
            added += 1
        else:
            print(f"Failed to add marker at frame {frame}: {marker.label}")
    
    return added


def clear_markers(timeline, color: str = None) -> int:
    """
    Clear markers from timeline.
    
    Args:
        timeline: DaVinci Resolve Timeline object
        color: Optional color to filter (None = all colors)
    
    Returns:
        Number of markers removed
    """
    markers = timeline.GetMarkers()
    removed = 0
    
    # Create list of frames to delete (avoid modifying dict during iteration)
    frames_to_delete = [
        frame for frame, marker_data in markers.items()
        if color is None or marker_data.get("color") == color
    ]
    
    for frame in frames_to_delete:
        if timeline.DeleteMarkerAtFrame(frame):
            removed += 1
    
    return removed


def get_markers_by_type(timeline, marker_type: MarkerType) -> dict:
    """
    Get all markers of a specific type from timeline.
    
    Args:
        timeline: DaVinci Resolve Timeline object
        marker_type: MarkerType to filter by
    
    Returns:
        Dict of frame -> marker data
    """
    color = get_marker_color(marker_type)
    all_markers = timeline.GetMarkers()
    
    return {
        frame: data 
        for frame, data in all_markers.items() 
        if data.get("color") == color
    }


def create_subclip_timeline(project, source_timeline, markers: List[EditMarker], 
                            name: str = "Shorts") -> object:
    """
    Create a new timeline with subclips from the marked sections.
    
    Args:
        project: DaVinci Resolve Project object
        source_timeline: Source Timeline object
        markers: List of markers to extract (usually SHORT_CLIP type)
        name: Name for the new timeline
    
    Returns:
        New Timeline object
    """
    media_pool = project.GetMediaPool()
    
    # Create new timeline
    new_timeline = media_pool.CreateEmptyTimeline(name)
    if not new_timeline:
        raise RuntimeError(f"Failed to create timeline: {name}")
    
    fps = float(source_timeline.GetSetting("timelineFrameRate"))
    start_frame = source_timeline.GetStartFrame()
    
    # Get clips from source timeline
    video_items = source_timeline.GetItemListInTrack("video", 1)
    if not video_items:
        raise RuntimeError("No video items in source timeline")
    
    # For each marker, create a subclip
    for marker in markers:
        if marker.marker_type != MarkerType.SHORT_CLIP:
            continue
        
        in_frame = start_frame + seconds_to_frames(marker.start_seconds, fps)
        out_frame = start_frame + seconds_to_frames(marker.end_seconds, fps)
        
        # Find the clip(s) that span this range
        # This is simplified - a full implementation would handle multi-clip ranges
        for clip in video_items:
            clip_start = clip.GetStart()
            clip_end = clip.GetEnd()
            
            if clip_start <= in_frame < clip_end:
                # This clip contains our in point
                media_item = clip.GetMediaPoolItem()
                if media_item:
                    # Add to new timeline
                    # Note: This is a simplified approach
                    # Full implementation would set proper in/out points
                    media_pool.AppendToTimeline([{
                        "mediaPoolItem": media_item,
                        "startFrame": in_frame - clip_start + clip.GetLeftOffset(),
                        "endFrame": out_frame - clip_start + clip.GetLeftOffset(),
                    }])
                break
    
    return new_timeline


def create_rough_cut_timeline(project, source_timeline, dead_air_markers: List[EditMarker],
                               name: str = "Rough Cut") -> object:
    """
    Create a new timeline with dead air removed.
    
    Args:
        project: DaVinci Resolve Project object
        source_timeline: Source Timeline object
        dead_air_markers: List of DEAD_AIR markers to remove
        name: Name for the new timeline
    
    Returns:
        New Timeline object
    """
    # This is a complex operation that would need to:
    # 1. Duplicate the timeline
    # 2. Identify regions to keep (inverse of dead_air_markers)
    # 3. Remove the dead air sections
    # 4. Ripple delete to close gaps
    
    # For now, we'll create markers on the original timeline
    # and let the user make the cuts
    
    media_pool = project.GetMediaPool()
    
    # Duplicate timeline
    # Note: Resolve API doesn't have a direct duplicate, 
    # so we'd need to export/import or rebuild
    
    raise NotImplementedError(
        "Automatic rough cut not yet implemented. "
        "Use the DEAD_AIR markers to manually cut."
    )
