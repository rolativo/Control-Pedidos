"""Unir el control PDF y las etiquetas ZPL usando una tabla copiada."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from control import ControlError, Order, read_orders, render_pdf, order_ids, order_identity


class MissingTableError(ControlError):
    """Permite ofrecer el modo de solo consecutivos sin ocultar pedidos."""


class TableRowError(ControlError):
    def __init__(self, index, raw, message, identifier=None, shipping_id=None, sku=None, quantity=None):
        self.index = index
        self.identifier = identifier
        self.shipping_id = shipping_id
        self.sku = sku
        self.quantity = quantity
        details = ["No se pudo usar este registro de la tabla: " + message]
        if identifier:
            details.append("Venta / Pack ID / identificador pegado: " + identifier)
        if shipping_id:
            details.append("Número de guía / Envío: " + shipping_id)
        if sku:
            details.append("SKU pegado: " + sku)
        if quantity:
            details.append("Cantidad pegada: " + quantity)
        details.append("Texto exacto pegado: " + raw.strip())
        super().__init__("\n".join(details))


def order_description(number, order):
    parts = [f"Consecutivo del control: {number:02d}", order_identity(order)]
    skus = [p.sku for p in order.products if p.sku]
    if skus:
        parts.append("SKU en el PDF: " + ", ".join(skus))
    return "\n".join(parts)


@dataclass(frozen=True)
class TableRow:
    identifier: str
    quantity: int
    sku: str
    shipping_id: str | None = None


def row_description(row):
    values = []
    if row.identifier:
        values.append("Venta / Pack ID / identificador pegado: " + row.identifier)
    if row.shipping_id:
        values.append("Número de guía / Envío: " + row.shipping_id)
    values.extend(("SKU pegado: " + row.sku, "Cantidad pegada: " + str(row.quantity)))
    return "\n".join(values)


def resolve_table(orders, rows, identity_rows=()):
    """Cruza por identificadores explícitos; una coincidencia conflictiva se rechaza."""
    aliases = {}
    for number, order in enumerate(orders, 1):
        for identifier in order_ids(order):
            if identifier in aliases and aliases[identifier][0] != number:
                raise ControlError("El mismo identificador aparece en pedidos distintos:\n"
                                   + order_description(*aliases[identifier]) + "\n"
                                   + order_description(number, order))
            aliases[identifier] = (number, order)
    # Las cuatro columnas pueden enlazar una guía nueva con una Venta del PDF
    # antiguo, o una Venta de Excel con una guía del PDF nuevo. Nunca por SKU.
    pending = list(rows) + list(identity_rows)
    while pending:
        remaining = []
        progress = False
        for row in pending:
            ids = [value for value in (row.identifier, row.shipping_id) if value]
            matches = {aliases[value][0]: aliases[value] for value in ids if value in aliases}
            if len(matches) > 1:
                raise ControlError("Datos contradictorios: la Venta / Pack ID y la guía "
                                   "corresponden a pedidos distintos.\n" + row_description(row)
                                   + "\n\n" + "\n\n".join(order_description(*pair) for pair in matches.values()))
            if not matches:
                remaining.append(row)
                continue
            pair = next(iter(matches.values()))
            for identifier in ids:
                aliases[identifier] = pair
            progress = True
        if not progress:
            break
        pending = remaining
    table_by_order = defaultdict(list)
    unused = []
    for row in rows:
        matches = {aliases[value][0]: aliases[value] for value in (row.identifier, row.shipping_id)
                   if value and value in aliases}
        if len(matches) > 1:
            raise ControlError("La tabla contiene identificadores contradictorios.\n" + row_description(row))
        if matches:
            table_by_order[next(iter(matches))].append(row)
        else:
            unused.append(row)
    return aliases, table_by_order, unused


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
    differences: list[str] = field(default_factory=list)
    number_only_orders: list[str] = field(default_factory=list)


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
    differences: int = 0
    nas_copy: str | None = None
    nas_warning: str | None = None
    allow_missing: bool = False
    source_zip: Path | None = None
    source_warning: str | None = None
    number_only_orders: list[str] = field(default_factory=list)


def parse_table(text: str, errors=None) -> list[TableRow]:
    """Admite Venta/Pack ID, cantidad, SKU y guía opcional; Excel o Markdown."""
    rows = []
    for index, raw in enumerate(text.splitlines(), 1):
        try:
            row = parse_table_row(index, raw)
        except TableRowError as exc:
            if errors is None:
                raise
            errors.append(exc)
            continue
        if row:
            rows.append(row)
    if not rows and errors is None:
        raise ControlError("La tabla está vacía. Copia Venta / Pack ID, Cantidad, SKU y Número de guía (si existe).")
    return rows


def parse_table_row(index, raw):
    line = raw.strip(" \r\n")
    if not line.strip():
        return None
    if line.startswith("|"):
        inner = line[1:-1] if line.endswith("|") else line[1:]
        columns = [c.strip() for c in inner.split("|")]
    elif "\t" in line:
        columns = [c.strip() for c in line.split("\t")]
    else:
        columns = [c.strip() for c in re.split(r"\s{2,}", line)]
    if columns and all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in columns):
        return None
    first = columns[0].casefold().replace(" ", "") if columns else ""
    if len(columns) in (3, 4) and first in (
            "packid", "packid/venta", "packidoventa", "venta", "pedido", "identificador",
            "guía", "guia", "envio", "envío", "númerodeguía", "numerodeguia"):
        return None
    identifier = columns[0].lstrip("/#") if columns else ""
    quantity = columns[1] if len(columns) > 1 else ""
    sku = columns[2] if len(columns) > 2 else ""
    shipping = columns[3].lstrip("/#") if len(columns) == 4 else None
    def invalid(message):
        raise TableRowError(index, raw, message, identifier or None, shipping or None, sku, quantity)
    if len(columns) not in (3, 4):
        invalid("copia Venta / Pack ID, Cantidad, SKU y, como cuarta columna, Número de guía.")
    if shipping and not re.fullmatch(r"\d{8,25}", shipping):
        invalid("número de guía ilegible; copia todos sus dígitos como texto.")
    if (identifier and not re.fullmatch(r"\d{8,25}", identifier)) or not (identifier or shipping):
        invalid("Venta / Pack ID / número de guía ilegible.")
    if not re.fullmatch(r"[1-9]\d*", quantity):
        invalid("la cantidad debe ser un entero mayor que cero.")
    if not sku or re.search(r"[\s^~\x00-\x1f\x7f]", sku):
        invalid("SKU vacío o con caracteres no admitidos.")
    return TableRow(identifier, int(quantity), sku, shipping or None)


BLOCK = re.compile(r"\^XA.*?\^XZ", re.S)
FO_FIELD = re.compile(r"\^FO(\d+),(\d+)((?:(?!\^FO|\^XZ).)*?)\^FD(.*?)\^FS", re.S)
ID_VALUE = re.compile(r"^(Pack\s*ID|Venta|Env[ií]o|(?:N[uú]mero\s+de\s+)?gu[ií]a)\s*:\s*(\d+)$", re.I)


def label_identifiers(block: str) -> list[tuple[str, str]]:
    """Reconstruye los identificadores explícitos de la cabecera por coordenadas."""
    fields = [(int(m[1]), int(m[2]), m[4]) for m in FO_FIELD.finditer(block)]
    found = []
    for x, y, value in fields:
        match = ID_VALUE.fullmatch(value.strip())
        if not match:
            continue
        kind = ("Pack ID" if match[1].lower().startswith("pack") else
                "Venta" if match[1].lower() == "venta" else "Número de guía / Envío")
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
        if not re.fullmatch(r"\d{8,25}", value):
            raise ControlError(f"No se pudo reconstruir el {kind} de una etiqueta.")
        found.append((kind, value))
    return found


def label_details(block):
    details = [f"{kind}: {identifier}" for kind, identifier in label_identifiers(block)]
    shipping = re.findall(r"\^BC[^\^]*\^FD>:(\d+)\^FS", block)
    details.extend("Código de envío de la etiqueta: " + value for value in dict.fromkeys(shipping))
    return "\n".join(details) or "La etiqueta no contiene un identificador de envío legible."


def zpl_field(text: str) -> str:
    """Escapar datos para ^FH; un SKU no puede inyectar comandos ZPL."""
    result = []
    for byte in text.encode("utf-8"):
        if byte in (ord("_"), ord("^"), ord("~")) or byte < 32 or byte > 126:
            result.append(f"_{byte:02X}")
        else:
            result.append(chr(byte))
    return "".join(result)


def insert_label_data(block: str, number: int, identifier: str, text: str | None) -> tuple[str, int]:
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
    font = min(max_font, max(9, int(650 / max(1, math.ceil(len(text) * 0.62))))) if text else 0
    if text and len(text) * font * 0.62 > 650:
        raise ControlError(f"Pedido {number:02d}: demasiados datos para la línea de la etiqueta.")
    if text and not compact:
        block = re.sub(r"\^FO120,20\^A0N,24,24\^FH\^FDRemitente([^\^]*)\^FS",
                       r"^FO120,43^A0N,24,24^FH^FDRemitente\1^FS", block, flags=re.I)
        block = re.sub(r"\^FO120,43\^A0N,24,24\^FB550,2,0,L\^FH\^FDCarr_2E([^\^]*)\^FS",
                       r"^FO120,66^A0N,24,24^FB550,1,0,L^FH^FDCarr_2E\1^FS", block, flags=re.I)
    x, y = (133, 2) if compact else (120, 20)
    inserted = ((f"^FX DATOS_PACK {identifier} ^FS{newline}"
                 f"^FO{x},{y}^A0N,{font},{font}^FB650,1,0,L^FH^FD{zpl_field(text)}^FS{newline}") if text else "")
    inserted += (f"^FX NUMERO_CONSECUTIVO {number:02d} ^FS{newline}"
                f"^FO30,100^A0N,45,45^FB80,1,0,C^FD{number:02d}^FS{newline}")
    origin = re.search(r"\^LH[^\r\n^]*(?:\r?\n)?", block)
    position = origin.end() if origin else len("^XA")
    block = block[:position] + inserted + block[position:]
    return block, font


def transform_labels(text: str, orders: list[Order], rows: list[TableRow], allow_missing=False,
                     identity_rows=()) -> LabelResult:
    aliases, table_by_order, unused = resolve_table(orders, rows, identity_rows)
    differences = []
    missing = [(number, order) for number, order in enumerate(orders, 1)
               if not table_by_order[number]]
    if missing and not allow_missing:
        raise MissingTableError("Faltan datos en la tabla para estos pedidos:\n\n"
                                + "\n\n".join(order_description(number, order) for number, order in missing)
                                + "\n\nBusca estas Ventas, Pack ID o números de guía en Excel y copia sus datos. "
                                  "El consecutivo es el número del control, no la fila de Excel.\n"
                                  "También puedes continuar dejando solo el consecutivo en estas guías. "
                                  "Las demás conservarán los SKU y cantidades pegados.")
    for number, order in enumerate(orders, 1):
        if not table_by_order[number]:
            continue
        expected = Counter(p.sku for p in order.products if p.sku is not None)
        actual = Counter(row.sku for row in table_by_order[number])
        if expected != actual or any(p.sku is None for p in order.products):
            differences.append(f"{number:02d} | SKU del PDF: "
                               + ", ".join(p.sku or "(no existe en origen)" for p in order.products)
                               + " | Datos usados en la etiqueta: "
                               + " /".join(f"{row.quantity}/{row.sku}" for row in table_by_order[number]))
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
                raise ControlError("Una etiqueta no tiene Venta, Pack ID ni número de guía reconocibles.\n"
                                   + label_details(block))
            configuration += 1
            output.append(block)
            cursor = match.end()
            continue
        pairs = []
        for kind, identifier in identifiers:
            if identifier not in aliases:
                raise ControlError(f"Etiqueta con {kind}: {identifier}; no se pudo relacionar con el PDF.\n"
                                   + label_details(block) + "\n"
                                   + "\n".join(row_description(r) for r in rows
                                               if identifier in (r.identifier, r.shipping_id)))
            pairs.append((identifier, *aliases[identifier]))
        if len({pair[1] for pair in pairs}) != 1:
            raise ControlError("Una etiqueta contiene identificadores de pedidos distintos.\n"
                               + "\n\n".join(order_description(number, order)
                                               for _, number, order in pairs))
        identifier, number, order = pairs[0]
        line = " /".join(f"{row.quantity}/{row.sku}" for row in table_by_order[number])
        try:
            block, font = insert_label_data(block, number, identifier, line or None)
        except ControlError as exc:
            raise ControlError(str(exc) + "\n" + order_description(number, order) + "\n"
                               + "\n\n".join(row_description(row) for row in table_by_order[number])) from exc
        labels.append(LabelInfo(number, identifier, line, font))
        seen.add(number)
        output.append(block)
        cursor = match.end()
    output.append(text[cursor:])
    expected_orders = set(range(1, len(orders) + 1))
    if seen != expected_orders:
        missing = "\n\n".join(order_description(i, orders[i-1]) for i in sorted(expected_orders - seen))
        raise ControlError(f"Faltan etiquetas para los pedidos: {missing}. No se generó el conjunto.")
    return LabelResult("".join(output), labels, configuration, unused, differences,
                       [order_description(n, o) for n, o in missing])


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
           source_name: str, label_name: str = "Etiquetas.txt", allow_missing=False) -> BundleResult:
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
        bad_rows = []
        row_warnings = []
        rows = parse_table(table, errors=bad_rows)
        identity_rows = list(rows)
        for error in bad_rows:
            identifier = error.identifier if error.identifier and re.fullmatch(r"\d{8,25}", error.identifier) else ""
            shipping = error.shipping_id if error.shipping_id and re.fullmatch(r"\d{8,25}", error.shipping_id) else None
            if identifier or shipping:
                identity_rows.append(TableRow(identifier, 1, "", shipping))
        aliases, _, _ = resolve_table(orders, rows, identity_rows)
        blocked_orders = set()
        for error in bad_rows:
            matches = {aliases[value][0]: aliases[value] for value in
                       (error.identifier, error.shipping_id) if value and value in aliases}
            if len(matches) != 1:
                if matches:
                    error.args = (str(error) + "\nIdentificadores de pedidos distintos:\n"
                                  + "\n\n".join(order_description(*pair) for pair in matches.values()),)
                raise error
            number, order = next(iter(matches.values()))
            error.args = (str(error) + "\n" + order_description(number, order),)
            error.can_omit = True
            if not allow_missing:
                raise error
            blocked_orders.add(number)
            row_warnings.append(str(error))
        if blocked_orders:
            rows = [row for row in rows if not any(aliases[value][0] in blocked_orders
                    for value in (row.identifier, row.shipping_id) if value and value in aliases)]
        if not rows and not bad_rows and not allow_missing:
            raise MissingTableError("La tabla no contiene datos para estos pedidos:\n\n"
                                    + "\n\n".join(order_description(n, order) for n, order in enumerate(orders, 1)))
        labels = transform_labels(label_text, orders, rows, allow_missing, identity_rows)
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
                      "SKU y cantidades de las guías con datos: los de la tabla copiada.",
                      f"Pedidos con guía solo numerada por datos faltantes: {len(labels.number_only_orders)}", "",
                      "COINCIDENCIAS"]
            report.extend(f"{label.number:02d} | {label.identifier} | {label.text}" for label in labels.labels)
            report.extend(["", "GUÍAS SOLO CON CONSECUTIVO (SIN DATOS UTILIZABLES)"])
            report.extend(labels.number_only_orders)
            report.extend(["", "RENGLONES INVÁLIDOS DE ESTOS PEDIDOS"])
            report.extend(row_warnings)
            report.extend(["", "DIFERENCIAS DE SKU (NO IMPIDEN GENERAR)",
                           "La tabla pegada tiene prioridad para SKU y cantidades de las etiquetas."])
            report.extend(labels.differences)
            report.extend(["", "PRODUCTOS SIN SKU EN EL PDF ORIGINAL"])
            report.extend(f"{number:02d} | {product.description} | "
                          "Conservado sin SKU en el control. La fila adicional de la tabla "
                          "se usa solo en la etiqueta; su SKU no se puede verificar contra el PDF."
                          for number, order in enumerate(orders, 1)
                          for product in order.products if product.sku is None)
            report.extend(["", "FILAS DE LA TABLA NO UTILIZADAS", f"Total: {len(labels.unused_rows)}"])
            report.extend(row_description(row) for row in labels.unused_rows)
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
                                len(labels.labels), pages, len(labels.unused_rows), len(labels.differences),
                                allow_missing=allow_missing, number_only_orders=labels.number_only_orders)
        except Exception:
            if final_folder:
                shutil.rmtree(final_folder)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def rename_processed_zip(source: Path) -> Path:
    if source.name.casefold().startswith("surtido"):
        return source
    for counter in range(1000):
        suffix = "" if counter == 0 else f" ({counter+1})"
        target = source.with_name("Surtido " + source.stem + suffix + source.suffix)
        try:
            if os.name == "nt":
                source.rename(target)
            else:
                os.link(source, target)
                try:
                    source.unlink()
                except OSError:
                    target.unlink()
                    raise
            return target
        except FileExistsError:
            continue
    raise OSError("No hay un nombre libre para marcar el ZIP como Surtido.")


def bundle_zip(source: Path, table: str = "", output_root: Path | None = None,
               allow_missing=False) -> BundleResult:
    source = Path(source)
    pdf, txt, txt_name = read_zip(source)
    result = bundle(pdf, txt, table, output_root or source.parent, source.name, txt_name, allow_missing)
    try:
        result.source_zip = rename_processed_zip(source)
    except OSError:
        result.source_zip = source
        result.source_warning = ("El PDF y el TXT se generaron correctamente, pero no se pudo agregar "
                                 "Surtido al nombre del ZIP. El original conserva su nombre.")
    try:
        with result.report.open("a", encoding="utf-8") as stream:
            stream.write("\nZIP ORIGINAL\n" + str(result.source_zip) + "\n" + (result.source_warning or ""))
    except OSError:
        pass
    return result


def bundle_files(pdf: Path, txt: Path, table: str = "", output_root: Path | None = None,
                 allow_missing=False) -> BundleResult:
    pdf, txt = Path(pdf), Path(txt)
    if pdf.stat().st_size > MAX_PDF or txt.stat().st_size > MAX_TEXT:
        raise ControlError("El PDF o TXT supera el tamaño admitido.")
    return bundle(pdf.read_bytes(), txt.read_bytes(), table, output_root or pdf.parent, pdf.name, txt.name, allow_missing)


def copy_to_nas(result: BundleResult) -> BundleResult:
    from respaldo import backup_labels, CopyResult
    try:
        copied = backup_labels(result.labels_file)
    except Exception:
        copied = CopyResult(warning="No se pudo entrar a la carpeta de impresiones. "
                            "El PDF y el TXT se generaron correctamente en la carpeta de salida.")
    result.nas_copy = copied.path
    result.nas_warning = copied.warning
    try:
        with result.report.open("a", encoding="utf-8") as stream:
            stream.write("\nCOPIA DEL TXT AL NAS\n" + (copied.path or copied.warning or "") + "\n")
    except OSError:
        pass
    return result
