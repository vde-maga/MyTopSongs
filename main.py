#!/usr/bin/env python3
import sys
import logging
import argparse
from pathlib import Path

from dotenv import load_dotenv
from parser import parse_songs
from fetcher import fetch_all, ApiKeyError
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


def main(input_file: str = "input.txt", output_video: str = "output.mp4", interactive: bool = True):
    check_dependencies()
    load_dotenv()

    input_path = Path(input_file)
    logger.info(f"Parsing {input_path}")
    songs = parse_songs(input_path)
    logger.info(f"Parsed {len(songs)} songs.")

    tmp_dir = Path("./tmp")
    tmp_dir.mkdir(exist_ok=True)

    logger.info("Fetching metadata, covers, and audio excerpts...")
    try:
        metadatas = fetch_all(songs, tmp_dir, interactive=interactive)
    except ApiKeyError as e:
        logger.critical(f"Configuration error: {e}")
        sys.exit(1)

    logger.info("Rendering frames...")
    render_frames(metadatas, tmp_dir / "frames")

    logger.info("Assembling video with transitions...")
    assemble_video(metadatas, tmp_dir / "frames", tmp_dir / "audio", Path(output_video))

    logger.info(f"Video successfully saved to {output_video}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cria um vídeo com o top de músicas.")
    parser.add_argument("-i", "--input", default="input.txt", help="Ficheiro de entrada (default: input.txt)")
    parser.add_argument("-o", "--output", default="output.mp4", help="Ficheiro de saída (default: output.mp4)")
    parser.add_argument("--no-interactive", action="store_true", help="Desativa prompts interativos para capas/metadata")
    args = parser.parse_args()

    main(input_file=args.input, output_video=args.output, interactive=not args.no_interactive)
