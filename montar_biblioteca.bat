@echo off
setlocal
rem Monta/atualiza a biblioteca de clipes: instala dependencias, baixa os videos oficiais de GTA VI
rem do canal da Rockstar e divide tudo em cenas com miniaturas. Pode rodar de novo quando sair video novo.
cd /d "%~dp0.."
call "%~dp0scripts\_ambiente.bat"
if errorlevel 1 exit /b 1
if not exist biblioteca mkdir biblioteca
set ST=biblioteca\status.txt
set LOG=biblioteca\log.txt
set T=%PY% ferramentas\scripts\tee.py %LOG% --

echo 1-instalando pacotes> %ST%
%T% %PY% -m pip install -U "yt-dlp[default]" deno edge-tts pillow "opencv-python-headless<5"
if errorlevel 1 (echo ERRO: pip> %ST% & pause & exit /b 1)

echo 2-baixando videos oficiais da Rockstar> %ST%
%T% %PY% ferramentas\scripts\baixar.py oficiais --pasta biblioteca\videos
if errorlevel 1 echo AVISO: algum download falhou, seguindo com o que baixou>> %ST%

echo 3-dividindo em cenas e gerando miniaturas> %ST%
%T% %PY% ferramentas\scripts\biblioteca.py indexar biblioteca\videos --lib biblioteca\biblioteca.json
if errorlevel 1 (echo ERRO: indexar> %ST% & pause & exit /b 1)
%T% %PY% ferramentas\scripts\biblioteca.py pendentes --lib biblioteca\biblioteca.json

echo PRONTO> %ST%
echo.
echo ===== BIBLIOTECA PRONTA. Volte ao Claude e diga "biblioteca pronta". =====
pause
