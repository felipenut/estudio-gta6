@echo off
setlocal
rem Gera o video de um projeto: narracao -> montagem -> projeto do After Effects.
rem Uso: arraste a pasta do projeto (videos\AAAA-MM-DD_tema) em cima deste arquivo,
rem      ou de dois cliques para usar o projeto mais recente da pasta videos.
cd /d "%~dp0.."
call "%~dp0scripts\_ambiente.bat"
if errorlevel 1 exit /b 1
set "PROJ=%~1"
if "%PROJ%"=="" for /f "delims=" %%d in ('dir /b /ad /o-d videos 2^>nul') do if not defined PROJ set "PROJ=videos\%%d"
if not exist "%PROJ%\roteiro.json" (echo roteiro.json nao encontrado em "%PROJ%" & pause & exit /b 1)
set "ST=%PROJ%\status.txt"
set "LOG=%PROJ%\log.txt"
set T=%PY% ferramentas\scripts\tee.py "%LOG%" --
%PY% -c "import cv2" >nul 2>&1 || %T% %PY% -m pip install "opencv-python-headless<5"
set MUS=
if exist "%PROJ%\musica.mp3" set MUS=--musica "%PROJ%\musica.mp3"

echo 0-checando roteiro> "%ST%"
%T% %PY% ferramentas\scripts\checar_roteiro.py "%PROJ%\roteiro.json" --lib biblioteca\biblioteca.json
if errorlevel 1 (echo ERRO: roteiro reprovado no checador, veja log.txt> "%ST%" & pause & exit /b 1)

echo 1-narrando> "%ST%"
if exist "%PROJ%\minha_voz.*" (
  for %%f in ("%PROJ%\minha_voz.*") do %T% %PY% ferramentas\scripts\narrar.py "%PROJ%\roteiro.json" --saida "%PROJ%\out" --audio "%%f"
) else (
  %T% %PY% ferramentas\scripts\narrar.py "%PROJ%\roteiro.json" --saida "%PROJ%\out"
)
if errorlevel 1 (echo ERRO: narracao> "%ST%" & pause & exit /b 1)

echo 2-montando video> "%ST%"
%T% %PY% ferramentas\scripts\montar.py "%PROJ%\roteiro.json" --saida "%PROJ%\out" --lib biblioteca\biblioteca.json %MUS%
if errorlevel 1 (echo ERRO: montagem> "%ST%" & pause & exit /b 1)

echo 3-exportando After Effects> "%ST%"
%T% %PY% ferramentas\scripts\exportar_ae.py "%PROJ%\out\timeline.json"

echo PRONTO> "%ST%"
echo.
echo ===== VIDEO PRONTO: %PROJ%\out\final.mp4 =====
start "" "%PROJ%\out\final.mp4"
pause
