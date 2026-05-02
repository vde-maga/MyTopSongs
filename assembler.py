# assembler.py
import logging
import shutil
import subprocess
from pathlib import Path

from fetcher import SongMetadata

logger = logging.getLogger(__name__)


def _validate_inputs(
    metadatas: list[SongMetadata],
    frames_dir: Path,
    audio_dir: Path,
) -> None:
    """Validate that all required frame and audio files exist."""
    if not metadatas:
        raise ValueError("No songs to process")
    for meta in metadatas:
        frame = frames_dir / f"{meta.position:02d}.png"
        audio = audio_dir / f"{meta.position:02d}.mp3"
        if not frame.exists():
            raise FileNotFoundError(f"Frame not found: {frame}")
        if not audio.exists():
            raise FileNotFoundError(f"Audio not found: {audio}")


def _create_clip(
    frame: Path,
    audio: Path,
    output: Path,
    clip_duration: float,
) -> None:
    """Create a single video clip from a static frame and audio via ffmpeg."""
    cmd: list[str] = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(frame),
        "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-t", str(clip_duration),
        str(output),
    ]
    logger.info("Creating clip %s", output.name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create clip {output.name}:\n{result.stderr}"
        )


def _build_filter_complex(
    n: int,
    clip_duration: float,
    transition_duration: float,
) -> str:
    """
    Build the ffmpeg filter_complex string for xfade (video)
    and acrossfade (audio) transitions.
    Pure function — easy to test.
    """
    v_filters: list[str] = []
    v_last = "0:v"
    for i in range(1, n):
        label = f"v{i}"
        offset = clip_duration * i - transition_duration * i
        v_filters.append(
            f"[{v_last}][{i}:v]xfade=transition=fade"
            f":duration={transition_duration}:offset={offset}[{label}]"
        )
        v_last = label

    a_filters: list[str] = []
    a_last = "0:a"
    for i in range(1, n):
        out_label = "a_out" if i == n - 1 else f"a{i}"
        a_filters.append(
            f"[{a_last}][{i}:a]acrossfade=d={transition_duration}"
            f":c1=tri:c2=tri[{out_label}]"
        )
        a_last = out_label

    return ";".join(v_filters + a_filters)


def _run_final_assembly(
    clip_paths: list[Path],
    filter_complex: str,
    video_label: str,
    output_file: Path,
) -> None:
    """Run ffmpeg to assemble clips with transitions into the final video."""
    inputs: list[str] = []
    for p in clip_paths:
        inputs.extend(["-i", str(p)])

    cmd: list[str] = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{video_label}]",
        "-map", "[a_out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_file),
    ]
    logger.info("Assembling final video with transitions")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to assemble video:\n{result.stderr}"
        )
    logger.info("Video successfully assembled: %s", output_file)


def assemble_video(
    metadatas: list[SongMetadata],
    frames_dir: Path,
    audio_dir: Path,
    output_file: Path,
    clip_duration: float = 15.0,
    transition_duration: float = 1.0,
) -> None:
    """
    Create individual clips (frame + audio) using ffmpeg, then concatenate
    with xfade transitions for video and acrossfade for audio.
    Clips are assembled in REVERSE order (last song first).
    """
    # Reverse order: last position appears first in the video
    ordered_metadatas = list(reversed(metadatas))

    _validate_inputs(ordered_metadatas, frames_dir, audio_dir)

    clips_dir = Path("./tmp/clips")
    clips_dir.mkdir(parents=True, exist_ok=True)

    n = len(ordered_metadatas)

    clip_paths: list[Path] = []
    for meta in ordered_metadatas:
        idx = meta.position
        frame = frames_dir / f"{idx:02d}.png"
        audio = audio_dir / f"{idx:02d}.mp3"
        clip = clips_dir / f"{idx:02d}.mp4"
        _create_clip(frame, audio, clip, clip_duration)
        clip_paths.append(clip)

    if n == 1:
        shutil.copy2(clip_paths[0], output_file)
        logger.info("Single clip video saved to %s", output_file)
        return

    filter_complex = _build_filter_complex(n, clip_duration, transition_duration)
    video_label = f"v{n - 1}"
    _run_final_assembly(clip_paths, filter_complex, video_label, output_file)
