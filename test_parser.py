import pytest
from pathlib import Path
from parser import parse_songs, SongInput

def test_parse_valid_file(tmp_path):
    content = "\n".join([
        "1. Bohemian Rhapsody - Queen",
        "2. Imagine - John Lennon",
        "   ",  # blank line
        "3. Hotel California - Eagles"
    ])
    file = tmp_path / "input.txt"
    file.write_text(content)
    songs = parse_songs(file)
    assert len(songs) == 3
    assert songs[0] == SongInput(1, "Bohemian Rhapsody", "Queen")
    assert songs[2].artist == "Eagles"

def test_missing_file_exits():
    with pytest.raises(SystemExit):
        parse_songs(Path("nonexistent.txt"))

def test_invalid_line_format(tmp_path):
    file = tmp_path / "bad.txt"
    file.write_text("no dash here\n1. Ok - Artist")
    with pytest.raises(SystemExit):
        parse_songs(file)