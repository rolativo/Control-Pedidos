"""Preparar el Generador original fuera de la carpeta temporal del EXE."""
from pathlib import Path
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
