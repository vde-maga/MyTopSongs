import logging
import subprocess
import sys
import requests
from pathlib import Path
from typing import List
from dataclasses import dataclass
from parser import SongInput
from urllib.parse import quote

logger = logging.getLogger(__name__)

@dataclass
class SongMetadata:
    position: int
    title: str
    artist: str
    album: str = "N/A"
    year: str = "N/A"
    genre: str = "N/A"
    rym_rating: str = "N/A"
    aoty_rating: str = "N/A"
    cover_path: str = ""
    excerpt_path: str = ""

def fetch_all(songs: List[SongInput], output_dir: Path) -> List[SongMetadata]:
    """
    Enrich songs with metadata, download covers (to output_dir/covers/) and
    audio excerpts (to output_dir/audio/). Return populated SongMetadata list.
    Critical failures (cover/excerpt) are handled by placeholder generation.
    """
    covers_dir = output_dir / "covers"
    audio_dir = output_dir / "audio"
    covers_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for song in songs:
        logger.info(f"Processing #{song.position}: {song.artist} - {song.title}")
        meta = SongMetadata(position=song.position, title=song.title, artist=song.artist)

        # Attempt to get metadata from iTunes Search API
        try:
            itunes_data = search_itunes(song.artist, song.title)
            meta.album = itunes_data.get("collectionName", "N/A")
            meta.year = itunes_data.get("releaseDate", "N/A")[:4]  # year only
            meta.genre = itunes_data.get("primaryGenreName", "N/A")
            artwork_url = itunes_data.get("artworkUrl100", "").replace("100x100", "600x600")
        except Exception as e:
            logger.warning(f"iTunes search failed for {song.artist} - {song.title}: {e}")
            artwork_url = None

        # Download cover
        cover_file = covers_dir / f"{song.position:02d}.png"
        if artwork_url:
            try:
                download_image(artwork_url, cover_file)
                meta.cover_path = str(cover_file)
            except Exception as e:
                logger.error(f"Cover download failed, using placeholder: {e}")
        if not meta.cover_path:
            create_placeholder_cover(cover_file)
            meta.cover_path = str(cover_file)

        # Download audio excerpt via yt-dlp
        excerpt_file = audio_dir / f"{song.position:02d}.mp3"
        try:
            download_excerpt(song.artist, song.title, excerpt_file)
            meta.excerpt_path = str(excerpt_file)
        except Exception as e:
            logger.error(f"Audio excerpt failed, using silent placeholder: {e}")
            generate_silent_audio(excerpt_file, duration=15)
            meta.excerpt_path = str(excerpt_file)

        # RYM/AOTY ratings: not implemented, keeping N/A
        results.append(meta)

    return results

def search_itunes(artist: str, title: str) -> dict:
    """Query iTunes Search API for track metadata."""
    term = f"{artist} {title}"
    url = f"https://itunes.apple.com/search?term={quote(term)}&limit=1"
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("resultCount", 0) > 0:
        return data["results"][0]
    raise ValueError("No results found")

def download_image(url: str, dest: Path):
    """Download an image from URL and save as PNG."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    dest.write_bytes(resp.content)

def create_placeholder_cover(dest: Path):
    """Generate a black 600x600 PNG placeholder."""
    from PIL import Image
    img = Image.new("RGB", (600, 600), color="black")
    img.save(dest)

def download_excerpt(artist: str, title: str, dest: Path):
    """
    Use yt-dlp to download first 15 seconds of official YouTube video.
    Output is MP3.
    """
    query = f"{artist} {title} official audio"
    yt_dlp_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--postprocessor-args", "ffmpeg:-t 15",
        "-o", str(dest),
        f"ytsearch1:{query}"
    ]
    subprocess.run(yt_dlp_cmd, check=True, capture_output=True, text=True)

def generate_silent_audio(dest: Path, duration: int = 15):
    """
    Generate a silent MP3 file of specified duration using ffmpeg.
    """
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",
        str(dest)
    ]
    subprocess.run(cmd, check=True, capture_output=True)