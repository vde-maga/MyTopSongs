"""
Metadata fetcher for the video creator pipeline.

Enriches song data from Last.fm and iTunes APIs,
downloads cover art and audio excerpts with fail-safe placeholders.
"""

import io
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

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
SUBPROCESS_TIMEOUT_SEC = 180  # Increased due to full audio download
SILENT_AUDIO_TIMEOUT_SEC = 30
MAX_API_RETRIES = 3
EXCERPT_DURATION_SEC = 15
MIN_SONG_DURATION_SEC = 30   # Filter out short clips/previews
MAX_SONG_DURATION_SEC = 600  # Filter out full DJ sets/mixes

# ── Exceptions ───────────────────────────────────────────────────────────

class ApiKeyError(Exception):
    """Required API key is missing from environment."""

class AudioValidationError(Exception):
    """Downloaded audio failed validation checks."""

# ── Data Model ───────────────────────────────────────────────────────────

@dataclass
class SongMetadata:
    """Enriched metadata for a single song."""
    position: int
    title: str
    artist: str
    comment: Optional[str] = None
    album: str = "N/A"
    year: str = "N/A"
    cover_path: str = ""
    excerpt_path: str = ""
    # Quality flags so consumers can tell what's real vs placeholder
    cover_is_placeholder: bool = False
    excerpt_is_placeholder: bool = False
    excerpt_start_sec: float = 0.0

# ── API Key ──────────────────────────────────────────────────────────────

def get_api_key(env_var: str = "LASTFM_API_KEY") -> str:
    """Retrieve an API key from an environment variable."""
    key = os.environ.get(env_var)
    if not key:
        raise ApiKeyError(f"{env_var} environment variable not set.")
    return key

# ── Last.fm Client ───────────────────────────────────────────────────────

class LastFmClient:
    """Encapsulates all Last.fm API calls with retry logic."""

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
        """Make a GET request with exponential backoff retry."""
        backoff_sec = 1
        for attempt in range(MAX_API_RETRIES):
            try:
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
            except requests.exceptions.RequestException as exc:
                if attempt < MAX_API_RETRIES - 1:
                    logger.warning(f"Last.fm request failed (attempt {attempt+1}), retrying in {backoff_sec}s: {exc}")
                    time.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    raise

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
                params={"term": f"{artist} {track}", "entity": "song", "limit": 5},
                timeout=REQUEST_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                # Try to find an exact or closer match rather than just the first result
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

def create_placeholder_cover(dest: Path, song_title: str = "?", song_artist: str = "?") -> None:
    """Generate a placeholder cover that clearly indicates it's a fallback."""
    img = Image.new("RGB", (600, 600), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    
    # Draw a visual indicator (X)
    draw.line([(150, 150), (450, 450)], fill=(80, 80, 80), width=6)
    draw.line([(450, 150), (150, 450)], fill=(80, 80, 80), width=6)
    
    # Attempt to load a decent font, fallback to default
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except (IOError, OSError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Add song info
    draw.text((300, 320), f"{song_artist}\n{song_title}", fill=(140, 140, 140), anchor="mm", font=font_large)
    draw.text((300, 560), "⚠ COVER NOT FOUND", fill=(200, 60, 60), anchor="mm", font=font_small)
    
    img.save(dest, format="PNG")

def generate_silent_audio(dest: Path, duration: int = 15) -> None:
    """Generate a silent MP3 file with metadata marking it as a placeholder."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-codec:a", "libmp3lame", "-qscale:a", "2",
        "-metadata", "title=PLACEHOLDER - AUDIO NOT FOUND",
        "-metadata", "artist=SYSTEM",
        str(dest),
    ]
    subprocess.run(cmd, capture_output=True, timeout=SILENT_AUDIO_TIMEOUT_SEC)

# ── Audio Analysis & Download ────────────────────────────────────────────

def _get_audio_duration(file_path: Path) -> float:
    """Get the duration of an audio file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise AudioValidationError("Could not determine audio duration.")

def find_best_moment(audio_path: Path, window_sec: int = EXCERPT_DURATION_SEC) -> float:
    """Find the most energetic window of `window_sec` seconds.
    
    Tries to use librosa for RMS energy analysis. If librosa is not installed,
    falls back to a simple midpoint heuristic (40% mark of the song).
    """
    try:
        import librosa
        import numpy as np
        
        logger.info(f"Analyzing audio for best moment with librosa: {audio_path.name}")
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        
        frame_length = int(sr * window_sec)
        hop_length = int(sr * 1)  # 1-second hop
        
        if len(y) <= frame_length:
            return 0.0
        
        # Sliding window RMS
        energy = np.array([
            np.sqrt(np.mean(y[i:i + frame_length] ** 2))
            for i in range(0, len(y) - frame_length, hop_length)
        ])
        
        # Bias towards the middle of the song (avoid intros/outros)
        n = len(energy)
        positions = np.arange(n) / n
        center_weight = np.exp(-0.5 * ((positions - 0.5) / 0.2) ** 2)
        
        scored = energy * center_weight
        best_idx = np.argmax(scored)
        
        start_sec = float(best_idx)
        logger.info(f"Best moment found at {start_sec:.1f}s (based on energy)")
        return start_sec

    except ImportError:
        logger.warning("librosa not installed. Falling back to midpoint heuristic for best moment.")
        duration = _get_audio_duration(audio_path)
        start = duration * 0.4  # 40% mark is usually a safe chorus bet
        logger.info(f"Using midpoint heuristic: starting at {start:.1f}s")
        return start

def download_excerpt(artist: str, title: str, dest: Path) -> None:
    """Download the best moment of a track as MP3 via yt-dlp."""
    query = f"{artist} {title} official audio"
    tmp_dest = dest.with_suffix(".tmp.mp3")
    
    try:
        # Step 1: Download full audio
        cmd_download = [
            "yt-dlp", "--no-playlist",
            "--extract-audio", "--audio-format", "mp3",
            "--force-overwrites",
            "-o", str(tmp_dest),
            f"ytsearch1:{query}",
        ]
        subprocess.run(cmd_download, check=True, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SEC)
        
        # Step 2: Validate downloaded audio
        duration = _get_audio_duration(tmp_dest)
        if duration < MIN_SONG_DURATION_SEC or duration > MAX_SONG_DURATION_SEC:
            raise AudioValidationError(
                f"Downloaded audio duration is {duration:.1f}s, "
                f"expected between {MIN_SONG_DURATION_SEC}s and {MAX_SONG_DURATION_SEC}s. "
                f"Possible wrong video downloaded."
            )
        
        # Step 3: Find the best moment
        start_sec = find_best_moment(tmp_dest, EXCERPT_DURATION_SEC)
        
        # Step 4: Extract just that window
        cmd_trim = [
            "ffmpeg", "-y", "-ss", str(start_sec),
            "-i", str(tmp_dest),
            "-t", str(EXCERPT_DURATION_SEC),
            "-c:a", "libmp3lame", "-qscale:a", "2",
            str(dest),
        ]
        subprocess.run(cmd_trim, check=True, capture_output=True, text=True, timeout=30)
        
    finally:
        # Cleanup temp file even if it fails
        if tmp_dest.exists():
            tmp_dest.unlink()

# ── Orchestrator ─────────────────────────────────────────────────────────

def fetch_all(
    songs: List[SongInput],
    output_dir: Path,
    lastfm_api_key: Optional[str] = None,
    *,
    interactive: bool = False,
    lastfm_client: Optional[LastFmClient] = None,
    itunes_client: Optional[ItunesClient] = None,
) -> List[SongMetadata]:
    """Enrich songs with metadata, covers, and audio excerpts.

    Data sources
    ------------
    Last.fm  -> album, cover art
    iTunes   -> year

    Fail-safe: placeholders are generated when downloads fail, and flags are set.
    If interactive=True, prompts the user for cover art when not found.
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
    failures_count = 0

    for song in songs:
        logger.info(f"Processing #{song.position}: {song.artist} - {song.title}")
        meta = SongMetadata(
            position=song.position,
            title=song.title,
            artist=song.artist,
            comment=song.comment,
        )

        cover_url = _enrich_metadata(meta, song, lastfm_client, itunes_client, interactive=interactive)
        _ensure_cover(meta, cover_url, song.position, covers_dir, interactive=interactive)
        _ensure_excerpt(meta, song.artist, song.title, song.position, audio_dir)

        if meta.cover_is_placeholder or meta.excerpt_is_placeholder:
            failures_count += 1

        results.append(meta)

    # Final UX report
    if failures_count > 0:
        logger.warning(
            f"⚠️ COMPLETED WITH ISSUES: {failures_count} out of {len(songs)} songs "
            f"have missing data (placeholders were used). Check logs above."
        )
    else:
        logger.info("✅ All songs processed successfully with real data.")

    _print_summary_table(results)

    return results


def _print_summary_table(results: List[SongMetadata]) -> None:
    """Print a user-friendly summary table of all processed songs."""
    if not results:
        print("No songs processed.")
        return

    print("\n" + "=" * 90)
    print("SUMMARY OF PROCESSED SONGS")
    print("=" * 90)

    # Header
    header = (
        f"{'Pos':<6} | {'Title':<25} | {'Artist':<18} | "
        f"{'Cover':<8} | {'Audio':<8} | {'Album':<15} | {'Year':<6}"
    )
    print(header)
    print("-" * 90)

    # Rows
    for meta in results:
        cover_status = "OK" if not meta.cover_is_placeholder else "PLCH"
        audio_status = "OK" if not meta.excerpt_is_placeholder else "PLCH"

        # Truncate long fields for display
        title = (meta.title[:22] + "...") if len(meta.title) > 25 else meta.title
        artist = (meta.artist[:15] + "...") if len(meta.artist) > 18 else meta.artist
        album = (meta.album[:12] + "...") if len(meta.album) > 15 else meta.album

        row = (
            f"{meta.position:02d}   | {title:<25} | {artist:<18} | "
            f"{cover_status:<8} | {audio_status:<8} | {album:<15} | {meta.year:<6}"
        )
        print(row)

    print("=" * 90)
    print("Legend: OK = Real data, PLCH = Placeholder used")
    print("=" * 90 + "\n")

def _enrich_metadata(
    meta: SongMetadata,
    song: SongInput,
    lastfm: LastFmClient,
    itunes: ItunesClient,
    interactive: bool = False,
) -> Optional[str]:
    """Populate *meta* from APIs."""
    cover_url: Optional[str] = None

    # ── Last.fm: album + cover ──
    try:
        track_data = lastfm.get_track_info(song.artist, song.title)
        meta.album = track_data.get("album") or "N/A"
        cover_url = track_data.get("cover_url")
    except Exception as exc:
        logger.warning(f"Last.fm track.getInfo failed for {song.artist} - {song.title}: {exc}")

    # ── Interactive Album Fallback ──
    if interactive and meta.album == "N/A":
        print(f"\n❌ Álbum não encontrado para: {meta.artist} - {meta.title}")
        user_input = input("👉 Insere o nome do álbum ou prime Enter para manter 'N/A': ").strip()
        if user_input:
            meta.album = user_input
            print("✅ Álbum atualizado!")

    # ── iTunes: year ──
    year = itunes.get_track_year(song.artist, song.title)
    if year:
        meta.year = year

    # ── Interactive Year Fallback ──
    if interactive and meta.year == "N/A":
        print(f"\n❌ Ano não encontrado para: {meta.artist} - {meta.title}")
        user_input = input("👉 Insere o ano ou prime Enter para manter 'N/A': ").strip()
        if user_input:
            meta.year = user_input
            print("✅ Ano atualizado!")

    return cover_url

def _ensure_cover(
    meta: SongMetadata,
    cover_url: Optional[str],
    position: int,
    covers_dir: Path,
    interactive: bool = False,
) -> None:
    """Download the cover image, ask user for input, or create a placeholder."""
    cover_file = covers_dir / f"{position:02d}.png"

    # ── 1. Try downloading from API ──
    if cover_url:
        try:
            download_image(cover_url, cover_file)
            meta.cover_path = str(cover_file)
            return
        except Exception as exc:
            logger.error(f"Cover download from API failed: {exc}")

    # ── 2. Interactive Fallback ──
    if interactive:
        print(f"\n❌ Capa não encontrada para: {meta.artist} - {meta.title}")
        user_input = input(
            "👉 Insere um URL, o caminho para um ficheiro local, "
            "ou prime Enter para gerar placeholder: "
        ).strip().strip("'\"")  # Remove quotes from copy-pasted paths

        if user_input:
            try:
                # Check if it's a URL
                if user_input.lower().startswith(("http://", "https://")):
                    download_image(user_input, cover_file)
                # Otherwise, treat as a local file path
                else:
                    local_path = Path(user_input).expanduser()  # Handles ~ (home dir)
                    if not local_path.is_file():
                        raise FileNotFoundError(f"Ficheiro não encontrado: {local_path}")
                    
                    # Open, normalize (remove alpha channel), and save as PNG
                    img = Image.open(local_path)
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGB")
                    img.save(cover_file, format="PNG")

                # If we reached here, the user's input was successful
                meta.cover_path = str(cover_file)
                print("✅ Capa aplicada com sucesso!")
                return

            except Exception as exc:
                logger.error(f"Falha ao usar o ficheiro/link fornecido: {exc}")
                print("⚠️ Não foi possível usar essa imagem. A gerar placeholder...")

    # ── 3. Default: Generate Placeholder ──
    create_placeholder_cover(cover_file, song_title=meta.title, song_artist=meta.artist)
    meta.cover_path = str(cover_file)
    meta.cover_is_placeholder = True

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
        logger.error(f"Audio excerpt failed, using silent placeholder: {exc}")
        generate_silent_audio(excerpt_file, duration=EXCERPT_DURATION_SEC)
        meta.excerpt_path = str(excerpt_file)
        meta.excerpt_is_placeholder = True
