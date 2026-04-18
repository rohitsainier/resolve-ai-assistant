"""Tests for audio_analysis.py — focused on parsing regex on canned ffmpeg output."""

from unittest.mock import patch


SAMPLE_LOUDNORM_OUTPUT = """
Input #0, wav, from '/tmp/test.wav':
  Metadata:
    encoder         : Lavf58.29.100
  Duration: 00:00:10.00, bitrate: 1536 kb/s
Stream mapping:
  Stream #0:0 -> #0:0 (pcm_s16le (native) -> pcm_s16le (native))
[Parsed_loudnorm_0 @ 0x7f1234]
{
	"input_i" : "-18.50",
	"input_tp" : "-3.20",
	"input_lra" : "7.80",
	"input_thresh" : "-28.50",
	"output_i" : "-23.00",
	"output_tp" : "-2.00",
	"output_lra" : "7.00",
	"output_thresh" : "-33.50",
	"normalization_type" : "dynamic",
	"target_offset" : "0.00"
}
"""


SAMPLE_SILENCEDETECT_OUTPUT = """
[silencedetect @ 0x7f1234] silence_start: 5.234
[silencedetect @ 0x7f1234] silence_end: 8.891 | silence_duration: 3.657
[silencedetect @ 0x7f1234] silence_start: 20.0
[silencedetect @ 0x7f1234] silence_end: 22.5 | silence_duration: 2.5
"""


SAMPLE_ASTATS_OUTPUT = """
[Parsed_astats_0 @ 0x7f1234] Overall
[Parsed_astats_0 @ 0x7f1234]   Peak level dB: -0.500
[Parsed_astats_0 @ 0x7f1234]   RMS level dB: -18.200
[Parsed_astats_0 @ 0x7f1234]   Max level dB: -0.500
"""


class TestAnalyzeLoudness:
    def test_parses_json_block(self):
        from audio_analysis import analyze_loudness
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=SAMPLE_LOUDNORM_OUTPUT):
            result = analyze_loudness("/tmp/fake.wav")
        assert result["integrated_lufs"] == -18.5
        assert result["true_peak_dbfs"] == -3.2
        assert result["loudness_range"] == 7.8

    def test_missing_json_block(self):
        from audio_analysis import analyze_loudness
        with patch("audio_analysis._run_ffmpeg_analysis", return_value="no json here"):
            result = analyze_loudness("/tmp/fake.wav")
        assert "error" in result


class TestSilenceDetection:
    def test_parses_multiple_regions(self):
        from audio_analysis import detect_silence
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=SAMPLE_SILENCEDETECT_OUTPUT):
            regions = detect_silence("/tmp/fake.wav")
        assert len(regions) == 2
        assert regions[0]["start"] == 5.23
        assert regions[0]["end"] == 8.89
        assert regions[0]["duration"] == 3.66
        assert regions[1]["duration"] == 2.5

    def test_empty_output_returns_empty(self):
        from audio_analysis import detect_silence
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=""):
            assert detect_silence("/tmp/fake.wav") == []


class TestClippingDetection:
    def test_detects_clipping(self):
        """Peak of -0.5 dBFS exceeds the -1.0 threshold → clipping."""
        from audio_analysis import detect_clipping
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=SAMPLE_ASTATS_OUTPUT):
            result = detect_clipping("/tmp/fake.wav")
        assert result["peak_dbfs"] == -0.5
        assert result["rms_dbfs"] == -18.2
        assert result["clipping"] is True

    def test_no_clipping_when_below_threshold(self):
        from audio_analysis import detect_clipping
        safe_output = SAMPLE_ASTATS_OUTPUT.replace("-0.500", "-5.000")
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=safe_output):
            result = detect_clipping("/tmp/fake.wav")
        assert result["clipping"] is False

    def test_negative_infinity_peak(self):
        from audio_analysis import detect_clipping
        silent = SAMPLE_ASTATS_OUTPUT.replace("-0.500", "-inf")
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=silent):
            result = detect_clipping("/tmp/fake.wav")
        assert result["peak_dbfs"] == float("-inf")
        assert result["clipping"] is False


class TestFullReport:
    def test_report_aggregates_all_sections(self):
        """full_audio_report runs all three analyzers and produces recommendations."""
        from audio_analysis import full_audio_report

        def fake_runner(_, fstr, *a, **k):
            if "loudnorm" in fstr:
                return SAMPLE_LOUDNORM_OUTPUT
            if "silencedetect" in fstr:
                return SAMPLE_SILENCEDETECT_OUTPUT
            if "astats" in fstr:
                return SAMPLE_ASTATS_OUTPUT
            return ""

        with patch("audio_analysis._run_ffmpeg_analysis", side_effect=fake_runner):
            report = full_audio_report("/tmp/fake.wav")

        assert "loudness" in report
        assert "clipping" in report
        assert "silence_regions" in report
        assert "recommendations" in report
        # -18.5 LUFS is quieter than YouTube's -14 target → should recommend gain
        recs = " ".join(report["recommendations"]).lower()
        assert "lufs" in recs or "loud" in recs or "quiet" in recs
        # Clipping should be flagged
        assert any("clip" in r.lower() or "peak" in r.lower() for r in report["recommendations"])

    def test_report_handles_empty_output(self):
        from audio_analysis import full_audio_report
        with patch("audio_analysis._run_ffmpeg_analysis", return_value=""):
            report = full_audio_report("/tmp/fake.wav")
        # Shouldn't crash even with empty outputs
        assert "loudness" in report
        assert "silence_regions" in report
