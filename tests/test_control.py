import os
from pathlib import Path
import tempfile
import unittest

import fitz

from control import ControlError, Order, Product, convert, read_orders, render_pdf


def fixture(path, pages):
    """PDF de prueba sintético; nunca contiene compradores reales."""
    doc = fitz.open()
    for entries in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_text((30, 65), "Identificacion", fontname="hebo", fontsize=9)
        page.insert_text((249, 65), "Productos", fontname="hebo", fontsize=9)
        for x, y, text, bold in entries:
            page.insert_text((x, y), text, fontname="hebo" if bold else "helv", fontsize=8)
    doc.save(path)
    doc.close()


def entries(y=95, sale="2000019000000001", pack="2000018000000001", products=None):
    result = [(31, y, "ABCDEFGHIJKLMNOPQRSTUV", True)]
    if pack:
        result.append((31, y+12, "Pack ID: " + pack, False))
    if sale:
        result.append((31, y+24, "Venta: " + sale, False))
    for product in products or [("SKU-A", "2", "Producto de prueba", [("Color", "Blanco")])]:
        sku, quantity, title, variants = product
        result.extend([(261, y, title, True), (261, y+12, "SKU: " + sku, False)])
        if quantity is not None:
            result.append((261, y+24, "Cantidad: " + quantity, False))
        for index, (key, value) in enumerate(variants):
            result.append((261, y+36+index*10, key + ": " + value, False))
        y += 75
    return result


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / "original.pdf"
        self.output = self.folder / "salida"

    def test_same_sku_keeps_different_quantities_and_titles(self):
        products = [("MSLG45B-39", "4", "10 Servilletas", [("Color", "Verde")]),
                    ("MSLG45B-39", "1", "100 Servilletas", [("Diseno especial", "Lisa")])]
        fixture(self.source, [entries(products=products)])
        orders, _ = read_orders(self.source)
        self.assertEqual([(p.sku, p.quantity, p.description) for p in orders[0].products],
                         [("MSLG45B-39", 4, "10 Servilletas"), ("MSLG45B-39", 1, "100 Servilletas")])
        result = convert(self.source, self.output)
        self.assertEqual((result.orders, result.products, result.units), (1, 2, 5))

    def test_variants_not_limited_to_a_fixed_whitelist(self):
        fixture(self.source, [entries(products=[("TMPBL", "1", "Toalla de prueba",
                         [("Nombre del diseño", "Microfibra New"), ("Talla", "Unitalla")])])])
        orders, _ = read_orders(self.source)
        self.assertEqual(orders[0].products[0].variants,
                         [("Nombre del diseño", "Microfibra New"), ("Talla", "Unitalla")])

    def test_sale_only_and_pack_only_and_missing_quantity(self):
        fixture(self.source, [entries(pack=None) + entries(220, sale=None,
                    products=[("SIN-CANT", None, "Sin cantidad en origen", [])])])
        result = convert(self.source, self.output)
        orders, _ = read_orders(self.source)
        self.assertIsNone(orders[0].pack_id)
        self.assertIsNone(orders[1].sale)
        self.assertIsNone(orders[1].products[0].quantity)
        with fitz.open(result.path) as doc:
            text = doc[0].get_text()
        self.assertEqual(text.count("Pack ID:"), 1)
        self.assertEqual(text.count("Venta:"), 1)
        self.assertNotIn("None", text)
        self.assertNotIn("×0", text)

    def test_continuation_on_another_source_page(self):
        first = entries()
        second = [(261, 95, "Segundo producto", True),
                  (261, 107, "SKU: SKU-B", False), (261, 119, "Cantidad: 3", False)]
        fixture(self.source, [first, second])
        orders, _ = read_orders(self.source)
        self.assertEqual(len(orders), 1)
        self.assertEqual([p.sku for p in orders[0].products], ["SKU-A", "SKU-B"])

    def test_order_without_opaque_identifier_and_sale_before_pack(self):
        lines = [entry for entry in entries(pack=None) if entry[0] > 200 or entry[2].startswith("Venta:")]
        lines.append((31,131,"Pack ID: 2000018000000001",False))
        fixture(self.source, [lines])
        orders, _ = read_orders(self.source)
        self.assertEqual(len(orders),1)
        self.assertEqual(orders[0].products[0].description,"Producto de prueba")
        self.assertEqual(orders[0].pack_id,"2000018000000001")

    def test_orphan_order_cannot_be_silently_attached_to_previous(self):
        lines = entries() + entries(220,sale=None,pack=None)
        fixture(self.source,[lines])
        with self.assertRaises(ControlError):
            convert(self.source,self.output)

    def test_repeated_sale_and_partial_product_on_next_page(self):
        first = [entry for entry in entries() if not entry[2].startswith(("Cantidad:", "Color:"))]
        second = [(31,95,"ABCDEFGHIJKLMNOPQRSTUV",True),
                  (31,107,"Pack ID: 2000018000000001",False),
                  (31,119,"Venta: 2000019000000001",False),
                  (261,95,"Cantidad: 2",False), (261,107,"Color: Blanco",False)]
        fixture(self.source, [first, second])
        orders, _ = read_orders(self.source)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].products[0].quantity, 2)

    def test_bad_quantity_leaves_no_new_file_and_preserves_existing(self):
        self.output.mkdir()
        existing = self.output / "Control_resumido.pdf"
        existing.write_bytes(b"existing control")
        fixture(self.source, [entries(products=[("SKU-A", "no legible", "Prueba", [])])])
        with self.assertRaises(ControlError):
            convert(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [existing])
        self.assertEqual(existing.read_bytes(), b"existing control")

    def test_product_missing_sku_is_rejected(self):
        lines = entries()
        lines.extend([(261,170,"Producto sin SKU",True),
                      (261,200,"Otro producto",True),
                      (261,212,"SKU: SKU-B",False), (261,224,"Cantidad: 1",False)])
        fixture(self.source, [lines])
        with self.assertRaises(ControlError):
            convert(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_no_overwrite_and_number_restarts_for_each_pdf(self):
        fixture(self.source, [entries()])
        first = convert(self.source, self.output)
        original_bytes = first.path.read_bytes()
        second = convert(self.source, self.output)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.path.read_bytes(), original_bytes)
        with fitz.open(second.path) as doc:
            self.assertIn("01", doc[0].get_text().splitlines())

    def test_120_orders_are_sequential_across_output_pages(self):
        pages = []
        for start in range(0, 120, 7):
            lines = []
            for i in range(start, min(start + 7, 120)):
                lines.extend(entries(95 + (i-start)*95,
                                     sale=str(2000019000000000+i),
                                     pack=str(2000018000000000+i),
                                     products=[(f"SKU-{i}", "1", "Articulo de prueba", [])]))
            pages.append(lines)
        fixture(self.source, pages)
        result = convert(self.source, self.output)
        self.assertEqual(result.orders, 120)
        numbers = []
        with fitz.open(result.path) as doc:
            self.assertGreater(len(doc), 1)
            for page in doc:
                found = []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            if span["font"] == "BitstreamVeraSans-Bold" and span["size"] >= 15:
                                found.append((span["bbox"][0], span["bbox"][1], int(span["text"])))
                numbers.extend(v for x,y,v in sorted(found, key=lambda item: (item[0] > page.rect.width/2,item[1])))
        self.assertEqual(numbers, list(range(1, 121)))

    def test_output_has_only_outer_boxes_and_vertical_lines(self):
        fixture(self.source, [entries(products=[("A", "1", "Primero", []), ("B", "2", "Segundo", [])])])
        result = convert(self.source, self.output)
        with fitz.open(result.path) as doc:
            drawings = doc[0].get_drawings()
            rectangles = [item for d in drawings for item in d["items"] if item[0] == "re"]
            lines = [item for d in drawings for item in d["items"] if item[0] == "l"]
            self.assertEqual(len(rectangles), 1)
            self.assertEqual(len(lines), 1)
            self.assertAlmostEqual(lines[0][1].x, lines[0][2].x)
            self.assertAlmostEqual(doc[0].rect.width, 595.2756, places=2)
            self.assertAlmostEqual(doc[0].rect.height, 841.8898, places=2)

    def test_oversized_order_keeps_one_number_on_all_continuations(self):
        order = Order(sale="2000019000000001", products=[
            Product(f"LARGO-{i}", 1, "Producto de prueba con descripcion comercial") for i in range(100)])
        target = self.folder / "largo.pdf"
        render_pdf([order], target)
        numbers = []
        with fitz.open(target) as doc:
            self.assertGreater(len(doc), 1)
            for page in doc:
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        numbers.extend(span["text"] for span in line["spans"] if span["size"] >= 20)
        self.assertGreater(len(numbers), 1)
        self.assertEqual(set(numbers), {"01"})

    def test_empty_and_corrupt_pdf_fail_without_outputs(self):
        fixture(self.source, [[]])
        with self.assertRaises(ControlError):
            convert(self.source, self.output)
        self.source.write_bytes(b"not a pdf")
        with self.assertRaises(ControlError):
            convert(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_real_sample_if_provided(self):
        sample = os.environ.get("CONTROL_SAMPLE_PDF")
        if not sample:
            self.skipTest("Muestra real opcional, no incluida en el repositorio")
        orders, pages = read_orders(Path(sample))
        self.assertEqual(pages, 5)
        self.assertEqual(len(orders), 35)
        self.assertEqual(sum(len(o.products) for o in orders), 49)
        self.assertEqual(sum(p.quantity or 0 for o in orders for p in o.products), 99)
        self.assertEqual(len(orders[28].products), 8)
        self.assertEqual([(p.sku,p.quantity) for p in orders[4].products],
                         [("MSLG45B-39",4),("MSLG45B-39",1)])
        result = convert(sample, self.output)
        self.assertEqual(result.pages, 2)


if __name__ == "__main__":
    unittest.main()
