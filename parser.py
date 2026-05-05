import re
import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class SongInput:
    position: int
    title: str
    artist: str
    comment: Optional[str] = None

LINE_RE = re.compile(r'^(\d+)\.\s+(.+?)\s+-\s+(.+?)(?:\s+-\s+(.+))?$')

def parse_songs(filepath: Path) -> List[SongInput]:
    """Parse the input file and return validated SongInput list. Exit on any error."""
    if not filepath.exists():
        sys.exit(f"ERROR: Input file not found: {filepath}")

    songs = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for i, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            match = LINE_RE.match(line)
            if not match:
                print(f"ERROR: Line {i} does not match required format: '{line}'")
                sys.exit(1)
            position = int(match.group(1))
            title = match.group(2).strip()
            artist = match.group(3).strip()
            comment = match.group(4).strip() if match.group(4) else None
            songs.append(SongInput(position=position, title=title, artist=artist, comment=comment))

    return songs
