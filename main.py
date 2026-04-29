#!/usr/bin/env python3
import sys
import logging
from pathlib import Path
from parser import parse_songs
from fetcher import fetch_all
from renderer import render_frames
from assembler import assemble_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

def check_dependencies():
    import shutil
    for tool in ["ffmpeg", "yt-dlp"]:
        if shutil.which(tool) is None:
            logger.critical(f"{tool} not found in PATH. Please install it before running.")
            sys.exit(1)

def main(input_file: str = "input.txt", output_video: str = "output.mp4"):
    check_dependencies()
    input_path = Path(input_file)
    logger.info(f"Parsing {input_path}")
    songs = parse_songs(input_path)
    logger.info(f"Parsed {len(songs)} songs.")

    tmp_dir = Path("./tmp")
    tmp_dir.mkdir(exist_ok=True)

    logger.info("Fetching metadata, covers, and audio excerpts...")
    metadatas = fetch_all(songs, tmp_dir)

    logger.info("Rendering frames...")
    frames_dir = tmp_dir / "frames"
    render_frames(metadatas, frames_dir)

    audio_dir = tmp_dir / "audio"
    logger.info("Assembling video with transitions...")
    assemble_video(metadatas, frames_dir, audio_dir, Path(output_video))

    logger.info(f"Video successfully saved to {output_video}")

if __name__ == "__main__":
    main()