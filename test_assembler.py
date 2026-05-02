# test_assembler.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from renderer import (
    assemble_video,
    _build_filter_complex,
    _create_clip,
    _run_final_assembly,
    _validate_inputs,
)


class FakeMetadata:
    def __init__(self, position: int) -> None:
        self.position = position


# ── _validate_inputs ──────────────────────────────────────────────


class TestValidateInputs:
    def test_empty_metadatas_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No songs to process"):
            _validate_inputs([], Path("f"), Path("a"))

    @patch.object(Path, "exists", return_value=True)
    def test_valid_inputs_pass(self, mock_exists: MagicMock) -> None:
        _validate_inputs([FakeMetadata(0)], Path("f"), Path("a"))
        assert mock_exists.call_count == 2  # frame + audio

    @patch.object(Path, "exists", return_value=False)
    def test_missing_frame_raises(self, mock_exists: MagicMock) -> None:
        with pytest.raises(FileNotFoundError, match="Frame not found"):
            _validate_inputs([FakeMetadata(0)], Path("f"), Path("a"))

    @patch.object(Path, "exists")
    def test_missing_audio_raises(self, mock_exists: MagicMock) -> None:
        mock_exists.side_effect = [True, False]
        with pytest.raises(FileNotFoundError, match="Audio not found"):
            _validate_inputs([FakeMetadata(0)], Path("f"), Path("a"))

    @patch.object(Path, "exists")
    def test_validates_all_metadatas(self, mock_exists: MagicMock) -> None:
        mock_exists.return_value = True
        _validate_inputs(
            [FakeMetadata(0), FakeMetadata(1), FakeMetadata(2)],
            Path("f"),
            Path("a"),
        )
        assert mock_exists.call_count == 6  # 3 frames + 3 audios


# ── _build_filter_complex (pure function — most testable) ─────────


class TestBuildFilterComplex:
    def test_two_clips_produces_correct_filters(self) -> None:
        result = _build_filter_complex(2, 15.0, 1.0)
        assert "[0:v][1:v]xfade=transition=fade:duration=1.0:offset=14.0[v1]" in result
        assert "[0:a][1:a]acrossfade=d=1.0:c1=tri:c2=tri[a_out]" in result

    def test_three_clips_produces_chained_filters(self) -> None:
        result = _build_filter_complex(3, 15.0, 1.0)
        # Video chain: 0:v → v1 → v2
        assert "[0:v][1:v]xfade=transition=fade:duration=1.0:offset=14.0[v1]" in result
        assert "[v1][2:v]xfade=transition=fade:duration=1.0:offset=28.0[v2]" in result
        # Audio chain: 0:a → a1 → a_out
        assert "[0:a][1:a]acrossfade=d=1.0:c1=tri:c2=tri[a1]" in result
        assert "[a1][2:a]acrossfade=d=1.0:c1=tri:c2=tri[a_out]" in result

    def test_single_clip_returns_empty_string(self) -> None:
        result = _build_filter_complex(1, 15.0, 1.0)
        assert result == ""

    def test_offsets_accumulate_correctly(self) -> None:
        result = _build_filter_complex(4, 10.0, 2.0)
        # i=1: 10*1 - 2*1 = 8
        # i=2: 10*2 - 2*2 = 16
        # i=3: 10*3 - 2*3 = 24
        assert "offset=8.0" in result
        assert "offset=16.0" in result
        assert "offset=24.0" in result

    def test_last_audio_label_is_always_a_out(self) -> None:
        for n in range(2, 6):
            result = _build_filter_complex(n, 15.0, 1.0)
            assert "[a_out]" in result

    def test_intermediate_audio_labels_are_numbered(self) -> None:
        result = _build_filter_complex(4, 15.0, 1.0)
        assert "[a1]" in result
        assert "[a2]" in result
        # a3 should NOT exist — last is a_out
        assert "[a3]" not in result

    def test_semicolon_separates_all_filters(self) -> None:
        result = _build_filter_complex(3, 15.0, 1.0)
        parts = result.split(";")
        assert len(parts) == 4  # 2 video + 2 audio


# ── _create_clip ──────────────────────────────────────────────────


class TestCreateClip:
    @patch("renderer.subprocess.run")
    def test_successful_clip_invokes_ffmpeg(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        _create_clip(Path("frame.png"), Path("audio.mp3"), Path("out.mp4"), 15.0)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-t" in cmd
        t_index = cmd.index("-t")
        assert cmd[t_index + 1] == "15.0"

    @patch("renderer.subprocess.run")
    def test_ffmpeg_failure_raises_runtime_error(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="encode error")
        with pytest.raises(RuntimeError, match="Failed to create clip"):
            _create_clip(
                Path("frame.png"), Path("audio.mp3"), Path("out.mp4"), 15.0
            )

    @patch("renderer.subprocess.run")
    def test_no_check_flag_in_subprocess(self, mock_run: MagicMock) -> None:
        """Ensure check=True is NOT used — we handle returncode manually."""
        mock_run.return_value = MagicMock(returncode=0)
        _create_clip(Path("f.png"), Path("a.mp3"), Path("o.mp4"), 10.0)
        assert mock_run.call_args[1].get("check") is not True


# ── _run_final_assembly ──────────────────────────────────────────


class TestRunFinalAssembly:
    @patch("renderer.subprocess.run")
    def test_successful_assembly(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        _run_final_assembly(
            [Path("a.mp4"), Path("b.mp4")],
            "some_filter",
            "v1",
            Path("out.mp4"),
        )
        cmd = mock_run.call_args[0][0]
        assert "-filter_complex" in cmd
        assert "-map" in cmd

    @patch("renderer.subprocess.run")
    def test_assembly_failure_raises_runtime_error(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="mux error")
        with pytest.raises(RuntimeError, match="Failed to assemble video"):
            _run_final_assembly(
                [Path("a.mp4")], "filter", "v1", Path("out.mp4")
            )


# ── assemble_video (integration) ─────────────────────────────────


class TestAssembleVideo:
    def test_empty_metadatas_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No songs to process"):
            assemble_video([], Path("f"), Path("a"), Path("out.mp4"))

    @patch("renderer._validate_inputs")
    @patch("renderer._create_clip")
    @patch("renderer.shutil.copy2")
    @patch.object(Path, "mkdir")
    def test_single_clip_uses_shutil_copy2(
        self,
        mock_mkdir: MagicMock,
        mock_copy: MagicMock,
        mock_create: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        assemble_video([FakeMetadata(0)], Path("f"), Path("a"), Path("out.mp4"))
        mock_copy.assert_called_once()
        src = mock_copy.call_args[0][0]
        dst = mock_copy.call_args[0][1]
        assert src.name == "00.mp4"
        assert dst == Path("out.mp4")

    @patch("renderer._validate_inputs")
    @patch("renderer._create_clip")
    @patch("renderer._run_final_assembly")
    @patch.object(Path, "mkdir")
    def test_multiple_clips_trigger_assembly(
        self,
        mock_mkdir: MagicMock,
        mock_assemble: MagicMock,
        mock_create: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        metas = [FakeMetadata(0), FakeMetadata(1), FakeMetadata(2)]
        assemble_video(metas, Path("f"), Path("a"), Path("out.mp4"))
        mock_assemble.assert_called_once()

    @patch("renderer._validate_inputs")
    @patch("renderer._create_clip")
    @patch("renderer._run_final_assembly")
    @patch.object(Path, "mkdir")
    def test_clips_are_created_in_reverse_order(
        self,
        mock_mkdir: MagicMock,
        mock_assemble: MagicMock,
        mock_create: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        metas = [FakeMetadata(0), FakeMetadata(1), FakeMetadata(2)]
        assemble_video(metas, Path("f"), Path("a"), Path("out.mp4"))
        calls = mock_create.call_args_list
        # First clip created should be position 2 (reversed)
        assert calls[0][0][0] == Path("f") / "02.png"
        assert calls[0][0][1] == Path("a") / "02.mp3"
        # Second clip: position 1
        assert calls[1][0][0] == Path("f") / "01.png"
        # Third clip: position 0
        assert calls[2][0][0] == Path("f") / "00.png"

    @patch("renderer._validate_inputs")
    @patch("renderer._create_clip")
    @patch("renderer._run_final_assembly")
    @patch.object(Path, "mkdir")
    def test_clip_paths_passed_in_reverse_order(
        self,
        mock_mkdir: MagicMock,
        mock_assemble: MagicMock,
        mock_create: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        metas = [FakeMetadata(0), FakeMetadata(1), FakeMetadata(2)]
        assemble_video(metas, Path("f"), Path("a"), Path("out.mp4"))
        clip_paths = mock_assemble.call_args[0][0]
        assert clip_paths[0].name == "02.mp4"
        assert clip_paths[1].name == "01.mp4"
        assert clip_paths[2].name == "00.mp4"
