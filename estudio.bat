@echo off
setlocal
rem ESTUDIO: abre a interface no navegador (http://127.0.0.1:8765). Deixe esta janela aberta enquanto usa.
cd /d "%~dp0.."
call "%~dp0scripts\_ambiente.bat"
if errorlevel 1 exit /b 1
%PY% -c "import edge_tts, PIL, cv2" >nul 2>&1 || %PY% -m pip install -U "yt-dlp[default]" deno edge-tts pillow "opencv-python-headless<5"
title Estudio GTA 6 Shorts - deixe aberta
%PY% ferramentas\scripts\estudio.py
pause
