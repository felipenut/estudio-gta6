@echo off
rem Prepara o ambiente: encontra/instala Python e ffmpeg. Define PY. Chamado pelos outros .bat.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set PY=
python --version >nul 2>&1 && set "PY=python"
if not defined PY (py -3 --version >nul 2>&1 && set "PY=py -3")
if not defined PY (
  echo Python nao encontrado. Instalando pelo winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python instalado. FECHE esta janela e de dois cliques no arquivo de novo.
  pause
  exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo ffmpeg nao encontrado. Instalando pelo winget...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  echo.
  echo ffmpeg instalado. FECHE esta janela e de dois cliques no arquivo de novo.
  pause
  exit /b 1
)
exit /b 0
