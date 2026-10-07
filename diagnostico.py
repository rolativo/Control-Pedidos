"""Errores visibles y registros locales, incluso en el EXE sin consola."""
from datetime import datetime
import os
from pathlib import Path
import tempfile
import traceback


def record_error(message, source=None, output=None, exception=None):
    folders = []
    if output:
        folders.append(Path(output))
    if source:
        folders.append(Path(source).resolve().parent)
    folders.append(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ControlPedidos" / "Errores")
    folders.append(Path(tempfile.gettempdir()) / "ControlPedidos" / "Errores")
    report = ["ERROR DE CONTROL DE PEDIDOS", datetime.now().isoformat(timespec="seconds"), "", str(message)]
    if source:
        report.extend(["", "Archivo seleccionado: " + str(source)])
    if exception is not None:
        report.extend(["", "Detalle técnico:", "".join(traceback.format_exception(
            type(exception), exception, exception.__traceback__))])
    for folder in dict.fromkeys(folders):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for counter in range(1000):
                name = "Error_Control" + (f"_{counter}" if counter else "") + ".txt"
                path = folder / name
                try:
                    with path.open("x", encoding="utf-8") as stream:
                        stream.write("\n".join(report) + "\n")
                    return str(message) + "\n\nArchivo de error: " + str(path)
                except FileExistsError:
                    continue
        except OSError:
            continue
    return str(message) + "\n\nNo se pudo guardar el archivo de error en ninguna carpeta disponible."


def install_handlers(root):
    def callback_error(kind, exception, tb):
        from tkinter import messagebox
        exception = exception.with_traceback(tb)
        message = record_error("Ocurrió un error al usar el programa: " + str(exception),
                               exception=exception)
        messagebox.showerror("No se pudo completar la operación", message, parent=root)
    root.report_callback_exception = callback_error


def startup_error(exception):
    message = record_error("No se pudo abrir el programa: " + str(exception), exception=exception)
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Control de pedidos", 0x10)
    else:
        import sys
        if sys.stderr:
            print(message, file=sys.stderr)
