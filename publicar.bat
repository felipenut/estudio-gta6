@echo off
rem Publica as ferramentas no GitHub (os programas instalados se atualizam sozinhos ao abrir).
rem Primeira vez: publicar.bat primeira      Depois: publicar.bat
title Publicar Estudio GTA 6 no GitHub
cd /d "%~dp0"
if /i "%~1"=="primeira" goto primeira

set "MSG="
set /p "MSG=O que mudou nesta versao? "
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\publicar.ps1" -Mensagem "%MSG%"
goto fim

:primeira
set "NOME="
set /p "NOME=Nome do repositorio no GitHub [estudio-gta6]: "
if "%NOME%"=="" set "NOME=estudio-gta6"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\publicar.ps1" -Primeira -Repo "%NOME%" -Mensagem "primeira versao"

:fim
echo.
pause
