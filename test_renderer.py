from renderer import create_frame
from fetcher import SongMetadata
from pathlib import Path
from PIL import Image

def test_create_frame(tmp_path):
    meta = SongMetadata(
        position=1, title="Test", artist="Artist",
        album="Album", year="2000", genre="Rock",
        rym_rating="4.00", aoty_rating="85",
        cover_path=str(tmp_path / "test.png")
    )
    # create a dummy cover
    dummy = Image.new("RGB", (400,400), color="red")
    dummy.save(meta.cover_path)

    img = create_frame(meta)
    assert img.size == (1920, 1080)
    # save frame
    frame_path = tmp_path / "frame.png"
    img.save(frame_path)
    assert frame_path.exists()

def test_frame_without_cover(tmp_path):
    meta = SongMetadata(position=2, title="No Cover", artist="Someone", cover_path="")
    img = create_frame(meta)
    assert img.size == (1920, 1080)