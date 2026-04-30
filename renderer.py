import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from fetcher import SongMetadata

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Configuração de fonte personalizada
# Coloque um ficheiro .ttf na raiz do projeto com o nome 'font.ttf'
# ou defina a variável de ambiente FONT_PATH para outro caminho.
# -------------------------------------------------------------------
CUSTOM_FONT_PATH = Path(os.environ.get("FONT_PATH", "font.ttf"))

# Tamanhos de fonte (escala 1080p)
TITLE_SIZE = 96       # para "#01" e nome da música
ARTIST_SIZE = 60      # artista
INFO_SIZE = 44        # ano | género | álbum
RATING_SIZE = 44      # ratings

# Cores
COLOR_POSITION = (255, 255, 255)     # branco
COLOR_TITLE = (255, 215, 0)          # amarelo ouro
COLOR_ARTIST = (240, 240, 240)       # quase branco
COLOR_INFO = (190, 190, 190)         # cinza claro
COLOR_RATING = (200, 200, 200)       # cinza claro
COLOR_SHADOW = (0, 0, 0)             # preto para sombra

# Deslocamento da sombra (pixels)
SHADOW_OFFSET = (3, 3)

def _find_system_font(bold: bool = True) -> Optional[str]:
    """Procura uma fonte de sistema aceitável, com preferência para DejaVu/Arial."""
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # Linux
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",              # Arch
            "/System/Library/Fonts/Helvetica.ttc",                   # macOS (negrito index 1)
            "C:\\Windows\\Fonts\\arialbd.ttf",                       # Windows
            "C:\\Windows\\Fonts\\segoeuib.ttf",                      # Windows moderno
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        ]
    for path_str in candidates:
        p = Path(path_str)
        if p.exists():
            return str(p)
    return None

def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    Carrega uma fonte com o tamanho especificado.
    Prioridade: 1) FONTE_PERSONALIZADA (se existir)
                 2) Fonte de sistema de alta qualidade
                 3) Fonte padrão do PIL (fallback, baixa qualidade)
    """
    if CUSTOM_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(CUSTOM_FONT_PATH), size)
        except Exception as e:
            logger.warning(f"Erro ao carregar fonte personalizada: {e}")

    # Fallback para fonte de sistema (negrito ou normal)
    sys_font = _find_system_font(bold)
    if sys_font:
        try:
            return ImageFont.truetype(sys_font, size)
        except Exception:
            pass

    # Último recurso – a fonte padrão do PIL (feia, mas funcional)
    logger.warning("Usando fonte padrão do PIL (baixa qualidade). Instale 'DejaVu' ou forneça uma 'font.ttf'.")
    return ImageFont.load_default()

def render_frames(metadatas: List[SongMetadata], frames_dir: Path):
    """Gera um frame 1920x1080 por música e guarda em frames_dir."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    for meta in metadatas:
        frame_path = frames_dir / f"{meta.position:02d}.png"
        create_frame(meta, frame_path)

def create_frame(meta: SongMetadata, output_path: Path) -> None:
    """
    Cria um frame individual com:
    - Fundo desfocado da capa (ou cinza escuro)
    - Capa do álbum à esquerda (800x800)
    - Textos à direita com sombra para legibilidade
    """
    # Carregar fontes
    font_title = load_font(TITLE_SIZE, bold=True)
    font_artist = load_font(ARTIST_SIZE, bold=False)
    font_info = load_font(INFO_SIZE, bold=False)
    font_rating = load_font(RATING_SIZE, bold=False)

    # Criar tela base
    bg = Image.new("RGB", (1920, 1080), color=(30, 30, 30))

    # Fundo desfocado se a capa existir
    try:
        if meta.cover_path and Path(meta.cover_path).exists():
            cover = Image.open(meta.cover_path).convert("RGB")
            # Redimensionar para preencher o ecrã
            cover = cover.resize((1920, 1080), Image.Resampling.LANCZOS)
            cover = cover.filter(ImageFilter.GaussianBlur(radius=30))
            bg.paste(cover)
    except Exception:
        pass  # mantém fundo escuro

    # Capa do álbum (800x800) à esquerda
    cover_size = 800
    cover_pos_x, cover_pos_y = 80, 140  # posição vertical centrada

    # Criar miniatura da capa
    thumbnail = Image.new("RGB", (cover_size, cover_size), color="black")
    try:
        if meta.cover_path and Path(meta.cover_path).exists():
            src = Image.open(meta.cover_path).convert("RGB")
            src = src.resize((cover_size, cover_size), Image.Resampling.LANCZOS)
            thumbnail = src
    except Exception:
        pass

    bg.paste(thumbnail, (cover_pos_x, cover_pos_y))

    # Área de texto (coluna direita)
    draw = ImageDraw.Draw(bg)
    x = cover_pos_x + cover_size + 80   # margem entre capa e texto
    y = 180

    # Função auxiliar para desenhar texto com sombra
    def draw_text_with_shadow(xy, text, font, color, shadow_color=COLOR_SHADOW, offset=SHADOW_OFFSET):
        # Sombra
        draw.text((xy[0] + offset[0], xy[1] + offset[1]), text, font=font, fill=shadow_color)
        # Texto principal
        draw.text(xy, text, font=font, fill=color)

    # 1. Número da posição (#01)
    draw_text_with_shadow((x, y), f"#{meta.position:02d}", font_title, COLOR_POSITION)
    y += TITLE_SIZE + 20

    # 2. Título da música
    draw_text_with_shadow((x, y), meta.title, font_title, COLOR_TITLE)
    y += TITLE_SIZE + 20

    # 3. Artista
    draw_text_with_shadow((x, y), meta.artist, font_artist, COLOR_ARTIST)
    y += ARTIST_SIZE + 40

    # 4. Linha informativa (Ano | Género | Álbum)
    info_text = f"{meta.year}  |  {meta.genre}  |  {meta.album}"
    draw_text_with_shadow((x, y), info_text, font_info, COLOR_INFO)
    y += INFO_SIZE + 40

    # 5. Ratings (RYM e AOTY)
    if meta.rym_rating != "N/A" or meta.aoty_rating != "N/A":
        rating_text = f"RYM: {meta.rym_rating}   AOTY: {meta.aoty_rating}"
    else:
        rating_text = "Ratings: N/A"
    draw_text_with_shadow((x, y), rating_text, font_rating, COLOR_RATING)

    # Guardar frame
    bg.save(output_path)
