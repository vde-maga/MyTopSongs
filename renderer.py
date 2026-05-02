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

# Tamanhos de fonte base (escala 1080p)
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

# Layout - Posições e Margens
COVER_SIZE = 800
COVER_POS = (80, 140)
TEXT_MARGIN_LEFT = 80
RIGHT_MARGIN = 80
TEXT_START_Y = 180
BOTTOM_MARGIN = 40      # Margem de segurança inferior

# Layout - Espaçamentos verticais
SHADOW_OFFSET = (3, 3)
SPACING_AFTER_POSITION = 20
SPACING_AFTER_TITLE = 20
SPACING_AFTER_ARTIST = 40
SPACING_AFTER_INFO_LINE = 20
SPACING_BEFORE_RATINGS = 40
LINE_SPACING = 10


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------
class FontNotFoundError(FileNotFoundError):
    """O ficheiro .ttf/.ttc requerido não foi encontrado."""


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------
def resolve_font_path() -> Path:
    """Resolve o caminho para o ficheiro de fonte fornecido pelo utilizador."""
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
        f"Coloque um ficheiro .ttf ou .ttc nesse diretório "
        f"ou defina a variável de ambiente {FONT_ENV_VAR}."
    )


def load_font(size: int, font_path: Path) -> ImageFont.FreeTypeFont:
    """Carrega uma fonte TrueType com o tamanho especificado."""
    size = max(8, size)  # Defensivo: nunca permitir fontes invisíveis
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
    """Carrega a imagem de capa e converte para RGB."""
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
# Desenho de texto (com Word Wrap dinâmico)
# ---------------------------------------------------------------------------
def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> List[str]:
    """Quebra o texto em múltiplas linhas para não exceder *max_width*."""
    if not text:
        return [""]

    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def draw_text_block_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int],
    max_width: int,
    shadow_fill: Tuple[int, int, int] = COLOR_SHADOW,
    shadow_offset: Tuple[int, int] = SHADOW_OFFSET,
    line_spacing: int = LINE_SPACING,
) -> int:
    """Desenha um bloco de texto com sombra e retorna a nova posição Y."""
    lines = _wrap_text(text, font, max_width)
    x, y = position
    font_height = sum(font.getmetrics())

    for i, line in enumerate(lines):
        draw_text_with_shadow(draw, (x, y), line, font, fill, shadow_fill, shadow_offset)
        y += font_height
        if i < len(lines) - 1:
            y += line_spacing

    return y


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
# Medição e Criação de frames
# ---------------------------------------------------------------------------
def _measure_required_height(
    elements: List[dict], font_path: Path, max_width: int, scale: float = 1.0
) -> int:
    """Calcula a altura total requerida para desenhar todos os elementos."""
    total_height = 0
    for i, el in enumerate(elements):
        size = int(el["size"] * scale)
        font = load_font(size, font_path)
        lines = _wrap_text(el["text"], font, max_width)
        font_height = sum(font.getmetrics())
        
        # Altura do bloco de texto
        total_height += len(lines) * font_height + max(0, len(lines) - 1) * int(LINE_SPACING * scale)
        
        # Espaçamento após o bloco (exceto o último)
        if i < len(elements) - 1:
            total_height += int(el["space"] * scale)
            
    return total_height


def create_frame(
    meta: SongMetadata, output_path: Path, font_path: Path
) -> None:
    """Cria um frame individual 1920×1080 para uma música."""
    
    # 1. Preparar estrutura de dados dos textos (DRY)
    rating_text = (
        f"RYM: {meta.rym_rating}   AOTY: {meta.aoty_rating}"
        if meta.rym_rating != "N/A" or meta.aoty_rating != "N/A"
        else "Ratings: N/A"
    )
    
    elements = [
        {"text": f"#{meta.position:02d}", "size": TITLE_SIZE, "color": COLOR_POSITION, "space": SPACING_AFTER_POSITION},
        {"text": meta.title, "size": TITLE_SIZE, "color": COLOR_TITLE, "space": SPACING_AFTER_TITLE},
        {"text": meta.artist, "size": ARTIST_SIZE, "color": COLOR_ARTIST, "space": SPACING_AFTER_ARTIST},
        {"text": f"Álbum: {meta.album}", "size": INFO_SIZE, "color": COLOR_INFO, "space": SPACING_AFTER_INFO_LINE},
        {"text": f"Ano: {meta.year}", "size": INFO_SIZE, "color": COLOR_INFO, "space": SPACING_AFTER_INFO_LINE},
        {"text": f"Tags: {meta.genre}", "size": INFO_SIZE, "color": COLOR_INFO, "space": SPACING_BEFORE_RATINGS},
        {"text": rating_text, "size": RATING_SIZE, "color": COLOR_RATING, "space": 0},
    ]

    max_text_width = FRAME_WIDTH - (COVER_POS[0] + COVER_SIZE + TEXT_MARGIN_LEFT) - RIGHT_MARGIN
    available_height = FRAME_HEIGHT - TEXT_START_Y - BOTTOM_MARGIN

    # 2. Calcular escala dinâmica para caber no ecrã
    base_height = _measure_required_height(elements, font_path, max_text_width, scale=1.0)
    scale = 1.0
    if base_height > available_height:
        scale = available_height / base_height
        logger.info(
            f"Frame #{meta.position:02d}: Texto longo detectado. "
            f"A aplicar escala de {scale:.2f} para caber no ecrã."
        )

    # 3. Renderização
    cover = _load_cover_image(meta.cover_path)
    bg = _create_background(cover)
    bg.paste(_create_thumbnail(cover), COVER_POS)

    draw = ImageDraw.Draw(bg)
    x = COVER_POS[0] + COVER_SIZE + TEXT_MARGIN_LEFT
    y = TEXT_START_Y

    for i, el in enumerate(elements):
        size = int(el["size"] * scale)
        font = load_font(size, font_path)
        current_line_spacing = int(LINE_SPACING * scale)
        
        y = draw_text_block_with_shadow(
            draw, (x, y), el["text"], font, el["color"], max_text_width, 
            line_spacing=current_line_spacing
        )
        
        if i < len(elements) - 1:
            y += int(el["space"] * scale)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(output_path)


def render_frames(metadatas: List[SongMetadata], frames_dir: Path) -> None:
    """Gera um frame 1920×1080 por música e guarda em *frames_dir*."""
    font_path = resolve_font_path()
    frames_dir.mkdir(parents=True, exist_ok=True)

    for meta in metadatas:
        frame_path = frames_dir / f"{meta.position:02d}.png"
        create_frame(meta, frame_path, font_path)
        logger.info("Frame renderizado: %s", frame_path)
