{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    # 1. Alterado para Python 3.12 para resolver o conflito do sphinx-9.1.0
    (python312.withPackages (ps: with ps; [
      # Dependências Principais (Runtime)
      httpx
      pydantic
      pydantic-settings
      python-dotenv
      filetype
      pillow
      librosa

      # Dependências de Desenvolvimento (Dev)
      pytest
      pytest-asyncio
      pytest-cov
      ruff
      mypy
      pre-commit
      pip
    ]))

    # 2. Dependências de Sistema (Ferramentas e Runtime)
    ffmpeg
    yt-dlp
    tree       
    git          
    glibcLocales 
  ];

  # 3. Dependências de Compilação/Sistema para bibliotecas Python (ex: Pillow)
  nativeBuildInputs = with pkgs; [
    pkg-config
    zlib
    libjpeg
    libtiff
    libwebp
    lcms2
    freetype
  ];

  shellHook = ''
    echo "🚀 Ambiente de desenvolvimento 'mytopsongs' ativo!"
    echo "Python: $(python --version)"
    echo "FFmpeg: $(ffmpeg -version | head -n 1)"
    echo "Para instalar o projeto em modo de edição (se necessário): pip install -e ."
  '';
}
