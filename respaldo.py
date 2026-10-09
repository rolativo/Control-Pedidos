"""Copia opcional del TXT, con tiempo limitado para cada dirección del NAS."""
from dataclasses import dataclass
from datetime import datetime
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import uuid


DESTINATIONS = (r"\\WD-NAS\Public\impresiones", r"\\10.10.1.220\Public\impresiones")


@dataclass(frozen=True)
class CopyResult:
    path: str | None = None
    warning: str | None = None


def _copy_one(source, destination, name, events):
    temporary = None
    try:
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / (".copiando_" + uuid.uuid4().hex + ".tmp")
        data = Path(source).read_bytes()
        with temporary.open("xb") as stream:
            stream.write(data)
        stem = Path(name).stem
        for counter in range(1000):
            target = folder / (stem + (f"_{counter:02d}" if counter else "") + ".txt")
            if target.exists():
                continue
            try:
                # En Windows, rename no sustituye un archivo existente.
                temporary.rename(target)
                temporary = None
                events.put((True, str(target)))
                return
            except FileExistsError:
                continue
        raise OSError("No se encontró un nombre libre para la copia.")
    except Exception as exc:
        events.put((False, str(exc)))
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def backup_labels(source, destinations=None, timeout=6, now=None):
    warning = ("No se pudo entrar a la carpeta de impresiones por ninguna de las dos direcciones. "
               "El PDF y el TXT se generaron correctamente y están en su carpeta de salida.")
    if destinations is None and sys.platform != "win32":
        return CopyResult(warning=warning)
    destinations = DESTINATIONS if destinations is None else destinations
    name = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S") + ".txt"
    for destination in destinations:
        process = events = None
        try:
            context = mp.get_context("spawn")
            events = context.Queue()
            process = context.Process(target=_copy_one,
                                      args=(str(source), str(destination), name, events), daemon=True)
            process.start()
            process.join(timeout)
            if process.is_alive():
                process.terminate()
                process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join(1)
                continue
            try:
                success, payload = events.get(timeout=0.5)
            except queue.Empty:
                continue
            if success:
                return CopyResult(path=payload)
        except Exception:
            continue
        finally:
            if process and process.is_alive():
                process.terminate()
                process.join(1)
            if events:
                events.close()
    return CopyResult(warning=warning)
