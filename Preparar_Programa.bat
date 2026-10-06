@echo off
setlocal
cd /d "%~dp0"
echo Este paso instala las dependencias del programa en la carpeta .venv.
echo Requiere Python 3.11 o posterior instalado y conexion a internet.
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python 3.11 o posterior con el lanzador py.
    echo Puedes utilizar el EXE que genera GitHub sin instalar Python.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo Listo. Abre Abrir_Control.bat.
pause
exit /b 0
:error
echo No se pudo preparar el programa. Revisa el mensaje anterior.
pause
exit /b 1
