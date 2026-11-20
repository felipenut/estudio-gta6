@echo off
setlocal
rem PREVIA (rapido, sem renderizar): checa o roteiro, narra (ou reaproveita) e gera a previa de enquadramento
rem em out\previa_enquadramento.jpg para o Claude revisar o recorte de cada corte.
rem Uso: arraste a pasta do projeto em cima deste arquivo, ou de dois cliques (usa o projeto mais recente).
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

echo 2-planejando cortes e enquadramento> "%ST%"
%T% %PY% ferramentas\scripts\montar.py "%PROJ%\roteiro.json" --saida "%PROJ%\out" --lib biblioteca\biblioteca.json --so-plano
if errorlevel 1 (echo ERRO: plano> "%ST%" & pause & exit /b 1)

echo PREVIA PRONTA> "%ST%"
echo.
echo ===== PREVIA PRONTA: volte ao Claude e diga "previa pronta" =====
pause
