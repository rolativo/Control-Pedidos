"""Control compacto de pedidos. No requiere cuentas ni servicios en línea."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import os
import re
import tempfile

import fitz
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


class ControlError(Exception):
    """Error legible que impide publicar un resultado incompleto."""


@dataclass
class Product:
    sku: str
    quantity: int | None
    description: str
    variants: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Order:
    sale: str | None = None
    pack_id: str | None = None
    products: list[Product] = field(default_factory=list)


@dataclass
class Result:
    path: Path
    orders: int
    products: int
    units: int
    original_pages: int
    pages: int


@dataclass
class Line:
    x: float
    y: float
    text: str
    bold: bool
    page: int


def clean(text: str) -> str:
    return " ".join(text.split())


def get_lines(page: fitz.Page) -> list[Line]:
    result = []
    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
        for row in block.get("lines", []):
            spans = [s for s in row["spans"] if s["text"].strip()]
            text = clean("".join(s["text"] for s in row["spans"]))
            if text:
                if "\ufffd" in text:
                    raise ControlError(f"Página {page.number + 1}: texto ilegible en el PDF.")
                result.append(Line(row["bbox"][0], row["bbox"][1], text,
                                   bool(spans) and all(s["flags"] & 16 for s in spans),
                                   page.number + 1))
    return sorted(result, key=lambda l: (round(l.y, 1), l.x))


META = re.compile(r"^(Pack\s*ID|Venta)\s*:\s*(.*)$", re.I)
FIELD = re.compile(r"^([^:]{1,65}):\s*(.*)$")
OPAQUE = re.compile(r"^[A-Z0-9-]{10,}$")


def page_sections(lines: list[Line], page_number: int):
    headings = [l for l in lines if l.text.casefold() == "productos"]
    if len(headings) != 1:
        raise ControlError(f"Página {page_number}: no se reconoce la tabla de pedidos. "
                           "No se generó un archivo nuevo.")
    heading = headings[0]
    boundary = heading.x - 2
    body = [l for l in lines if l.y > heading.y + 8]
    left = [l for l in body if l.x < boundary]
    right = [l for l in body if l.x >= boundary]
    groups = []
    previous_meta_y = -1000.0
    for line in left:
        match = META.match(line.text)
        if not match:
            continue
        label, value = match.groups()
        if not re.fullmatch(r"\d{8,25}", value):
            raise ControlError(f"Página {page_number}: {label} no se pudo leer: {value!r}.")
        kind = "pack_id" if label.lower().startswith("pack") else "sale"
        if (groups and not getattr(groups[-1]["order"], kind)
                and line.y - previous_meta_y < 40
                and not any(previous_meta_y < l.y < line.y and l.bold
                            and OPAQUE.fullmatch(l.text) for l in left)):
            group = groups[-1]
        else:
            candidates = [l for l in left if OPAQUE.fullmatch(l.text)
                          and l.bold and 0 < line.y - l.y < 28]
            # Los identificadores alfanuméricos marcan el comienzo de la fila,
            # pero nunca se imprimen en el resultado.
            titles = [l for l in right if l.bold and 0 <= line.y - l.y < 36
                      and not l.text.lower().startswith("sku:")]
            start = (candidates[-1].y - 1 if candidates else
                     min(l.y for l in titles) - 1 if titles else line.y - 24)
            group = {"start": start, "order": Order(), "lines": []}
            groups.append(group)
        setattr(group["order"], kind, value)
        previous_meta_y = line.y
    for marker in (l for l in left if l.bold and OPAQUE.fullmatch(l.text)):
        if not any(abs(group["start"] - marker.y) < 3 for group in groups):
            raise ControlError(f"Página {page_number}: hay un pedido sin Venta ni Pack ID "
                               "que no se puede identificar.")
    prefix = []
    for line in right:
        eligible = [g for g in groups if line.y >= g["start"]]
        if eligible:
            eligible[-1]["lines"].append(line)
        else:
            prefix.append(line)
    return groups, prefix


def parse_products(lines: list[Line], identity: str) -> list[Product]:
    products: list[Product] = []
    title: list[str] = []
    current: Product | None = None
    previous: Line | None = None
    last_field: str | None = None
    quantity_seen = False

    def finish():
        nonlocal current, quantity_seen
        if current is not None:
            if not current.description:
                raise ControlError(f"Pedido {identity}: no se pudo leer el nombre de {current.sku}.")
            products.append(current)
            current = None
            quantity_seen = False

    for line in lines:
        match = FIELD.match(line.text)
        key = clean(match.group(1)).casefold() if match else None
        value = clean(match.group(2)) if match else ""
        if key == "sku":
            finish()
            if not value or re.search(r"\s", value):
                raise ControlError(f"Página {line.page}, pedido {identity}: SKU ilegible.")
            current = Product(value, None, clean(" ".join(title)))
            title = []
            last_field = "sku"
        elif key == "cantidad":
            if current is None or title or quantity_seen or not re.fullmatch(r"[1-9]\d*", value):
                raise ControlError(f"Página {line.page}, pedido {identity}: cantidad sin reconocer "
                                   f"o sin SKU correcto ({line.text}).")
            current.quantity = int(value)
            quantity_seen = True
            last_field = "cantidad"
        elif match and not line.bold:
            if current is None or title or not value:
                raise ControlError(f"Página {line.page}, pedido {identity}: variante sin reconocer "
                                   f"({line.text}).")
            current.variants.append((clean(match.group(1)), value))
            last_field = "variant"
        elif line.bold or current is None or title:
            if (title and previous and line.page == previous.page
                    and line.y - previous.y > 14):
                raise ControlError(f"Página {line.page}, pedido {identity}: "
                                   "hay un producto cuya descripción no tiene SKU.")
            if current is not None:
                finish()
            title.append(line.text)
            last_field = "title"
        elif (last_field == "variant" and previous is not None
              and (line.page != previous.page or line.y - previous.y < 13)):
            label, old_value = current.variants[-1]
            current.variants[-1] = (label, clean(old_value + " " + line.text))
        else:
            # También admite títulos sin negritas cuando comienzan otro producto.
            finish()
            title.append(line.text)
            last_field = "title"
        previous = line
    finish()
    if title:
        raise ControlError(f"Pedido {identity}: descripción sin SKU; el PDF podría estar incompleto.")
    if not products:
        raise ControlError(f"Pedido {identity}: no se encontraron sus productos.")
    return products


def read_orders(source: Path) -> tuple[list[Order], int]:
    raw_groups = []
    sku_audit: Counter[str] = Counter()
    qty_audit: Counter[int] = Counter()
    with fitz.open(source) as doc:
        if doc.needs_pass:
            raise ControlError("El PDF tiene contraseña; selecciona un PDF sin contraseña.")
        if not len(doc):
            raise ControlError("El PDF no contiene páginas.")
        page_count = len(doc)
        for page in doc:
            lines = get_lines(page)
            if not lines:
                raise ControlError(f"Página {page.number + 1}: el PDF es una imagen o no tiene "
                                   "texto legible. No se generó un archivo nuevo.")
            groups, prefix = page_sections(lines, page.number + 1)
            if prefix:
                if not raw_groups:
                    raise ControlError(f"Página {page.number + 1}: productos sin pedido identificable.")
                raw_groups[-1]["lines"].extend(prefix)
            raw_groups.extend(groups)
            for line in lines:
                if line.text.lower().startswith("sku:"):
                    sku_audit[clean(line.text.split(":", 1)[1])] += 1
                if line.text.lower().startswith("cantidad:"):
                    value = clean(line.text.split(":", 1)[1])
                    if not re.fullmatch(r"[1-9]\d*", value):
                        raise ControlError(f"Página {page.number + 1}: cantidad ilegible ({value}).")
                    qty_audit[int(value)] += 1
    if not raw_groups:
        raise ControlError("No se detectó ninguna Venta ni Pack ID.")
    orders: list[Order] = []
    by_key: dict[tuple[str, str], dict] = {}
    for group in raw_groups:
        order = group["order"]
        key = ("sale", order.sale) if order.sale else ("pack", order.pack_id)
        if key in by_key:
            target = by_key[key]["order"]
            if target.pack_id and order.pack_id and target.pack_id != order.pack_id:
                raise ControlError(f"Venta {order.sale}: aparecen Pack ID distintos.")
            target.pack_id = target.pack_id or order.pack_id
            by_key[key]["lines"].extend(group["lines"])
        else:
            by_key[key] = group
            orders.append(order)
    for group in by_key.values():
        order = group["order"]
        order.products = parse_products(group["lines"], order.sale or order.pack_id)
    parsed = [p for order in orders for p in order.products]
    if Counter(p.sku for p in parsed) != sku_audit:
        raise ControlError("La validación detectó SKU faltantes o duplicados. No se generó un PDF.")
    if Counter(p.quantity for p in parsed if p.quantity is not None) != qty_audit:
        raise ControlError("La validación detectó cantidades faltantes o duplicadas. No se generó un PDF.")
    return orders, page_count


def register_fonts():
    directory = Path(reportlab.__file__).parent / "fonts"
    for name, filename in [("Control", "Vera.ttf"), ("ControlBold", "VeraBd.ttf")]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(directory / filename)))


def wrap(text: str, width: float, font: str, size: float) -> list[str]:
    result: list[str] = []
    row = ""
    for word in text.split():
        # No truncar SKU ni palabras largas: se parten si es necesario.
        parts = []
        while pdfmetrics.stringWidth(word, font, size) > width:
            cut = 1
            while cut < len(word) and pdfmetrics.stringWidth(word[:cut+1], font, size) <= width:
                cut += 1
            parts.append(word[:cut])
            word = word[cut:]
        parts.append(word)
        for part in parts:
            candidate = (row + " " + part).strip()
            if row and pdfmetrics.stringWidth(candidate, font, size) > width:
                result.append(row)
                row = part
            else:
                row = candidate
    if row:
        result.append(row)
    return result


def content(order: Order, products: list[Product], width: float, continuation: bool = False):
    rows = []
    if continuation:
        rows.append(("Continuación", "Control", 7.2, 9, "left"))
    ids = []
    if order.pack_id:
        ids.append("Pack ID: " + order.pack_id)
    if order.sale:
        ids.append("Venta: " + order.sale)
    combined = " | ".join(ids)
    id_rows = [combined] if pdfmetrics.stringWidth(combined, "Control", 6.8) <= width else ids
    for text in id_rows:
        rows.append((text, "Control", 6.8, 8.2, "left"))
    for i, p in enumerate(products):
        rows.append(("", "Control", 1, 3 if i else 2, "left"))
        qty = f"×{p.quantity}" if p.quantity is not None else ""
        qty_width = pdfmetrics.stringWidth(qty, "ControlBold", 11) + 9 if qty else 0
        sku_rows = wrap(p.sku, width - qty_width, "ControlBold", 10)
        for j, text in enumerate(sku_rows):
            rows.append((text, "ControlBold", 10, 12, "sku:" + qty if j == 0 else "left"))
        if p.variants:
            variants = " · ".join(f"{label}: {value}" for label, value in p.variants)
            for text in wrap(variants, width, "Control", 7.1):
                rows.append((text, "Control", 7.1, 8.5, "left"))
        for text in wrap(p.description, width, "Control", 7.4):
            rows.append((text, "Control", 7.4, 8.7, "left"))
    return rows


def render_pdf(orders: list[Order], destination: Path) -> int:
    register_fonts()
    for order in orders:
        for product in order.products:
            texts = [product.sku, product.description]
            texts.extend(label + value for label, value in product.variants)
            for text in texts:
                if any(ord(char) not in pdfmetrics.getFont("Control").face.charToGlyph
                       for char in text):
                    raise ControlError(f"SKU {product.sku}: el texto tiene caracteres que no se "
                                       "pueden imprimir con la fuente del programa.")
    page_width, page_height = A4
    margin, gap, padding, number_width = 17.0, 9.0, 5.0, 41.0
    column_width = (page_width - margin * 2 - gap) / 2
    text_width = column_width - number_width - padding * 2
    available = page_height - margin * 2 - 9
    pdf = canvas.Canvas(str(destination), pagesize=A4, pageCompression=1)
    pdf.setTitle("Control resumido")
    pdf.setAuthor("Control de pedidos")
    column, y, pages = 0, page_height - margin, 1

    def footer():
        pdf.setFont("Control", 6.5)
        pdf.drawRightString(page_width - margin, 10, f"Página {pages}")

    def advance():
        nonlocal column, y, pages
        if column == 0:
            column = 1
        else:
            footer()
            pdf.showPage()
            column = 0
            pages += 1
        y = page_height - margin

    def height(rows):
        return max(35.0, sum(row[3] for row in rows) + padding * 2)

    def draw(number, rows):
        nonlocal y
        h = height(rows)
        if h > y - margin - 9:
            advance()
        x = margin + column * (column_width + gap)
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setLineWidth(0.55)
        pdf.rect(x, y - h, column_width, h, stroke=1, fill=0)
        # Única línea interna: separa el consecutivo del contenido.
        pdf.line(x + number_width, y, x + number_width, y - h)
        label = f"{number:02d}"
        number_size = 25
        while pdfmetrics.stringWidth(label, "ControlBold", number_size) > number_width - 5:
            number_size -= 1
        pdf.setFont("ControlBold", number_size)
        pdf.drawCentredString(x + number_width / 2, y - padding - number_size, label)
        baseline = y - padding
        for text, font, size, leading, alignment in rows:
            baseline -= leading
            if text:
                pdf.setFont(font, size)
                pdf.drawString(x + number_width + padding, baseline + 1.6, text)
                if alignment.startswith("sku:") and alignment[4:]:
                    pdf.setFont("ControlBold", 11)
                    pdf.drawRightString(x + column_width - padding, baseline + 1.6, alignment[4:])
        y -= h + 4

    for number, order in enumerate(orders, 1):
        rows = content(order, order.products, text_width)
        if height(rows) <= available:
            draw(number, rows)
            continue
        # Si un pedido supera una columna completa, continúa con el MISMO
        # consecutivo. Ningún producto se parte ni recibe otro número.
        part: list[Product] = []
        continuation = False
        for product in order.products:
            candidate = content(order, part + [product], text_width, continuation)
            if height(candidate) > available:
                if not part:
                    raise ControlError(f"Pedido {number:02d}: un producto es demasiado largo "
                                       "para imprimirlo de forma legible.")
                draw(number, content(order, part, text_width, continuation))
                continuation = True
                part = [product]
                if height(content(order, part, text_width, continuation)) > available:
                    raise ControlError(f"Pedido {number:02d}: descripción demasiado larga.")
            else:
                part.append(product)
        if part:
            draw(number, content(order, part, text_width, continuation))
    footer()
    pdf.save()
    return pages


def convert(source: Path | str, destination: Path | str | None = None) -> Result:
    source = Path(source).resolve()
    if not source.is_file():
        raise ControlError("No se encontró el PDF seleccionado.")
    try:
        orders, original_pages = read_orders(source)
    except ControlError:
        raise
    except Exception as exc:
        raise ControlError("No se pudo abrir o interpretar el PDF seleccionado.") from exc
    folder = Path(destination).resolve() if destination else source.parent
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".control-", suffix=".pdf", dir=folder)
    os.close(descriptor)
    temp = Path(temp_name)
    output = None
    try:
        pages = render_pdf(orders, temp)
        # Abrir el PDF acabado antes de publicarlo. Nunca sustituir un archivo
        # existente ni dejar el resultado parcial de un error.
        with fitz.open(temp) as checked:
            if len(checked) != pages:
                raise ControlError("No se pudo validar el PDF generado.")
            text = " ".join(page.get_text() for page in checked)
            for order in orders:
                for identifier in (order.sale, order.pack_id):
                    if identifier and identifier not in text:
                        raise ControlError("Un identificador no quedó en el PDF generado.")
        counter = 0
        while True:
            suffix = "" if counter == 0 else "_" + date.today().isoformat() + (f"_{counter}" if counter > 1 else "")
            candidate = folder / ("Control_resumido" + suffix + ".pdf")
            try:
                # Creación exclusiva: evita carreras y sobrescrituras.
                with candidate.open("xb") as target, temp.open("rb") as src:
                    output = candidate
                    import shutil
                    shutil.copyfileobj(src, target)
                break
            except FileExistsError:
                counter += 1
        return Result(output, len(orders), sum(len(o.products) for o in orders),
                      sum(p.quantity or 0 for o in orders for p in o.products), original_pages, pages)
    except Exception:
        if output:
            output.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
