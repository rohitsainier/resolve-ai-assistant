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
    """Apply edit markers to a DaVinci Resolve timeline.

    Returns the number of markers successfully added.
    """
    import os, time
    log_path = os.path.expanduser("~/.resolve-ai-assistant/whisper.log")
    def log(msg):
        try:
            with open(log_path, "a") as lf:
                lf.write(f"{time.strftime('%H:%M:%S')} [markers] {msg}\n")
                lf.flush()
        except Exception:
            pass

    log(f"apply_markers called with {len(markers)} markers")
    t_start = time.time()

    try:
        fps = float(timeline.GetSetting("timelineFrameRate"))
        log(f"got fps={fps}")
    except Exception as e:
        log(f"fps call failed: {e}")
        raise

    added = 0
    # Resolve's AddMarker takes the frame OFFSET from the timeline start
    # (NOT the absolute timeline frame number). Passing absolute frames lands
    # markers at 2x the intended position.
    for i, marker in enumerate(markers):
        frame_offset = seconds_to_frames(marker.start_seconds, fps)
        duration_frames = max(1, seconds_to_frames(
            marker.end_seconds - marker.start_seconds, fps))
        color = get_marker_color(marker.marker_type)
        log(f"  [{i+1}/{len(markers)}] offset={frame_offset} dur={duration_frames} color={color} label={marker.label!r}")
        try:
            t0 = time.time()
            success = timeline.AddMarker(
                frame_offset, color, marker.label, marker.note,
                duration_frames, "",
            )
            log(f"     AddMarker -> {success} ({time.time()-t0:.2f}s)")
            if success:
                added += 1
        except Exception as e:
            log(f"     AddMarker RAISED: {type(e).__name__}: {e}")

    log(f"apply_markers done: {added}/{len(markers)} added in {time.time()-t_start:.1f}s")

    # Diagnostic: dump what Resolve actually thinks the markers are at
    try:
        all_markers = timeline.GetMarkers() or {}
        log(f"timeline.GetMarkers() returned {len(all_markers)} entries:")
        for fid, data in sorted(all_markers.items())[:15]:
            log(f"  frame_in_dict={fid} data={data}")
        try:
            log(f"timeline.GetStartFrame()={timeline.GetStartFrame()}")
            log(f"timeline.GetEndFrame()={timeline.GetEndFrame()}")
            log(f"timeline.GetStartTimecode()={timeline.GetStartTimecode()}")
        except Exception as e:
            log(f"start/end query failed: {e}")
    except Exception as e:
        log(f"GetMarkers() failed: {e}")

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


def _build_segments_for_range(video_items, in_frame: int, out_frame: int):
    """Walk every source clip overlapping [in_frame, out_frame) and produce
    AppendToTimeline-ready segment dicts mapped into source media frames."""
    segments = []
    for clip in video_items:
        try:
            clip_start = clip.GetStart()
            clip_end = clip.GetEnd()
            left_offset = clip.GetLeftOffset()
        except Exception:
            continue
        if clip_end <= in_frame or clip_start >= out_frame:
            continue
        media_item = clip.GetMediaPoolItem()
        if not media_item:
            continue
        eff_in = max(in_frame, clip_start)
        eff_out = min(out_frame, clip_end)
        if eff_out <= eff_in:
            continue
        segments.append({
            "mediaPoolItem": media_item,
            "startFrame": eff_in - clip_start + left_offset,
            "endFrame": eff_out - clip_start + left_offset,
        })
    return segments


def create_subclip_timeline(project, source_timeline, markers: List[EditMarker],
                            name: str = "Shorts") -> object:
    """Create a new timeline made of just the SHORT_CLIP marker regions.

    Walks every video clip that intersects each marker so multi-clip shorts
    are reconstructed correctly. Returns the new Timeline (or None if the
    source has no eligible content).
    """
    shorts_markers = [m for m in markers if m.marker_type == MarkerType.SHORT_CLIP]
    if not shorts_markers:
        return None

    media_pool = project.GetMediaPool()

    fps = float(source_timeline.GetSetting("timelineFrameRate"))
    start_frame = source_timeline.GetStartFrame()
    video_items = source_timeline.GetItemListInTrack("video", 1) or []
    if not video_items:
        raise RuntimeError("No video items in source timeline")

    new_timeline = media_pool.CreateEmptyTimeline(name)
    if not new_timeline:
        raise RuntimeError(f"Failed to create timeline: {name}")

    # Switch context to the new timeline so AppendToTimeline targets it.
    project.SetCurrentTimeline(new_timeline)

    appended = 0
    for marker in sorted(shorts_markers, key=lambda m: m.start_seconds):
        in_frame = start_frame + seconds_to_frames(marker.start_seconds, fps)
        out_frame = start_frame + seconds_to_frames(marker.end_seconds, fps)
        segs = _build_segments_for_range(video_items, in_frame, out_frame)
        if segs and media_pool.AppendToTimeline(segs):
            appended += len(segs)

    # Restore original timeline as the user's working context.
    project.SetCurrentTimeline(source_timeline)

    if appended == 0:
        return None
    return new_timeline


def create_rough_cut_timeline(project, source_timeline, dead_air_markers: List[EditMarker],
                              name: str = "Rough Cut") -> object:
    """Create a new timeline with all DEAD_AIR regions removed.

    The keep regions are the inverse of dead_air_markers across the source
    timeline's full range. Each keep region is rebuilt clip-by-clip so the
    output preserves takes that span multiple source clips.
    """
    fps = float(source_timeline.GetSetting("timelineFrameRate"))
    tl_start = source_timeline.GetStartFrame()
    tl_end = source_timeline.GetEndFrame()

    video_items = source_timeline.GetItemListInTrack("video", 1) or []
    if not video_items:
        raise RuntimeError("No video items in source timeline")

    # Convert dead-air markers to timeline-frame ranges, merge overlapping ones.
    cuts = []
    for m in dead_air_markers:
        if m.marker_type != MarkerType.DEAD_AIR:
            continue
        s = tl_start + seconds_to_frames(m.start_seconds, fps)
        e = tl_start + seconds_to_frames(m.end_seconds, fps)
        if e > s:
            cuts.append((max(s, tl_start), min(e, tl_end)))
    cuts.sort()

    merged = []
    for s, e in cuts:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Inverse → keep regions
    keep = []
    cursor = tl_start
    for s, e in merged:
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < tl_end:
        keep.append((cursor, tl_end))

    if not keep:
        raise RuntimeError("Dead-air markers cover the entire timeline; nothing to keep")

    media_pool = project.GetMediaPool()
    new_timeline = media_pool.CreateEmptyTimeline(name)
    if not new_timeline:
        raise RuntimeError(f"Failed to create timeline: {name}")

    project.SetCurrentTimeline(new_timeline)

    appended = 0
    for in_frame, out_frame in keep:
        segs = _build_segments_for_range(video_items, in_frame, out_frame)
        if segs and media_pool.AppendToTimeline(segs):
            appended += len(segs)

    project.SetCurrentTimeline(source_timeline)

    if appended == 0:
        raise RuntimeError("Failed to append any segments to rough cut")
    return new_timeline
