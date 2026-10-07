"""Unir el control PDF y las etiquetas ZPL usando una tabla copiada."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from control import ControlError, Order, read_orders, render_pdf


@dataclass(frozen=True)
class TableRow:
    identifier: str
    quantity: int
    sku: str


@dataclass(frozen=True)
class LabelInfo:
    number: int
    identifier: str
    text: str
    font_size: int


@dataclass
class LabelResult:
    text: str
    labels: list[LabelInfo]
    configuration_blocks: int
    unused_rows: list[TableRow]


@dataclass
class BundleResult:
    folder: Path
    pdf: Path
    labels_file: Path
    report: Path
    orders: int
    labels: int
    pages: int
    unused_rows: int


def parse_table(text: str) -> list[TableRow]:
    """Admite tres columnas copiadas de Excel o una tabla Markdown."""
    rows = []
    for index, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            columns = [c.strip() for c in line.strip("|").split("|")]
        elif "\t" in line:
            columns = [c.strip() for c in line.split("\t")]
        else:
            columns = [c.strip() for c in re.split(r"\s{2,}", line)]
        if columns and all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in columns):
            continue
        if len(columns) == 3 and columns[0].casefold().replace(" ", "") in (
                "packid", "packid/venta", "packidoventa", "venta", "pedido", "identificador"):
            continue
        if len(columns) != 3:
            raise ControlError(f"Tabla, fila {index}: copia exactamente tres columnas: "
                               "Pack ID o Venta, Cantidad y SKU.")
        identifier = columns[0].removeprefix("/")
        quantity, sku = columns[1:]
        if not re.fullmatch(r"\d{12,22}", identifier):
            raise ControlError(f"Tabla, fila {index}: Pack ID o Venta ilegible.")
        if not re.fullmatch(r"[1-9]\d*", quantity):
            raise ControlError(f"Tabla, fila {index}: la cantidad debe ser un entero mayor que cero.")
        if not sku or re.search(r"[\s^~\x00-\x1f\x7f]", sku):
            raise ControlError(f"Tabla, fila {index}: SKU vacío o con caracteres no admitidos.")
        rows.append(TableRow(identifier, int(quantity), sku))
    if not rows:
        raise ControlError("La tabla está vacía. Copia las tres columnas y pulsa Pegar tabla.")
    return rows


BLOCK = re.compile(r"\^XA.*?\^XZ", re.S)
FO_FIELD = re.compile(r"\^FO(\d+),(\d+)((?:(?!\^FO|\^XZ).)*?)\^FD(.*?)\^FS", re.S)
ID_VALUE = re.compile(r"^(Pack\s*ID|Venta)\s*:\s*(\d+)$", re.I)


def label_identifiers(block: str) -> list[tuple[str, str]]:
    """Reconstruye IDs fragmentados por coordenadas, sin leer números de envío."""
    fields = [(int(m[1]), int(m[2]), m[4]) for m in FO_FIELD.finditer(block)]
    found = []
    for x, y, value in fields:
        match = ID_VALUE.fullmatch(value.strip())
        if not match:
            continue
        kind = "Pack ID" if match[1].lower().startswith("pack") else "Venta"
        value = match[2]
        # Mercado Libre imprime el fragmento en negrita dos veces con un píxel
        # de diferencia. Solo se toma una vez. Las coordenadas excluyen códigos
        # de envío, números de domicilio y otros campos de la etiqueta.
        fragments = sorted((fx, fy, text) for fx, fy, text in fields
                           if fx > x and abs(fy - y) <= 8 and re.fullmatch(r"\d+", text))
        previous_x, previous_text = None, None
        for fx, fy, text in fragments:
            if previous_x is not None and abs(fx - previous_x) <= 2 and text == previous_text:
                continue
            value += text
            previous_x, previous_text = fx, text
        if not re.fullmatch(r"\d{12,22}", value):
            raise ControlError(f"No se pudo reconstruir el {kind} de una etiqueta.")
        found.append((kind, value))
    return found


def zpl_field(text: str) -> str:
    """Escapar datos para ^FH; un SKU no puede inyectar comandos ZPL."""
    result = []
    for byte in text.encode("utf-8"):
        if byte in (ord("_"), ord("^"), ord("~")) or byte < 32 or byte > 126:
            result.append(f"_{byte:02X}")
        else:
            result.append(chr(byte))
    return "".join(result)


def insert_label_data(block: str, number: int, identifier: str, text: str) -> tuple[str, int]:
    newline = "\r\n" if "\r\n" in block else "\n"
    # Volver a procesar una etiqueta creada por este programa no duplica campos.
    block = re.sub(r"(?m)^\^FX NUMERO_CONSECUTIVO[^\r\n]*(?:\r?\n)?", "", block)
    block = re.sub(r"\^FO30,100\^A0N,45,45\^FB80,1,0,C\^FD\d+\^FS(?:\r?\n)?", "", block)
    block = re.sub(r"(?m)^\^FX DATOS_PACK[^\r\n]*(?:\r?\n)?", "", block)
    block = re.sub(r"\^FO(?:120,20|133,2)\^A0N,\d+,\d+\^FB650,1,0,L\^FH\^FD[^\^]*\^FS(?:\r?\n)?", "", block)
    # La etiqueta compacta tiene Pack ID a la altura 100. Sus campos del
    # remitente se dejan en su lugar; la línea nueva usa su margen superior.
    compact = any(int(m[2]) <= 105 and ID_VALUE.fullmatch(m[4].strip())
                  for m in FO_FIELD.finditer(block))
    max_font = 16 if compact else 24
    font = min(max_font, max(9, int(650 / max(1, math.ceil(len(text) * 0.62)))))
    if len(text) * font * 0.62 > 650:
        raise ControlError(f"Pedido {number:02d}: demasiados datos para la línea de la etiqueta.")
    if not compact:
        block = re.sub(r"\^FO120,20\^A0N,24,24\^FH\^FDRemitente([^\^]*)\^FS",
                       r"^FO120,43^A0N,24,24^FH^FDRemitente\1^FS", block, flags=re.I)
        block = re.sub(r"\^FO120,43\^A0N,24,24\^FB550,2,0,L\^FH\^FDCarr_2E([^\^]*)\^FS",
                       r"^FO120,66^A0N,24,24^FB550,1,0,L^FH^FDCarr_2E\1^FS", block, flags=re.I)
    x, y = (133, 2) if compact else (120, 20)
    inserted = (f"^FX DATOS_PACK {identifier} ^FS{newline}"
                f"^FO{x},{y}^A0N,{font},{font}^FB650,1,0,L^FH^FD{zpl_field(text)}^FS{newline}"
                f"^FX NUMERO_CONSECUTIVO {number:02d} ^FS{newline}"
                f"^FO30,100^A0N,45,45^FB80,1,0,C^FD{number:02d}^FS{newline}")
    origin = re.search(r"\^LH[^\r\n^]*(?:\r?\n)?", block)
    position = origin.end() if origin else len("^XA")
    block = block[:position] + inserted + block[position:]
    return block, font


def transform_labels(text: str, orders: list[Order], rows: list[TableRow]) -> LabelResult:
    order_ids = {}
    for number, order in enumerate(orders, 1):
        for identifier in (order.pack_id, order.sale):
            if identifier:
                if identifier in order_ids and order_ids[identifier][0] != number:
                    raise ControlError("Un identificador corresponde a dos pedidos diferentes.")
                order_ids[identifier] = (number, order)
    table_by_order = defaultdict(list)
    unused = []
    for row in rows:
        if row.identifier in order_ids:
            table_by_order[order_ids[row.identifier][0]].append(row)
        else:
            unused.append(row)
    for number, order in enumerate(orders, 1):
        expected = Counter(p.sku for p in order.products if p.sku is not None)
        actual = Counter(row.sku for row in table_by_order[number])
        unknown = sum(p.sku is None for p in order.products)
        if expected - actual or sum((actual - expected).values()) != unknown:
            missing = list((expected - actual).elements())
            extra = list((actual - expected).elements())
            detail = ("faltan " + ", ".join(missing) if missing else "")
            if extra:
                detail += ("; " if detail else "") + "sobran " + ", ".join(extra)
            if unknown:
                detail += ("; " if detail else "") + (f"el PDF tiene {unknown} producto(s) sin SKU; "
                          "incluye también sus filas en la tabla")
            raise ControlError(f"Tabla del pedido {number:02d}: {detail}. No se generó el conjunto.")
    matches = list(BLOCK.finditer(text))
    if not matches or len(matches) != text.count("^XA") or len(matches) != text.count("^XZ"):
        raise ControlError("El TXT no contiene bloques ZPL completos y reconocibles.")
    output = []
    labels = []
    configuration = 0
    cursor = 0
    seen = set()
    for match in matches:
        output.append(text[cursor:match.start()])
        block = match[0]
        identifiers = label_identifiers(block)
        if not identifiers:
            if "^FD" in block or "^FO" in block or "^GFA" in block or "^GF" in block:
                raise ControlError("Una etiqueta no tiene Pack ID ni Venta reconocibles.")
            configuration += 1
            output.append(block)
            cursor = match.end()
            continue
        pairs = []
        for kind, identifier in identifiers:
            if identifier not in order_ids:
                raise ControlError(f"Etiqueta con {kind} {identifier}: no aparece en el PDF.")
            pairs.append((identifier, *order_ids[identifier]))
        if len({pair[1] for pair in pairs}) != 1:
            raise ControlError("Una etiqueta contiene identificadores de pedidos distintos.")
        identifier, number, order = pairs[0]
        line = " /".join(f"{row.quantity}/{row.sku}" for row in table_by_order[number])
        block, font = insert_label_data(block, number, identifier, line)
        labels.append(LabelInfo(number, identifier, line, font))
        seen.add(number)
        output.append(block)
        cursor = match.end()
    output.append(text[cursor:])
    expected_orders = set(range(1, len(orders) + 1))
    if seen != expected_orders:
        missing = ", ".join(f"{i:02d}" for i in sorted(expected_orders - seen))
        raise ControlError(f"Faltan etiquetas para los pedidos: {missing}. No se generó el conjunto.")
    return LabelResult("".join(output), labels, configuration, unused)


MAX_PDF = 50 * 1024 * 1024
MAX_TEXT = 30 * 1024 * 1024


def read_zip(path: Path) -> tuple[bytes, bytes, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            pdfs = [i for i in files if PurePosixPath(i.filename).suffix.lower() == ".pdf"]
            texts = [i for i in files if PurePosixPath(i.filename).suffix.lower() == ".txt"]
            if len(pdfs) != 1 or len(texts) != 1:
                raise ControlError("El ZIP debe contener un PDF de control y un TXT de etiquetas. "
                                   "También puedes seleccionarlos por separado.")
            if pdfs[0].file_size > MAX_PDF or texts[0].file_size > MAX_TEXT:
                raise ControlError("Los archivos del ZIP son demasiado grandes para este proceso.")
            return archive.read(pdfs[0]), archive.read(texts[0]), PurePosixPath(texts[0].filename).name
    except ControlError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ControlError("No se pudo abrir el ZIP seleccionado o está protegido.") from exc


def safe_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem).strip("_")[:80] or "pedidos"


def bundle(pdf_bytes: bytes, txt_bytes: bytes, table: str, output_root: Path,
           source_name: str, label_name: str = "Etiquetas.txt") -> BundleResult:
    rows = parse_table(table)
    if len(pdf_bytes) > MAX_PDF or len(txt_bytes) > MAX_TEXT:
        raise ControlError("El PDF o TXT supera el tamaño admitido.")
    try:
        label_text = txt_bytes.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ControlError("El TXT no está codificado como UTF-8 y no se puede modificar con seguridad.") from exc
    output_root = Path(output_root)
    # Hasta validar todos los pedidos no se crea ninguna salida definitiva.
    with tempfile.TemporaryDirectory(prefix="control-entrada-") as temporary:
        source = Path(temporary) / "entrada.pdf"
        source.write_bytes(pdf_bytes)
        try:
            orders, original_pages = read_orders(source)
        except ControlError:
            raise
        except Exception as exc:
            raise ControlError("No se pudo abrir el PDF del conjunto.") from exc
        labels = transform_labels(label_text, orders, rows)
        output_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".control-conjunto-", dir=output_root))
        final_folder = None
        try:
            pdf_path = staging / "Control_resumido.pdf"
            pages = render_pdf(orders, pdf_path)
            label_directory = staging / "Etiquetas"
            label_directory.mkdir()
            txt_name = safe_stem(label_name) + ".txt"
            label_path = label_directory / txt_name
            label_path.write_text(labels.text, encoding="utf-8", newline="")
            report_path = staging / "Revision.txt"
            report = ["CONTROL Y ETIQUETAS", "",
                      f"Pedidos del PDF: {len(orders)}",
                      f"Etiquetas de envío: {len(labels.labels)}",
                      f"Bloques de configuración conservados sin numerar: {labels.configuration_blocks}",
                      f"Hojas del control: {original_pages} -> {pages}",
                      "Cantidades del PDF: las del PDF original.",
                      "Cantidades de las etiquetas: las de la tabla copiada.", "",
                      "COINCIDENCIAS"]
            report.extend(f"{label.number:02d} | {label.identifier} | {label.text}" for label in labels.labels)
            report.extend(["", "PRODUCTOS SIN SKU EN EL PDF ORIGINAL"])
            report.extend(f"{number:02d} | {product.description} | "
                          "Conservado sin SKU en el control. La fila adicional de la tabla "
                          "se usa solo en la etiqueta; su SKU no se puede verificar contra el PDF."
                          for number, order in enumerate(orders, 1)
                          for product in order.products if product.sku is None)
            report.extend(["", "FILAS DE LA TABLA NO UTILIZADAS", f"Total: {len(labels.unused_rows)}"])
            report.extend(f"{row.identifier}\t{row.quantity}\t{row.sku}" for row in labels.unused_rows)
            report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
            import fitz
            with fitz.open(pdf_path) as checked:
                if len(checked) != pages:
                    raise ControlError("No se pudo validar el control generado.")
            # La carpeta de resultados se publica solo cuando termina todo.
            base = "Surtido_" + safe_stem(source_name) + "_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            counter = 0
            while True:
                folder = output_root / (base + (f"_{counter:02d}" if counter else ""))
                try:
                    folder.mkdir()
                    final_folder = folder
                    break
                except FileExistsError:
                    counter += 1
            for item in staging.iterdir():
                shutil.move(str(item), str(final_folder / item.name))
            return BundleResult(final_folder, final_folder / pdf_path.name,
                                final_folder / "Etiquetas" / txt_name,
                                final_folder / report_path.name, len(orders),
                                len(labels.labels), pages, len(labels.unused_rows))
        except Exception:
            if final_folder:
                shutil.rmtree(final_folder)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def bundle_zip(source: Path, table: str, output_root: Path | None = None) -> BundleResult:
    source = Path(source)
    pdf, txt, txt_name = read_zip(source)
    return bundle(pdf, txt, table, output_root or source.parent, source.name, txt_name)


def bundle_files(pdf: Path, txt: Path, table: str, output_root: Path | None = None) -> BundleResult:
    pdf, txt = Path(pdf), Path(txt)
    if pdf.stat().st_size > MAX_PDF or txt.stat().st_size > MAX_TEXT:
        raise ControlError("El PDF o TXT supera el tamaño admitido.")
    return bundle(pdf.read_bytes(), txt.read_bytes(), table, output_root or pdf.parent, pdf.name, txt.name)
