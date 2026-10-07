"""Comprobar que el EXE empaquetado puede crear el PDF y el TXT."""
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_control import fixture, entries
from test_etiquetas import label


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        pdf = folder / "control.pdf"
        fixture(pdf, [entries() + [(261,170,"Funda sin SKU",True),
                                  (261,182,"Cantidad: 1",False), (261,194,"Color: Gris",False)]])
        archive = folder / "pedido.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("control.pdf", pdf.read_bytes())
            z.writestr("etiquetas.txt", label())
        table = folder / "tabla.txt"
        table.write_text("/2000018000000001\t40\tSKU-A\n/2000018000000001\t2\tFUNDA-TABLA", encoding="utf-8")
        result = subprocess.run([str(executable), "--sin-ventana", "--zip", str(archive),
                                 "--tabla", str(table), "--salida", str(folder / "salida")], timeout=90)
        if result.returncode:
            raise RuntimeError("El ejecutable no terminó correctamente.")
        pdfs = list((folder / "salida").glob("*/Control_resumido.pdf"))
        texts = list((folder / "salida").glob("*/Etiquetas/*.txt"))
        if len(pdfs) != 1 or len(texts) != 1 or "^FD40/SKU-A /2/FUNDA-TABLA^FS" not in texts[0].read_text():
            raise RuntimeError("El ejecutable no produjo los dos archivos esperados.")
        import fitz
        with fitz.open(pdfs[0]) as pdf:
            text = pdf[0].get_text()
            if "×2" not in text or "Funda sin SKU" not in text or "FUNDA-TABLA" in text:
                raise RuntimeError("El ejecutable cambió una cantidad del PDF.")
        table.write_text("fila incorrecta", encoding="utf-8")
        failed_output = folder / "fallo"
        failure = subprocess.run([str(executable), "--sin-ventana", "--zip", str(archive),
                                  "--tabla", str(table), "--salida", str(failed_output)], timeout=90)
        logs = list(failed_output.glob("Error_Control*.txt"))
        if failure.returncode != 1 or len(logs) != 1 or list(failed_output.glob("**/*.pdf")):
            raise RuntimeError("El ejecutable no registró el fallo sin publicar un PDF.")
        print("Ejecutable probado: PDF y etiquetas generados correctamente.")


if __name__ == "__main__":
    main()
