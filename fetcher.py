import subprocess
from pathlib import Path
from typing import List
from fetcher import SongMetadata
import logging

logger = logging.getLogger(__name__)

def assemble_video(metadatas: List[SongMetadata], frames_dir: Path, audio_dir: Path,
                   output_file: Path, clip_duration: float = 15.0, transition_duration: float = 1.0):
    """
    Create individual clips (frame + audio) using ffmpeg, then concatenate
    with xfade transitions for video and acrossfade for audio.
    """
    clips_dir = Path("./tmp/clips")
    clips_dir.mkdir(parents=True, exist_ok=True)
    
    n = len(metadatas)
    if n == 0:
        raise ValueError("No songs to process")
    
    # Generate intermediate clips (video+audio) for each song
    clip_paths = []
    for meta in metadatas:
        idx = meta.position
        frame = frames_dir / f"{idx:02d}.png"
        audio = audio_dir / f"{idx:02d}.mp3"
        clip = clips_dir / f"{idx:02d}.mp4"
        
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(frame),
            "-i", str(audio),
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-t", str(clip_duration),
            str(clip)
        ]
        logger.info(f"Creating clip for position {idx}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to create clip {idx}: {result.stderr}")
        clip_paths.append(clip)

    if n == 1:
        # Just copy the single clip
        subprocess.run(["cp", str(clip_paths[0]), str(output_file)], check=True)
        logger.info(f"Single clip video saved to {output_file}")
        return

    # Build FFmpeg command with complex filter for xfade + acrossfade
    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", str(p)])
    
    # Build video xfade filter chain
    v_filters = []
    v_last = "0:v"
    
    for i in range(1, n):
        label = f"v{i}"
        offset = (clip_duration * i) - (transition_duration * i)
        v_filters.append(f"[{v_last}][{i}:v]xfade=transition=fade:duration={transition_duration}:offset={offset}[{label}]")
        v_last = label
    
    # Build audio acrossfade filter chain
    a_filters = []
    a_last = "0:a"
    
    for i in range(1, n):
        label = f"a{i}"
        a_filters.append(f"[{a_last}][{i}:a]acrossfade=d={transition_duration}:c1=tri:c2=tri[{label}]")
        a_last = f"a{i}" if i < n - 1 else "a_out"
    
    # Rename last audio output
    if n > 1:
        a_filters[-1] = a_filters[-1].replace(f"[a{n-1}]", "[a_out]")
    
    # Combine all filters
    all_filters = v_filters + a_filters
    filter_complex = ";".join(all_filters)
    
    # Build final command
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{v_last}]",
        "-map", "[a_out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_file)
    ]
    
    logger.info("Assembling final video with transitions")
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Failed to assemble video: {result.stderr}")
    else:
        logger.info(f"Video successfully assembled: {output_file}")