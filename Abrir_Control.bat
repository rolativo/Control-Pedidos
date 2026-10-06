@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Primero ejecuta Preparar_Programa.bat.
    echo Este archivo necesita Python instalado; el EXE de GitHub no lo necesita.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "app.py" %*
