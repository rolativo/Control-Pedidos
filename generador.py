"""Preparar el Generador original fuera de la carpeta temporal del EXE."""
from pathlib import Path
import os
import subprocess
import sys

from control import ControlError


def prepare_generator(parent: Path) -> Path:
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "tools"
    names = ("GENERADOR.bat", "Generador.ps1")
    if not all((resources / name).is_file() for name in names):
        raise ControlError("No se encontraron los archivos del Generador en el programa.")
    files = {name: (resources / name).read_bytes() for name in names}
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    counter = 0
    while True:
        folder = parent / ("Generador" + (f"_{counter:02d}" if counter else ""))
        if folder.exists():
            if all((folder / name).is_file() and (folder / name).read_bytes() == data
                   for name, data in files.items()):
                return folder / "GENERADOR.bat"
            counter += 1
            continue
        try:
            folder.mkdir()
            break
        except FileExistsError:
            counter += 1
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder / "GENERADOR.bat"


def prepare_shortcut(bat: Path):
    """El icono externo se aplica a un acceso directo, sin cambiar el BAT."""
    if sys.platform != "win32":
        return
    try:
        resources = Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent)) / "assets"
        icon = bat.parent / "Generador_de_Excel.ico"
        icon.write_bytes((resources / "mask.ico").read_bytes())
        link = bat.parent / "Generador de Excel.lnk"
        environment = os.environ.copy()
        environment.update(EL_TODO_BAT=str(bat), EL_TODO_ICON=str(icon),
                           EL_TODO_LINK=str(link), EL_TODO_DIR=str(bat.parent))
        command = ("$w=New-Object -ComObject WScript.Shell;"
                   "$s=$w.CreateShortcut($env:EL_TODO_LINK);"
                   "$s.TargetPath=$env:ComSpec;"
                   "$s.Arguments='/c \"\"'+$env:EL_TODO_BAT+'\"\"';"
                   "$s.WorkingDirectory=$env:EL_TODO_DIR;"
                   "$s.IconLocation=$env:EL_TODO_ICON;"
                   "$s.Save()")
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        # La falta de acceso directo no impide abrir el BAT original.
        pass
