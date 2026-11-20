"""Prepara o computador para o pipeline gta6-shorts. Rode uma vez:  python setup.py"""
import shutil, subprocess, sys

PACOTES = ["edge-tts", "yt-dlp", "pillow", "faster-whisper", "opencv-python-headless<5"]

print("instalando pacotes python:", ", ".join(PACOTES))
subprocess.call([sys.executable, "-m", "pip", "install", "-U", *PACOTES])

if shutil.which("ffmpeg") and shutil.which("ffprobe"):
    print("ffmpeg: ok")
else:
    print("ffmpeg NÃO encontrado.")
    if sys.platform.startswith("win"):
        print("  instale com:  winget install --id Gyan.FFmpeg -e   (depois feche e reabra o terminal)")
    else:
        print("  instale pelo gerenciador de pacotes (brew install ffmpeg / apt install ffmpeg)")
print("fonte: instale assets/fonts/Bangers-Regular.ttf no sistema para o After Effects (clique direito > Instalar)")
