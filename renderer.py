"""Renderer – gera um frame 1920×1080 por música."""

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fetcher import SongMetadata

logger = logging.getLogger(__name__)

__all__ = ["render_frames", "create_frame", "FontNotFoundError"]


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
FONTS_DIR = Path("fonts")
DEFAULT_FONT_FILENAME = "font.ttf"
FONT_ENV_VAR = "FONT_PATH"

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# Tamanhos de fonte (escala 1080p)
TITLE_SIZE = 96
ARTIST_SIZE = 60
INFO_SIZE = 44
RATING_SIZE = 44

# Cores (R, G, B)
COLOR_POSITION = (255, 255, 255)
COLOR_TITLE = (255, 215, 0)
COLOR_ARTIST = (240, 240, 240)
COLOR_INFO = (190, 190, 190)
COLOR_RATING = (200, 200, 200)
COLOR_SHADOW = (0, 0, 0)
COLOR_BG_FALLBACK = (30, 30, 30)
COLOR_COVER_PLACEHOLDER = (0, 0, 0)

# Layout - Posições
COVER_SIZE = 800
COVER_POS = (80, 140)
TEXT_MARGIN_LEFT = 80
TEXT_START_Y = 180

# Layout - Espaçamentos verticais
SHADOW_OFFSET = (3, 3)
SPACING_AFTER_POSITION = 20
SPACING_AFTER_TITLE = 20
SPACING_AFTER_ARTIST = 40
SPACING_AFTER_INFO_LINE = 20
SPACING_BEFORE_RATINGS = 40


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------
class FontNotFoundError(FileNotFoundError):
    """O ficheiro .ttf/.ttc requerido não foi encontrado."""


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------
def resolve_font_path() -> Path:
    """Resolve o caminho para o ficheiro de fonte fornecido pelo utilizador.

    Ordem de procura:
      1. Variável de ambiente ``FONT_PATH``.
      2. ``fonts/font.ttf`` ou ``fonts/font.ttc`` na raiz do projeto.

    Raises:
        FontNotFoundError: Nenhum ficheiro de fonte válido encontrado.
    """
    env_path = os.environ.get(FONT_ENV_VAR)
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path
        raise FontNotFoundError(
            f"Fonte não encontrada em FONT_PATH='{env_path}'. "
            f"Coloque um ficheiro .ttf/.ttc válido nesse caminho."
        )

    for filename in ("font.ttf", "font.ttc"):
        default_path = FONTS_DIR / filename
        if default_path.is_file():
            return default_path

    raise FontNotFoundError(
        f"Nenhuma fonte encontrada em '{FONTS_DIR}/'. "
        f"Coloque um ficheiro .ttf ou .ttc (com suporte Unicode/CJK) nesse diretório "
        f"ou defina a variável de ambiente {FONT_ENV_VAR}."
    )


def load_font(size: int, font_path: Path) -> ImageFont.FreeTypeFont:
    """Carrega uma fonte TrueType com o tamanho especificado.

    Suporta ficheiros .ttf, .otf e .ttc (neste caso, usa o índice 0).

    Raises:
        FontNotFoundError: O ficheiro não pôde ser carregado pelo PIL.
    """
    try:
        return ImageFont.truetype(str(font_path), size, index=0)
    except OSError as exc:
        raise FontNotFoundError(
            f"Falha ao carregar fonte '{font_path}': {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Helpers de imagem
# ---------------------------------------------------------------------------
def _load_cover_image(cover_path: Optional[str]) -> Optional[Image.Image]:
    """Carrega a imagem de capa e converte para RGB.

    Retorna ``None`` se *cover_path* estiver em falta ou o ficheiro
    não puder ser lido.
    """
    if not cover_path:
        return None

    path = Path(cover_path)
    if not path.is_file():
        logger.warning("Capa não encontrada: %s", path)
        return None

    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except Exception as exc:
        logger.warning("Falha ao carregar capa '%s': %s", path, exc)
        return None


def _create_background(cover: Optional[Image.Image]) -> Image.Image:
    """Cria o fundo do frame: capa desfocada ou cinzento escuro."""
    bg = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), color=COLOR_BG_FALLBACK)

    if cover is None:
        return bg

    try:
        blurred = cover.resize(
            (FRAME_WIDTH, FRAME_HEIGHT), Image.Resampling.LANCZOS
        )
        blurred = blurred.filter(ImageFilter.GaussianBlur(radius=30))
        bg.paste(blurred)
    except Exception as exc:
        logger.warning("Falha ao criar fundo desfocado: %s", exc)

    return bg


def _create_thumbnail(cover: Optional[Image.Image]) -> Image.Image:
    """Redimensiona a capa para COVER_SIZE × COVER_SIZE, ou retorna placeholder."""
    if cover is None:
        return Image.new(
            "RGB", (COVER_SIZE, COVER_SIZE), color=COLOR_COVER_PLACEHOLDER
        )
    return cover.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# Desenho de texto
# ---------------------------------------------------------------------------
def draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int],
    shadow_fill: Tuple[int, int, int] = COLOR_SHADOW,
    shadow_offset: Tuple[int, int] = SHADOW_OFFSET,
) -> None:
    """Desenha *text* em *position* com sombra para legibilidade."""
    shadow_pos = (
        position[0] + shadow_offset[0],
        position[1] + shadow_offset[1],
    )
    draw.text(shadow_pos, text, font=font, fill=shadow_fill)
    draw.text(position, text, font=font, fill=fill)


# ---------------------------------------------------------------------------
# Criação de frames
# ---------------------------------------------------------------------------
def create_frame(
    meta: SongMetadata, output_path: Path, font_path: Path
) -> None:
    """Cria um frame individual 1920×1080 para uma música.

    Args:
        meta: Metadados da música.
        output_path: Caminho onde guardar o PNG.
        font_path: Caminho para o ficheiro .ttf/.ttc.

    Raises:
        FontNotFoundError: Se a fonte não puder ser carregada.
    """
    font_title = load_font(TITLE_SIZE, font_path)
    font_artist = load_font(ARTIST_SIZE, font_path)
    font_info = load_font(INFO_SIZE, font_path)
    font_rating = load_font(RATING_SIZE, font_path)

    cover = _load_cover_image(meta.cover_path)

    bg = _create_background(cover)
    bg.paste(_create_thumbnail(cover), COVER_POS)

    draw = ImageDraw.Draw(bg)
    x = COVER_POS[0] + COVER_SIZE + TEXT_MARGIN_LEFT
    y = TEXT_START_Y

    # 1. Número da posição (#01)
    draw_text_with_shadow(
        draw, (x, y), f"#{meta.position:02d}", font_title, COLOR_POSITION
    )
    y += TITLE_SIZE + SPACING_AFTER_POSITION

    # 2. Título da música
    draw_text_with_shadow(
        draw, (x, y), meta.title, font_title, COLOR_TITLE
    )
    y += TITLE_SIZE + SPACING_AFTER_TITLE

    # 3. Artista
    draw_text_with_shadow(
        draw, (x, y), meta.artist, font_artist, COLOR_ARTIST
    )
    y += ARTIST_SIZE + SPACING_AFTER_ARTIST

    # 4. Álbum
    draw_text_with_shadow(
        draw, (x, y), f"Álbum: {meta.album}", font_info, COLOR_INFO
    )
    y += INFO_SIZE + SPACING_AFTER_INFO_LINE

    # 5. Ano de lançamento
    draw_text_with_shadow(
        draw, (x, y), f"Ano: {meta.year}", font_info, COLOR_INFO
    )
    y += INFO_SIZE + SPACING_AFTER_INFO_LINE

    # 6. Tags (Género)
    draw_text_with_shadow(
        draw, (x, y), f"Tags: {meta.genre}", font_info, COLOR_INFO
    )
    y += INFO_SIZE + SPACING_BEFORE_RATINGS

    # 7. Ratings
    if meta.rym_rating != "N/A" or meta.aoty_rating != "N/A":
        rating_text = f"RYM: {meta.rym_rating}   AOTY: {meta.aoty_rating}"
    else:
        rating_text = "Ratings: N/A"
    draw_text_with_shadow(
        draw, (x, y), rating_text, font_rating, COLOR_RATING
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(output_path)


def render_frames(metadatas: List[SongMetadata], frames_dir: Path) -> None:
    """Gera um frame 1920×1080 por música e guarda em *frames_dir*.

    Raises:
        FontNotFoundError: Se nenhum ficheiro de fonte estiver disponível.
    """
    font_path = resolve_font_path()
    frames_dir.mkdir(parents=True, exist_ok=True)

    for meta in metadatas:
        frame_path = frames_dir / f"{meta.position:02d}.png"
        create_frame(meta, frame_path, font_path)
        logger.info("Frame renderizado: %s", frame_path)
