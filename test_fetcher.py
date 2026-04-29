import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from parser import SongInput
from fetcher import fetch_all, SongMetadata

@patch("fetcher.search_itunes")
@patch("fetcher.download_image")
@patch("fetcher.download_excerpt")
def test_fetch_all_success(mock_excerpt, mock_dl_img, mock_itunes, tmp_path):
    mock_itunes.return_value = {
        "collectionName": "Album X",
        "releaseDate": "1999-01-01T00:00:00Z",
        "primaryGenreName": "Rock",
        "artworkUrl100": "http://example.com/img.jpg"
    }
    mock_dl_img.side_effect = lambda url, dest: dest.write_bytes(b"fake")
    mock_excerpt.side_effect = lambda a,t,d: d.write_bytes(b"fake")

    songs = [SongInput(1, "Song A", "Artist B")]
    result = fetch_all(songs, tmp_path)
    assert len(result) == 1
    meta = result[0]
    assert meta.album == "Album X"
    assert meta.year == "1999"
    assert meta.genre == "Rock"
    assert Path(meta.cover_path).exists()
    assert Path(meta.excerpt_path).exists()

@patch("fetcher.search_itunes", side_effect=Exception("API down"))
@patch("fetcher.create_placeholder_cover")
@patch("fetcher.download_excerpt", side_effect=Exception("no audio"))
@patch("fetcher.generate_silent_audio")
def test_fallback_placeholders(mock_silent, mock_excerpt, mock_placeholder_cover, mock_itunes, tmp_path):
    songs = [SongInput(2, "Test", "Test")]
    result = fetch_all(songs, tmp_path)
    meta = result[0]
    assert meta.album == "N/A"
    assert meta.cover_path  # placeholder created
    assert meta.excerpt_path  # silent audio
    mock_placeholder_cover.assert_called_once()
    mock_silent.assert_called_once()