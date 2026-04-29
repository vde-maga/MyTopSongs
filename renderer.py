from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import List
from fetcher import SongMetadata

FONT_TITLE = None  # will load default or fallback
FONT_MAIN = None

def load_fonts():
    global FONT_TITLE, FONT_MAIN
    try:
        FONT_TITLE = ImageFont.truetype("Arial Bold.ttf", 72)
        FONT_MAIN = ImageFont.truetype("Arial.ttf", 48)
    except OSError:
        FONT_TITLE = ImageFont.load_default()
        FONT_MAIN = ImageFont.load_default()

def render_frames(metadatas: List[SongMetadata], frames_dir: Path):
    """
    Generate one 1920x1080 frame per song and save in frames_dir.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    load_fonts()

    for meta in metadatas:
        img = create_frame(meta)
        frame_file = frames_dir / f"{meta.position:02d}.png"
        img.save(frame_file)

def create_frame(meta: SongMetadata) -> Image.Image:
    # Background
    background = Image.new("RGB", (1920, 1080), color=(30, 30, 30))
    # Try to load album cover for blurred background
    try:
        if meta.cover_path and Path(meta.cover_path).exists():
            cover = Image.open(meta.cover_path).convert("RGB")
            # resize to fill and blur
            cover = cover.resize((1920, 1080), Image.Resampling.LANCZOS)
            cover = cover.filter(ImageFilter.GaussianBlur(radius=30))
            background.paste(cover)
    except Exception:
        pass  # keep dark background

    # Left side: album cover
    cover_rect_size = 800
    cover_img = Image.new("RGB", (cover_rect_size, cover_rect_size), color="black")
    try:
        if meta.cover_path and Path(meta.cover_path).exists():
            src = Image.open(meta.cover_path).convert("RGB")
            src = src.resize((cover_rect_size, cover_rect_size), Image.Resampling.LANCZOS)
            cover_img = src
    except Exception:
        pass
    cover_pos = (60, 140)  # vertical center roughly
    background.paste(cover_img, cover_pos)

    # Right side: text
    draw = ImageDraw.Draw(background)
    x_text = 920
    y = 200

    # Position number
    draw.text((x_text, y), f"#{meta.position:02d}", fill="white", font=FONT_TITLE)
    # Title (yellow)
    draw.text((x_text, y+100), meta.title, fill="yellow", font=FONT_TITLE)
    # Artist
    draw.text((x_text, y+200), meta.artist, fill="white", font=FONT_MAIN)
    # Year | Genre | Album
    info_line = f"{meta.year} | {meta.genre} | {meta.album}"
    draw.text((x_text, y+280), info_line, fill="gray", font=FONT_MAIN)
    # Ratings
    rating_line = f"RYM: {meta.rym_rating} | AOTY: {meta.aoty_rating}"
    draw.text((x_text, y+340), rating_line, fill="white", font=FONT_MAIN)

    return background