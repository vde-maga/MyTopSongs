import logging
import subprocess
import sys
import requests
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from parser import SongInput
from urllib.parse import quote

logger = logging.getLogger(__name__)

LASTFM_API_BASE = "http://ws.audioscrobbler.com/2.0/"
SIZE_PRIORITY = {"small": 1, "medium": 2, "large": 3, "extralarge": 4, "mega": 5}

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

def get_api_key() -> str:
    """Get Last.fm API key from environment variable, exit if not set."""
    key = os.environ.get("LASTFM_API_KEY")
    if not key:
        logger.critical("LASTFM_API_KEY environment variable not set.")
        sys.exit(1)
    return key

def fetch_all(songs: List[SongInput], output_dir: Path) -> List[SongMetadata]:
    """
    Enrich songs with metadata from Last.fm, download covers and audio excerpts.
    Fail-safe: generates placeholders for missing cover/audio.
    """
    covers_dir = output_dir / "covers"
    audio_dir = output_dir / "audio"
    covers_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    api_key = get_api_key()
    results = []
    
    for song in songs:
        logger.info(f"Processing #{song.position}: {song.artist} - {song.title}")
        meta = SongMetadata(position=song.position, title=song.title, artist=song.artist)
        
        # Attempt to get metadata from Last.fm
        try:
            track_data = get_track_info(song.artist, song.title, api_key)
            meta.album = track_data.get("album", "N/A")
            # Year not directly available in track.getInfo; we keep N/A
            meta.genre = track_data.get("genre", "N/A")
            cover_url = track_data.get("cover_url")
        except Exception as e:
            logger.warning(f"Last.fm track.getInfo failed for {song.artist} - {song.title}: {e}")
            cover_url = None
        
        # Download cover
        cover_file = covers_dir / f"{song.position:02d}.png"
        if cover_url:
            try:
                download_image(cover_url, cover_file)
                meta.cover_path = str(cover_file)
            except Exception as e:
                logger.error(f"Cover download failed, using placeholder: {e}")
        if not meta.cover_path:
            create_placeholder_cover(cover_file)
            meta.cover_path = str(cover_file)
        
        # Download audio excerpt (unchanged)
        excerpt_file = audio_dir / f"{song.position:02d}.mp3"
        try:
            download_excerpt(song.artist, song.title, excerpt_file)
            meta.excerpt_path = str(excerpt_file)
        except Exception as e:
            logger.error(f"Audio excerpt failed, using silent placeholder: {e}")
            generate_silent_audio(excerpt_file, duration=15)
            meta.excerpt_path = str(excerpt_file)
        
        results.append(meta)
    
    return results

def get_track_info(artist: str, track: str, api_key: str) -> Dict[str, str]:
    """
    Query Last.fm track.getInfo and extract relevant metadata.
    Returns dict with keys 'album', 'genre', 'cover_url'.
    Raises exception on API error or missing track.
    """
    params = {
        "method": "track.getInfo",
        "api_key": api_key,
        "artist": artist,
        "track": track,
        "autocorrect": "1",
        "format": "json"
    }
    resp = requests.get(LASTFM_API_BASE, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    
    if "error" in data:
        error_code = data["error"]
        message = data.get("message", "Unknown error")
        raise ValueError(f"Last.fm API error {error_code}: {message}")
    
    track_obj = data.get("track")
    if not track_obj:
        raise ValueError("No track data in response")
    
    # Album info
    album = "N/A"
    if "album" in track_obj:
        album = track_obj["album"].get("title", "N/A")
    
    # Genre from top tags (first tag)
    genre = "N/A"
    toptags = track_obj.get("toptags", {}).get("tag", [])
    if isinstance(toptags, list) and len(toptags) > 0:
        genre = toptags[0].get("name", "N/A")
    elif isinstance(toptags, dict):  # single tag returned as dict
        genre = toptags.get("name", "N/A")
    
    # Cover image (largest available)
    cover_url = None
    images = track_obj.get("album", {}).get("image", [])
    if images:
        # Sort by size priority and pick the one with highest priority URL
        best_image = max(images, key=lambda img: SIZE_PRIORITY.get(img.get("size", ""), 0))
        cover_url = best_image.get("#text")
    
    return {
        "album": album,
        "genre": genre,
        "cover_url": cover_url
    }

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
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--postprocessor-args", "ffmpeg:-t 15",
        "-o", str(dest),
        f"ytsearch1:{query}"
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

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
