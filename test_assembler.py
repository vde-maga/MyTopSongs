import subprocess
from unittest.mock import patch, call
from assembler import assemble_video
from fetcher import SongMetadata
from pathlib import Path

@patch("subprocess.run")
def test_assemble_single_song(mock_run, tmp_path):
    meta = [SongMetadata(position=1, title="A", artist="B",
                        cover_path="c.png", excerpt_path="a.mp3")]
    frames_dir = tmp_path / "frames"
    audio_dir = tmp_path / "audio"
    # create dummy files needed for ffmpeg (they won't be run, just paths)
    (frames_dir / "01.png").touch()
    (audio_dir / "01.mp3").touch()
    output = tmp_path / "out.mp4"
    with patch("assembler.Path.mkdir"):  # avoid real dirs
        with patch("assembler.Path.touch"):
            assemble_video(meta, frames_dir, audio_dir, output)
    # check that ffmpeg was called to create clip and copy
    assert mock_run.call_count == 2  # one for clip creation, one for cp
    # check clip command
    clip_call_args = mock_run.call_args_list[0][0][0]
    assert "ffmpeg" in clip_call_args
    assert "-loop" in clip_call_args