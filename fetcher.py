"""
Metadata fetcher for the video creator pipeline.

Enriches song data from Last.fm and iTunes APIs,
downloads cover art and audio excerpts with fail-safe placeholders.
"""

import io
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
from PIL import Image

from parser import SongInput  # project-local parser module

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

LASTFM_API_BASE = "http://ws.audioscrobbler.com/2.0/"
ITUNES_API_BASE = "https://itunes.apple.com/search"

SIZE_PRIORITY: Dict[str, int] = {
    "small": 1,
    "medium": 2,
    "large": 3,
    "extralarge": 4,
    "mega": 5,
}

REQUEST_TIMEOUT_SEC = 10
SUBPROCESS_TIMEOUT_SEC = 120
SILENT_AUDIO_TIMEOUT_SEC = 30


# ── Exceptions ───────────────────────────────────────────────────────────

class ApiKeyError(Exception):
    """Required API key is missing from environment."""


# ── Data Model ───────────────────────────────────────────────────────────

@dataclass
class SongMetadata:
    """Enriched metadata for a single song."""
    position: int
    title: str
    artist: str
    album: str = "N/A"
    year: str = "N/A"
    cover_path: str = ""
    excerpt_path: str = ""


# ── API Key ──────────────────────────────────────────────────────────────

def get_api_key(env_var: str = "LASTFM_API_KEY") -> str:
    """Retrieve an API key from an environment variable."""
    key = os.environ.get(env_var)
    if not key:
        raise ApiKeyError(f"{env_var} environment variable not set.")
    return key


# ── Last.fm Client ───────────────────────────────────────────────────────

class LastFmClient:
    """Encapsulates all Last.fm API calls."""

    def __init__(self, api_key: str, base_url: str = LASTFM_API_BASE) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def get_track_info(
        self, artist: str, track: str
    ) -> Dict[str, Optional[str]]:
        """Fetch album name and cover URL via *track.getInfo*."""
        params = {
            "method": "track.getInfo",
            "api_key": self._api_key,
            "artist": artist,
            "track": track,
            "autocorrect": "1",
            "format": "json",
        }
        data = self._request(params)
        track_obj = data.get("track")
        if not track_obj:
            raise ValueError("No track data in Last.fm response")

        return {
            "album": self._extract_album(track_obj),
            "cover_url": self._extract_cover_url(track_obj),
        }

    # ── Private ──

    def _request(self, params: Dict[str, str]) -> Dict:
        resp = requests.get(
            self._base_url, params=params, timeout=REQUEST_TIMEOUT_SEC
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(
                f"Last.fm API error {data['error']}: "
                f"{data.get('message', 'Unknown')}"
            )
        return data

    @staticmethod
    def _extract_album(track_obj: Dict) -> str:
        album_obj = track_obj.get("album")
        if album_obj:
            return album_obj.get("title", "N/A")
        return "N/A"

    @staticmethod
    def _extract_cover_url(track_obj: Dict) -> Optional[str]:
        images = track_obj.get("album", {}).get("image", [])
        if not images:
            return None
        best = max(
            images,
            key=lambda img: SIZE_PRIORITY.get(img.get("size", ""), 0),
        )
        url = best.get("#text", "")
        return url if url else None


# ── iTunes Client (Year only) ────────────────────────────────────────────

class ItunesClient:
    """Fetches Year from the iTunes Search API (no auth)."""

    def __init__(self) -> None:
        self._session = requests.Session()

    def get_track_year(self, artist: str, track: str) -> Optional[str]:
        """Look up a track on iTunes and return its release year."""
        try:
            resp = self._session.get(
                ITUNES_API_BASE,
                params={"term": f"{artist} {track}", "entity": "song", "limit": 1},
                timeout=REQUEST_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                release_date = results[0].get("releaseDate", "")
                if release_date:
                    return release_date.split("-")[0]
        except Exception as exc:
            logger.warning(f"iTunes lookup failed for {artist} - {track}: {exc}")
        return None


# ── File Download Helpers ────────────────────────────────────────────────

def download_image(url: str, dest: Path) -> None:
    """Download an image from *url* and re-encode as PNG."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT_SEC)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(dest, format="PNG")


def create_placeholder_cover(dest: Path) -> None:
    """Generate a black 600×600 PNG placeholder."""
    img = Image.new("RGB", (600, 600), color="black")
    img.save(dest, format="PNG")


def download_excerpt(artist: str, title: str, dest: Path) -> None:
    """Download the first 15 s of a track as MP3 via yt-dlp."""
    query = f"{artist} {title} official audio"
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--postprocessor-args", "ffmpeg:-t 15",
        "-o", str(dest),
        f"ytsearch1:{query}",
    ]
    subprocess.run(cmd, check=True, timeout=SUBPROCESS_TIMEOUT_SEC)


def generate_silent_audio(dest: Path, duration: int = 15) -> None:
    """Generate a silent MP3 file of *duration* seconds using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",
        str(dest),
    ]
    subprocess.run(
        cmd, capture_output=True, timeout=SILENT_AUDIO_TIMEOUT_SEC
    )


# ── Orchestrator ─────────────────────────────────────────────────────────

def fetch_all(
    songs: List[SongInput],
    output_dir: Path,
    lastfm_api_key: Optional[str] = None,
    *,
    lastfm_client: Optional[LastFmClient] = None,
    itunes_client: Optional[ItunesClient] = None,
) -> List[SongMetadata]:
    """Enrich songs with metadata, covers, and audio excerpts.

    Data sources
    ------------
    Last.fm  -> album, cover art
    iTunes   -> year

    Fail-safe: placeholders are generated when downloads fail.
    """
    if not songs:
        return []

    covers_dir = output_dir / "covers"
    audio_dir = output_dir / "audio"
    covers_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    if lastfm_client is None:
        api_key = lastfm_api_key or get_api_key()
        lastfm_client = LastFmClient(api_key)

    if itunes_client is None:
        itunes_client = ItunesClient()

    results: List[SongMetadata] = []

    for song in songs:
        logger.info(
            f"Processing #{song.position}: {song.artist} - {song.title}"
        )
        meta = SongMetadata(
            position=song.position,
            title=song.title,
            artist=song.artist,
        )

        cover_url = _enrich_metadata(
            meta, song, lastfm_client, itunes_client
        )
        _ensure_cover(meta, cover_url, song.position, covers_dir)
        _ensure_excerpt(
            meta, song.artist, song.title, song.position, audio_dir
        )

        results.append(meta)

    return results


def _enrich_metadata(
    meta: SongMetadata,
    song: SongInput,
    lastfm: LastFmClient,
    itunes: ItunesClient,
) -> Optional[str]:
    """Populate *meta* from APIs."""
    cover_url: Optional[str] = None

    # ── Last.fm: album + cover ──
    try:
        track_data = lastfm.get_track_info(song.artist, song.title)
        meta.album = track_data.get("album") or "N/A"
        cover_url = track_data.get("cover_url")
    except Exception as exc:
        logger.warning(
            f"Last.fm track.getInfo failed for "
            f"{song.artist} - {song.title}: {exc}"
        )

    # ── iTunes: year ──
    year = itunes.get_track_year(song.artist, song.title)
    if year:
        meta.year = year

    return cover_url


def _ensure_cover(
    meta: SongMetadata,
    cover_url: Optional[str],
    position: int,
    covers_dir: Path,
) -> None:
    """Download the cover image or create a placeholder."""
    cover_file = covers_dir / f"{position:02d}.png"

    if cover_url:
        try:
            download_image(cover_url, cover_file)
            meta.cover_path = str(cover_file)
            return
        except Exception as exc:
            logger.error(f"Cover download failed, using placeholder: {exc}")

    create_placeholder_cover(cover_file)
    meta.cover_path = str(cover_file)


def _ensure_excerpt(
    meta: SongMetadata,
    artist: str,
    title: str,
    position: int,
    audio_dir: Path,
) -> None:
    """Download an audio excerpt or generate a silent placeholder."""
    excerpt_file = audio_dir / f"{position:02d}.mp3"

    try:
        download_excerpt(artist, title, excerpt_file)
        meta.excerpt_path = str(excerpt_file)
    except Exception as exc:
        logger.error(
            f"Audio excerpt failed, using silent placeholder: {exc}"
        )
        generate_silent_audio(excerpt_file, duration=15)
        meta.excerpt_path = str(excerpt_file)
