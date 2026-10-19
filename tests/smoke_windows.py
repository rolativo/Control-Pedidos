"""Comprobar que el EXE empaquetado puede crear el PDF y el TXT."""
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_control import fixture, entries
from test_etiquetas import label, BLOCK


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        pdf = folder / "control.pdf"
        fixture(pdf, [entries(products=[("SMEN40NE-100","1","100 Toallas faciales",[])]) + [(261,170,"Funda sin SKU",True),
                                  (261,182,"Cantidad: 1",False), (261,194,"Color: Gris",False)] + entries(260,sale="2000019000000002",pack="2000018000000002")],
                product_heading="Producto")
        archive = folder / "pedido.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("control.pdf", pdf.read_bytes())
            z.writestr("etiquetas.txt", label()+label("2000018000000002"))
        table = folder / "tabla.txt"
        table.write_text("/2000018000000001\t100\tSMEN40NE\n/2000018000000001\t2\tFUNDA-TABLA\n/2000018000000002\t40\tSKU-A", encoding="utf-8")
        result = subprocess.run([str(executable), "--sin-ventana", "--zip", str(archive),
                                 "--tabla", str(table), "--salida", str(folder / "salida")], timeout=90)
        if result.returncode:
            raise RuntimeError("El ejecutable no terminó correctamente.")
        archive = folder / "Surtido pedido.zip"
        if not archive.is_file():
            raise RuntimeError("El ejecutable no agregó Surtido al ZIP original.")
        pdfs = list((folder / "salida").glob("*/Control_resumido.pdf"))
        texts = list((folder / "salida").glob("*/Etiquetas/*.txt"))
        if len(pdfs) != 1 or len(texts) != 1 or "^FD100/SMEN40NE /2/FUNDA-TABLA^FS" not in texts[0].read_text():
            raise RuntimeError("El ejecutable no produjo los dos archivos esperados.")
        import fitz
        with fitz.open(pdfs[0]) as pdf:
            text = pdf[0].get_text()
            if "SMEN40NE-100" not in text or "×1" not in text or "Funda sin SKU" not in text or "FUNDA-TABLA" in text:
                raise RuntimeError("El ejecutable cambió una cantidad del PDF.")
        table.write_text("fila incorrecta", encoding="utf-8")
        failed_output = folder / "fallo"
        failure = subprocess.run([str(executable), "--sin-ventana", "--zip", str(archive),
                                  "--tabla", str(table), "--salida", str(failed_output)], timeout=90)
        logs = list(failed_output.glob("Error_Control*.txt"))
        if failure.returncode != 1 or len(logs) != 1 or list(failed_output.glob("**/*.pdf")):
            raise RuntimeError("El ejecutable no registró el fallo sin publicar un PDF.")
        table.write_text("/2000018000000001\t100\tSMEN40NE",encoding="utf-8")
        only_output = folder / "faltantes"
        numbered = subprocess.run([str(executable), "--sin-ventana", "--zip", str(archive),
                                   "--permitir-faltantes", "--tabla", str(table), "--salida", str(only_output)], timeout=90)
        if numbered.returncode:
            raise RuntimeError("El ejecutable no generó las guías con datos faltantes.")
        labels = list(only_output.glob("*/Etiquetas/*.txt"))[0].read_text(encoding="utf-8")
        blocks = BLOCK.findall(labels)
        if "100/SMEN40NE" not in blocks[0] or "NUMERO_CONSECUTIVO 01" not in blocks[0]:
            raise RuntimeError("La guía con datos perdió su SKU o su número.")
        if "DATOS_PACK" in blocks[1] or "NUMERO_CONSECUTIVO 02" not in blocks[1]:
            raise RuntimeError("La guía sin datos no quedó únicamente con su consecutivo.")
        print("Ejecutable probado: PDF y etiquetas generados correctamente.")


if __name__ == "__main__":
    main()
