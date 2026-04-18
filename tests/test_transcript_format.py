"""Tests for Transcript export formats (.srt, .vtt) and word-level handling."""


class TestSrtExport:
    def test_single_segment(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(0.0, 2.5, "Hello world")],
            language="en", duration=2.5,
        )
        srt = t.to_srt()
        assert "1\n" in srt
        assert "00:00:00,000 --> 00:00:02,500" in srt
        assert "Hello world" in srt

    def test_multiple_segments_numbered(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[
                TranscriptSegment(0.0, 2.0, "First"),
                TranscriptSegment(3.0, 5.0, "Second"),
                TranscriptSegment(6.0, 9.0, "Third"),
            ],
            language="en", duration=9.0,
        )
        srt = t.to_srt()
        # Should have indices 1, 2, 3
        for n in ("1\n", "2\n", "3\n"):
            assert n in srt
        assert "First" in srt and "Third" in srt

    def test_srt_hh_mm_ss_format(self):
        """Hour boundary should use leading zero HH:MM:SS."""
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(3661.5, 3663.0, "Late")],  # 1:01:01.5
            language="en", duration=3663.0,
        )
        srt = t.to_srt()
        assert "01:01:01,500" in srt


class TestVttExport:
    def test_header(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(0.0, 1.0, "Hi")],
            language="en", duration=1.0,
        )
        vtt = t.to_vtt()
        assert vtt.startswith("WEBVTT")

    def test_uses_dot_separator_not_comma(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(1.5, 2.5, "Hi")],
            language="en", duration=2.5,
        )
        vtt = t.to_vtt()
        # WebVTT uses 00:00:01.500 (dot), SRT uses 00:00:01,500 (comma)
        assert "00:00:01.500" in vtt
        assert "00:00:01,500" not in vtt


class TestIterWords:
    def test_returns_empty_when_no_word_timestamps(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[TranscriptSegment(0.0, 1.0, "hi", words=None)],
            language="en", duration=1.0,
        )
        assert list(t.iter_words()) == []

    def test_returns_words_when_present(self):
        from transcribe import Transcript, TranscriptSegment, Word
        t = Transcript(
            segments=[
                TranscriptSegment(0.0, 1.0, "hi there", words=[
                    Word(0.0, 0.3, "hi"),
                    Word(0.4, 1.0, "there"),
                ]),
            ],
            language="en", duration=1.0,
        )
        words = list(t.iter_words())
        assert [w.text for w in words] == ["hi", "there"]


class TestToText:
    def test_joins_with_spaces(self):
        from transcribe import Transcript, TranscriptSegment
        t = Transcript(
            segments=[
                TranscriptSegment(0.0, 1.0, "Hello"),
                TranscriptSegment(1.0, 2.0, "World"),
            ],
            language="en", duration=2.0,
        )
        assert t.to_text() == "Hello World"


class TestTimestampFormatting:
    def test_srt_ts_exactly_one_second(self):
        from transcribe import _srt_ts
        assert _srt_ts(1.0) == "00:00:01,000"

    def test_srt_ts_rounds_up_ms(self):
        """0.9999 seconds is either 01,000 or 00,999+ms rounded safely — no crash."""
        from transcribe import _srt_ts
        result = _srt_ts(1.9999)
        # Whatever the rounding choice, it must still be a valid SRT timestamp
        assert len(result) == 12
        assert result[2] == ":" and result[5] == ":" and result[8] == ","
