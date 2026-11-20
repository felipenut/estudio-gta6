@echo off
rem Monta o instalador Setup_EstudioGTA6.exe (pasta instalador\). Deixe esta janela aberta ate aparecer PRONTO.
title Montando o instalador do Estudio GTA 6
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\montar_exe.ps1"
echo.
pause
