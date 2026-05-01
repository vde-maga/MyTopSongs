"""Testes unitários para o módulo renderer."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from renderer import (
    FontNotFoundError,
    _create_background,
    _create_thumbnail,
    _load_cover_image,
    create_frame,
    draw_text_with_shadow,
    load_font,
    render_frames,
    resolve_font_path,
)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
@dataclass
class FakeSongMetadata:
    """Substituto leve de SongMetadata para testes."""

    position: int
    title: str
    artist: str
    year: str
    genre: str
    album: str
    cover_path: Optional[str] = None
    rym_rating: str = "N/A"
    aoty_rating: str = "N/A"


def _mock_font() -> MagicMock:
    return MagicMock(spec=ImageFont.FreeTypeFont)


# ---------------------------------------------------------------------------
# resolve_font_path
# ---------------------------------------------------------------------------
class TestResolveFontPath:
    def test_env_var_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        font_file = tmp_path / "custom.ttf"
        font_file.write_bytes(b"fake")
        monkeypatch.setenv("FONT_PATH", str(font_file))

        assert resolve_font_path() == font_file

    def test_env_var_invalid_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FONT_PATH", str(tmp_path / "missing.ttf"))

        with pytest.raises(FontNotFoundError, match="FONT_PATH"):
            resolve_font_path()

    def test_default_path_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FONT_PATH", raising=False)
        fonts_dir = tmp_path / "fonts"
        fonts_dir.mkdir()
        font_file = fonts_dir / "font.ttf"
        font_file.write_bytes(b"fake")

        with patch("renderer.FONTS_DIR", fonts_dir):
            assert resolve_font_path() == font_file

    def test_no_font_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FONT_PATH", raising=False)

        with patch("renderer.FONTS_DIR", tmp_path / "missing"):
            with pytest.raises(FontNotFoundError, match="Coloque um ficheiro"):
                resolve_font_path()


# ---------------------------------------------------------------------------
# load_font
# ---------------------------------------------------------------------------
class TestLoadFont:
    def test_invalid_path_raises(self):
        with pytest.raises(FontNotFoundError, match="Falha ao carregar"):
            load_font(96, Path("/nao/existe.ttf"))

    def test_valid_path_returns_font(self):
        mock = _mock_font()
        with patch("renderer.ImageFont.truetype", return_value=mock):
            result = load_font(96, Path("qualquer.ttf"))
        assert result is mock


# ---------------------------------------------------------------------------
# _load_cover_image
# ---------------------------------------------------------------------------
class TestLoadCoverImage:
    def test_none_returns_none(self):
        assert _load_cover_image(None) is None

    def test_empty_returns_none(self):
        assert _load_cover_image("") is None

    def test_missing_file_returns_none(self):
        assert _load_cover_image("/nao/existe.jpg") is None

    def test_corrupt_file_returns_none(self, tmp_path: Path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"isto nao e uma imagem")
        assert _load_cover_image(str(bad)) is None

    def test_valid_image_returns_rgb(self, tmp_path: Path):
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        path = tmp_path / "cover.png"
        img.save(path)

        result = _load_cover_image(str(path))
        assert result is not None
        assert result.mode == "RGB"
        assert result.size == (100, 100)


# ---------------------------------------------------------------------------
# _create_background
# ---------------------------------------------------------------------------
class TestCreateBackground:
    def test_no_cover_dark_fallback(self):
        bg = _create_background(None)
        assert bg.size == (1920, 1080)
        assert bg.getpixel((0, 0)) == (30, 30, 30)

    def test_with_cover_is_blurred(self):
        cover = Image.new("RGB", (500, 500), (100, 150, 200))
        bg = _create_background(cover)
        assert bg.size == (1920, 1080)
        # O pixel central deve ter cor (não será preto puro)
        pixel = bg.getpixel((960, 540))
        assert all(0 <= c <= 255 for c in pixel)


# ---------------------------------------------------------------------------
# _create_thumbnail
# ---------------------------------------------------------------------------
class TestCreateThumbnail:
    def test_no_cover_black_placeholder(self):
        thumb = _create_thumbnail(None)
        assert thumb.size == (800, 800)
        assert thumb.getpixel((0, 0)) == (0, 0, 0)

    def test_with_cover_resized(self):
        cover = Image.new("RGB", (500, 500), (255, 0, 0))
        thumb = _create_thumbnail(cover)
        assert thumb.size == (800, 800)


# ---------------------------------------------------------------------------
# draw_text_with_shadow
# ---------------------------------------------------------------------------
class TestDrawTextWithShadow:
    def test_calls_draw_text_twice_with_correct_args(self):
        draw = MagicMock()
        font = _mock_font()

        draw_text_with_shadow(
            draw, (10, 20), "Olá", font, (255, 255, 255)
        )

        assert draw.text.call_count == 2
        # Sombra
        draw.text.assert_any_call(
            (13, 23), "Olá", font=font, fill=(0, 0, 0)
        )
        # Texto principal
        draw.text.assert_any_call(
            (10, 20), "Olá", font=font, fill=(255, 255, 255)
        )

    def test_custom_shadow_offset(self):
        draw = MagicMock()
        font = _mock_font()

        draw_text_with_shadow(
            draw, (5, 5), "X", font, (0, 0, 0),
            shadow_offset=(10, 10),
        )

        draw.text.assert_any_call(
            (15, 15), "X", font=font, fill=(0, 0, 0)
        )


# ---------------------------------------------------------------------------
# create_frame
# ---------------------------------------------------------------------------
class TestCreateFrame:
    def test_creates_png_file(self, tmp_path: Path):
        meta = FakeSongMetadata(
            position=1, title="Música", artist="Artista",
            year="2024", genre="Rock", album="Álbum",
        )
        output = tmp_path / "01.png"

        with patch("renderer.ImageFont.truetype", return_value=_mock_font()):
            create_frame(meta, output, Path("fake.ttf"))

        assert output.is_file()

    def test_creates_parent_directory(self, tmp_path: Path):
        meta = FakeSongMetadata(
            position=1, title="Música", artist="Artista",
            year="2024", genre="Rock", album="Álbum",
        )
        output = tmp_path / "sub" / "dir" / "01.png"

        with patch("renderer.ImageFont.truetype", return_value=_mock_font()):
            create_frame(meta, output, Path("fake.ttf"))

        assert output.is_file()

    def test_with_cover_image(self, tmp_path: Path):
        cover = Image.new("RGB", (200, 200), (0, 128, 255))
        cover_path = tmp_path / "cover.png"
        cover.save(cover_path)

        meta = FakeSongMetadata(
            position=3, title="Тест", artist="Тест",
            year="2024", genre="Pop", album="Тест",
            cover_path=str(cover_path),
        )
        output = tmp_path / "03.png"

        with patch("renderer.ImageFont.truetype", return_value=_mock_font()):
            create_frame(meta, output, Path("fake.ttf"))

        assert output.is_file()
        result = Image.open(output)
        assert result.size == (1920, 1080)


# ---------------------------------------------------------------------------
# render_frames
# ---------------------------------------------------------------------------
class TestRenderFrames:
    def test_creates_all_frames(self, tmp_path: Path):
        metas = [
            FakeSongMetadata(position=i, title=f"S{i}", artist=f"A{i}",
                             year="2024", genre="Rock", album=f"Alb{i}")
            for i in range(1, 4)
        ]
        frames_dir = tmp_path / "frames"

        with patch("renderer.resolve_font_path", return_value=Path("f.ttf")), \
             patch("renderer.ImageFont.truetype", return_value=_mock_font()):
            render_frames(metas, frames_dir)

        assert (frames_dir / "01.png").is_file()
        assert (frames_dir / "02.png").is_file()
        assert (frames_dir / "03.png").is_file()

    def test_raises_when_no_font(self, tmp_path: Path):
        metas = [FakeSongMetadata(
            position=1, title="S", artist="A",
            year="2024", genre="G", album="B"
        )]

        with patch("renderer.resolve_font_path",
                    side_effect=FontNotFoundError("Sem fonte")):
            with pytest.raises(FontNotFoundError):
                render_frames(metas, tmp_path / "frames")

    def test_empty_list_no_error(self, tmp_path: Path):
        with patch("renderer.resolve_font_path", return_value=Path("f.ttf")):
            render_frames([], tmp_path / "frames")

        # Apenas o diretório é criado, sem frames
        assert (tmp_path / "frames").is_dir()
        assert list((tmp_path / "frames").iterdir()) == []
