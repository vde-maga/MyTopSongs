"""Renderer – gera um frame 1920×1080 por música."""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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

# === SWITCH: Capa Redonda ===
ROUND_COVER = True  

# Tamanhos de fonte base (escala 1080p)
POSITION_SIZE = 48
TITLE_SIZE = 86
ARTIST_SIZE = 56
INFO_SIZE = 38

# Cores (R, G, B)
COLOR_POSITION = (255, 255, 255)
COLOR_TITLE = (45, 24, 41)
COLOR_ARTIST = (86, 114, 41)
COLOR_INFO = (159, 183, 234)
COLOR_BG_FALLBACK = (20, 20, 20)
COLOR_OVERLAY = (0, 0, 0, 100) # Overlay escuro para contraste do fundo

# Sombra do Texto
SHADOW_OFFSET = (4, 4)
SHADOW_BLUR_RADIUS = 6       # Suavidade da sombra (0 = sem blur, 6 = muito suave)
SHADOW_OPACITY = 0.5         # Opacidade da sombra (0.0 a 1.0) - Reduzido para ser menos presente

# Layout - Posições e Margens
COVER_SIZE = 680
TEXT_MARGIN_LEFT = 80
RIGHT_MARGIN = 100
BOTTOM_MARGIN = 40

# Layout - Espaçamentos verticais
SPACING_AFTER_POSITION = 15
SPACING_AFTER_TITLE = 15
SPACING_AFTER_ARTIST = 30
SPACING_AFTER_INFO_LINE = 15
LINE_SPACING = 8


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------
class FontNotFoundError(FileNotFoundError):
    """O ficheiro .ttf/.ttc requerido não foi encontrado."""


# ---------------------------------------------------------------------------
# Fonte (Com Cache para remover redundância de I/O)
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


@lru_cache(maxsize=32)
def load_font(size: int, font_path: Path) -> ImageFont.FreeTypeFont:
    """Carrega uma fonte TrueType com o tamanho especificado (Com Cache)."""
    size = max(8, size)
    try:
        return ImageFont.truetype(str(font_path), size, index=0)
    except OSError as exc:
        raise FontNotFoundError(f"Falha ao carregar fonte '{font_path}': {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers de imagem
# ---------------------------------------------------------------------------
def _load_cover_image(cover_path: Optional[str]) -> Optional[Image.Image]:
    """Carrega a imagem de capa e converte para RGBA."""
    if not cover_path:
        return None

    path = Path(cover_path)
    if not path.is_file():
        logger.warning("Capa não encontrada: %s", path)
        return None

    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except Exception as exc:
        logger.warning("Falha ao carregar capa '%s': %s", path, exc)
        return None


def _create_background(cover: Optional[Image.Image]) -> Image.Image:
    """Cria o fundo do frame com overlay escuro para legibilidade."""
    bg = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), color=COLOR_BG_FALLBACK)

    if cover is not None:
        try:
            blurred = cover.resize((FRAME_WIDTH, FRAME_HEIGHT), Image.Resampling.LANCZOS)
            blurred = blurred.filter(ImageFilter.GaussianBlur(radius=40))
            bg.paste(blurred)
        except Exception as exc:
            logger.warning("Falha ao criar fundo desfocado: %s", exc)

    # Overlay escuro para garantir contraste do texto
    overlay = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), COLOR_OVERLAY)
    bg = Image.alpha_composite(bg, overlay)

    return bg


def _create_thumbnail(cover: Optional[Image.Image], round_shape: bool) -> Image.Image:
    """Redimensiona a capa e aplica máscara se necessário."""
    size = COVER_SIZE
    if cover is None:
        img = Image.new("RGBA", (size, size), (30, 30, 30, 255))
    else:
        img = cover.resize((size, size), Image.Resampling.LANCZOS)

    if round_shape:
        # Máscara circular
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)
        
        output = ImageOps.fit(img, (size, size), centering=(0.5, 0.5))
        output.putalpha(mask)

        # Borda sutil
        border_draw = ImageDraw.Draw(output)
        border_draw.ellipse([(2, 2), (size - 2, size - 2)], outline=(255, 255, 255, 40), width=3)
        return output
    else:
        # Capa quadrada normal com cantos ligeiramente arredondados (opcional, mas fica bem)
        # Se quiseres mesmo 100% quadrada, mudar para radius=0
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([(0, 0), (size, size)], radius=20, fill=255)
        img.putalpha(mask)
        return img


# ---------------------------------------------------------------------------
# Desenho de texto (Apenas Lógica de Wrap, Sem Sombras)
# ---------------------------------------------------------------------------
def _break_long_word(word: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    lines = []
    current_line = ""
    for char in word:
        test_line = current_line + char
        line_width = font.getbbox(test_line)[2]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
    if current_line:
        lines.append(current_line)
    return lines if lines else [word]


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]

    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}" if current_line else word
        line_width = font.getbbox(test_line)[2]

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
                current_line = ""
            
            word_width = font.getbbox(word)[2]
            if word_width <= max_width:
                current_line = word
            else:
                broken = _break_long_word(word, font, max_width)
                lines.extend(broken[:-1])
                current_line = broken[-1] if broken else ""

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, ...],
    max_width: int,
    line_spacing: int = LINE_SPACING,
) -> int:
    """Desenha um bloco de texto (SEM SOMBRA) e retorna a nova posição Y."""
    lines = _wrap_text(text, font, max_width)
    x, y = position
    font_height = sum(font.getmetrics())

    for i, line in enumerate(lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += font_height
        if i < len(lines) - 1:
            y += line_spacing

    return y


# ---------------------------------------------------------------------------
# Medição e Criação de frames
# ---------------------------------------------------------------------------
def _measure_required_height(
    elements: List[dict], font_path: Path, max_width: int, scale: float = 1.0
) -> int:
    total_height = 0
    for i, el in enumerate(elements):
        size = int(el["size"] * scale)
        font = load_font(size, font_path)
        lines = _wrap_text(el["text"], font, max_width)
        font_height = sum(font.getmetrics())
        
        total_height += len(lines) * font_height + max(0, len(lines) - 1) * int(LINE_SPACING * scale)
        
        if i < len(elements) - 1:
            total_height += int(el["space"] * scale)
            
    return total_height


def _find_optimal_scale(
    elements: List[dict], font_path: Path, max_width: int, available_height: int
) -> float:
    if _measure_required_height(elements, font_path, max_width, 1.0) <= available_height:
        return 1.0

    low, high = 0.1, 1.0
    best_scale = low
    
    for _ in range(10):
        mid = (low + high) / 2
        current_height = _measure_required_height(elements, font_path, max_width, mid)
        
        if current_height <= available_height:
            best_scale = mid
            low = mid
        else:
            high = mid

    return best_scale


def create_frame(
    meta: SongMetadata, output_path: Path, font_path: Path
) -> None:
    """Cria um frame individual 1920×1080 para uma música."""
    
    elements = [
        {"text": f"#{meta.position:02d}", "size": POSITION_SIZE, "color": COLOR_POSITION, "space": SPACING_AFTER_POSITION},
        {"text": meta.title, "size": TITLE_SIZE, "color": COLOR_TITLE, "space": SPACING_AFTER_TITLE},
        {"text": meta.artist, "size": ARTIST_SIZE, "color": COLOR_ARTIST, "space": SPACING_AFTER_ARTIST},
        {"text": f"Álbum: {meta.album}", "size": INFO_SIZE, "color": COLOR_INFO, "space": SPACING_AFTER_INFO_LINE},
        {"text": f"Ano: {meta.year}", "size": INFO_SIZE, "color": COLOR_INFO, "space": 0},
    ]

    # Calcular limites de texto com base na capa
    cover_x_start = 100
    max_text_width = FRAME_WIDTH - (cover_x_start + COVER_SIZE + TEXT_MARGIN_LEFT) - RIGHT_MARGIN
    available_height = FRAME_HEIGHT - 100 - BOTTOM_MARGIN

    # Calcular escala dinâmica
    scale = _find_optimal_scale(elements, font_path, max_text_width, available_height)
    
    if scale < 0.99:
        logger.info(f"Frame #{meta.position:02d}: Texto longo. Escala {scale:.2f} aplicada.")

    # --- RENDERIZAÇÃO ---
    cover = _load_cover_image(meta.cover_path)
    bg = _create_background(cover)
    
    # Posições da Capa
    cover_pos = (cover_x_start, (FRAME_HEIGHT - COVER_SIZE) // 2)
    
    # 1. Desenhar Sombra da Capa (Correspondendo à forma redonda ou quadrada)
    shadow_layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    
    shadow_offset_val = 10
    if ROUND_COVER:
        shadow_draw.ellipse(
            [cover_pos[0] + shadow_offset_val, cover_pos[1] + shadow_offset_val, 
             cover_pos[0] + COVER_SIZE + shadow_offset_val, cover_pos[1] + COVER_SIZE + shadow_offset_val], 
            fill=(0, 0, 0, 140)
        )
    else:
        shadow_draw.rounded_rectangle(
            [cover_pos[0] + shadow_offset_val, cover_pos[1] + shadow_offset_val, 
             cover_pos[0] + COVER_SIZE + shadow_offset_val, cover_pos[1] + COVER_SIZE + shadow_offset_val], 
            radius=20, fill=(0, 0, 0, 140)
        )
        
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=25))
    bg = Image.alpha_composite(bg, shadow_layer)
    
    # 2. Colar a Capa
    thumbnail = _create_thumbnail(cover, ROUND_COVER)
    bg.paste(thumbnail, cover_pos, thumbnail)

    # 3. Preparar Texto e Sombra Profissional
    x = cover_x_start + COVER_SIZE + TEXT_MARGIN_LEFT
    total_text_height = _measure_required_height(elements, font_path, max_text_width, scale)
    cover_center_y = cover_pos[1] + COVER_SIZE // 2
    y = cover_center_y - total_text_height // 2

    # Criar camada para a sombra do texto
    shadow_padding = 40  # Para o blur não cortar nas bordas
    text_shadow_layer = Image.new("RGBA", (max_text_width + shadow_padding * 2, total_text_height + shadow_padding * 2), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(text_shadow_layer)
    
    # Desenhar texto preto na camada de sombra
    temp_y = shadow_padding
    for i, el in enumerate(elements):
        size = int(el["size"] * scale)
        font = load_font(size, font_path)
        current_line_spacing = int(LINE_SPACING * scale)
        
        temp_y = draw_text_block(
            shadow_draw, (shadow_padding, temp_y), el["text"], font, (0, 0, 0, 255), 
            max_text_width, line_spacing=current_line_spacing
        )
        if i < len(elements) - 1:
            temp_y += int(el["space"] * scale)

    # Aplicar Blur e Opacidade à sombra do texto
    if SHADOW_BLUR_RADIUS > 0:
        text_shadow_layer = text_shadow_layer.filter(ImageFilter.GaussianBlur(radius=SHADOW_BLUR_RADIUS))
    
    # Reduzir a presença/opacidade da sombra
    alpha = text_shadow_layer.split()[3]
    alpha = alpha.point(lambda p: int(p * SHADOW_OPACITY))
    text_shadow_layer.putalpha(alpha)

    # Colar camada de sombra no fundo principal
    bg.paste(text_shadow_layer, (x - shadow_padding + SHADOW_OFFSET[0], y - shadow_padding + SHADOW_OFFSET[1]), text_shadow_layer)

    # 4. Desenhar Texto Final (Por cima da sombra, na imagem principal)
    main_draw = ImageDraw.Draw(bg)
    curr_y = y
    for i, el in enumerate(elements):
        size = int(el["size"] * scale)
        font = load_font(size, font_path)
        current_line_spacing = int(LINE_SPACING * scale)
        
        curr_y = draw_text_block(
            main_draw, (x, curr_y), el["text"], font, el["color"], 
            max_text_width, line_spacing=current_line_spacing
        )
        if i < len(elements) - 1:
            curr_y += int(el["space"] * scale)

    # Converter de volta para RGB e salvar
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, quality=95)


def render_frames(metadatas: List[SongMetadata], frames_dir: Path) -> None:
    """Gera um frame 1920×1080 por música e guarda em *frames_dir*."""
    font_path = resolve_font_path()
    load_font.cache_clear() 
    frames_dir.mkdir(parents=True, exist_ok=True)

    for meta in metadatas:
        frame_path = frames_dir / f"{meta.position:02d}.png"
        create_frame(meta, frame_path, font_path)
        logger.info("Frame renderizado: %s", frame_path)
