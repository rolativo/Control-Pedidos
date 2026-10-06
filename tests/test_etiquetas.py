from collections import Counter
import os
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

import fitz

from control import ControlError, Order, Product
from etiquetas import (BLOCK, TableRow, bundle_files, bundle_zip, label_identifiers,
                       parse_table, transform_labels)
from generador import prepare_generator
from test_control import fixture, entries


def label(identifier="2000018000000001", kind="Pack ID", compact=False):
    y = 100 if compact else 120
    extra = "" if compact else "^FX LAST CLUSTER ^FS\n"
    return ("^XA\n^MCY\n^CI28\n^LH5,15\n"
            "^FO120,20^A0N,24,24^FH^FDRemitente #1234^FS\n"
            "^FO120,43^A0N,24,24^FB550,2,0,L^FH^FDCarr_2E prueba^FS\n"
            f"^FO120,{y}^A0N,24,24^FD{kind}: {identifier[:5]}^FS\n"
            f"^FO272,{y-3}^A0N,27,27^FD{identifier[5:13]}^FS\n"
            f"^FO272,{y-2}^A0N,27,27^FD{identifier[5:13]}^FS\n"
            f"^FO379,{y}^A0N,24,24^FD{identifier[13:]}^FS\n" + extra +
            "^FO95,382^A0N,35,35^FD99999999999^FS\n"
            "^FO100,500^BCN,160,N,N,N^FD>:99999999999^FS\n"
            "^FO30,962^A0N,26,26^FDDestinatario de prueba^FS\n^XZ")


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.pdf = self.folder / "original.pdf"
        self.txt = self.folder / "etiquetas.txt"
        self.output = self.folder / "resultados"
        self.order = Order("2000019000000001", "2000018000000001",
                           [Product("SKU-A", 2, "Producto de prueba")])
        self.rows = [TableRow(self.order.pack_id, 40, "SKU-A")]

    def test_excel_and_markdown_tables(self):
        excel = "/2000018000000001\t40\tSKU-A\n2000018000000001\t100\tSKU-A"
        markdown = ("| Pack ID | Cantidad | SKU |\n|---|---|---|\n"
                    "| /2000018000000001 | 40 | SKU-A |\n| /2000018000000001 | 100 | SKU-A |")
        self.assertEqual(parse_table(excel), parse_table(markdown))
        self.assertEqual(len(parse_table(excel)), 2)

    def test_bad_rows_cannot_be_silently_skipped(self):
        for text in ["", "2000018000000001\t4.0\tSKU-A", "bad id\t1\tSKU-A",
                     "2000018000000001\t1\tA^XZ", "2000018000000001\t-3\tSKU-A",
                     "2000018000000001\t1"]:
            with self.subTest(text=text), self.assertRaises(ControlError):
                parse_table(text)

    def test_split_id_and_duplicate_print_fragments(self):
        self.assertEqual(label_identifiers(label()), [("Pack ID", self.order.pack_id)])
        self.assertEqual(label_identifiers(label(self.order.sale, "Venta")), [("Venta", self.order.sale)])

    def test_compact_label_does_not_append_shipping_number(self):
        self.assertEqual(label_identifiers(label(compact=True)), [("Pack ID", self.order.pack_id)])

    def test_configuration_block_kept_and_not_numbered(self):
        orders = [self.order, Order("2000019000000002", "2000018000000002",
                                   [Product("SKU-B", 1, "Segundo")])]
        rows = self.rows + [TableRow("2000018000000002", 10, "SKU-B")]
        original = label() + "\n^XA^MCY^XZ\n" + label("2000018000000002")
        result = transform_labels(original, orders, rows)
        self.assertEqual(result.configuration_blocks, 1)
        self.assertIn("^XA^MCY^XZ", result.text)
        self.assertEqual([r.number for r in result.labels], [1, 2])
        self.assertEqual(result.text.count("^FX NUMERO_CONSECUTIVO"), 2)

    def test_order_number_comes_from_pdf_even_when_labels_reordered(self):
        second = Order("2000019000000002", "2000018000000002", [Product("SKU-B", 1, "Segundo")])
        result = transform_labels(label(second.pack_id) + label(), [self.order, second],
                                  self.rows + [TableRow(second.sale, 10, "SKU-B")])
        self.assertEqual([r.number for r in result.labels], [2, 1])

    def test_table_units_do_not_replace_pdf_quantities(self):
        fixture(self.pdf, [entries()])
        self.txt.write_text(label(), encoding="utf-8")
        result = bundle_files(self.pdf, self.txt, "/2000018000000001\t40\tSKU-A", self.output)
        with fitz.open(result.pdf) as pdf:
            text = pdf[0].get_text()
        self.assertIn("×2", text)
        self.assertNotIn("×40", text)
        self.assertIn("^FD40/SKU-A^FS", result.labels_file.read_text())

    def test_original_barcode_receiver_and_field_values_preserved(self):
        original = label()
        result = transform_labels(original, [self.order], self.rows)
        fields = Counter(re.findall(r"\^FD(.*?)\^FS", original, re.S))
        output_fields = Counter(re.findall(r"\^FD(.*?)\^FS", result.text, re.S))
        self.assertFalse(fields - output_fields)
        self.assertIn("^FO100,500^BCN,160,N,N,N^FD>:99999999999^FS", result.text)

    def test_reprocessing_does_not_duplicate_added_fields(self):
        first = transform_labels(label(), [self.order], self.rows)
        second = transform_labels(first.text, [self.order], self.rows)
        self.assertEqual(second.text.count("^FX NUMERO_CONSECUTIVO"), 1)
        self.assertEqual(second.text.count("^FX DATOS_PACK"), 1)
        self.assertEqual(second.text.count("^FD40/SKU-A^FS"), 1)

    def test_unknown_id_missing_sku_and_missing_label_fail(self):
        for text, rows in [(label("2000018000000099"), self.rows),
                           (label(), []), ("^XA^MCY^XZ", self.rows),
                           ("^XA^FO1,1^FDdireccion sin ID^FS^XZ", self.rows)]:
            with self.subTest(text=text), self.assertRaises(ControlError):
                transform_labels(text, [self.order], rows)

    def test_extra_table_rows_reported(self):
        extra = TableRow("2000018000000099", 1, "SKU-EXTRA")
        result = transform_labels(label(), [self.order], self.rows + [extra])
        self.assertEqual(result.unused_rows, [extra])
        self.assertNotIn("SKU-EXTRA", result.text)

    def test_sku_repeats_and_table_order_preserved(self):
        self.order.products.append(Product("SKU-A", 1, "100 unidades"))
        result = transform_labels(label(), [self.order], self.rows + [TableRow(self.order.sale,100,"SKU-A")])
        self.assertEqual(result.labels[0].text, "40/SKU-A /100/SKU-A")

    def test_zip_without_extracting_member_paths(self):
        fixture(self.pdf, [entries()])
        archive = self.folder / "descarga.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../../original.pdf", self.pdf.read_bytes())
            z.writestr("../../etiquetas.txt", label())
        result = bundle_zip(archive, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertTrue(result.pdf.exists())
        self.assertTrue(result.labels_file.exists())
        second = bundle_zip(archive, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertNotEqual(result.folder, second.folder)

    def test_bundle_validation_failure_publishes_nothing(self):
        fixture(self.pdf, [entries()])
        self.txt.write_text(label("2000018000000099"), encoding="utf-8")
        with self.assertRaises(ControlError):
            bundle_files(self.pdf, self.txt, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertFalse(self.output.exists())

    def test_generator_scripts_have_matching_names_and_are_persistent(self):
        bat = prepare_generator(self.folder)
        self.assertIn('Generador.ps1', bat.read_text())
        self.assertTrue((bat.parent / "Generador.ps1").is_file())
        self.assertEqual(bat, prepare_generator(self.folder))
        bat.write_text("archivo modificado")
        alternate = prepare_generator(self.folder)
        self.assertNotEqual(bat, alternate)
        self.assertEqual(bat.read_text(), "archivo modificado")

    def test_real_35_labels_if_provided(self):
        sample, table_path = os.environ.get("CONTROL_SAMPLE_ZPL"), os.environ.get("CONTROL_SAMPLE_TABLE")
        if not sample or not table_path:
            self.skipTest("Muestra real opcional; no se incluye en GitHub")
        result = bundle_files(Path(os.environ["CONTROL_SAMPLE_PDF"]), Path(sample),
                              Path(table_path).read_text(), self.output)
        self.assertEqual((result.orders,result.labels,result.pages,result.unused_rows), (35,35,2,3))
        zpl = result.labels_file.read_text()
        numbers = [int(n) for n in re.findall(r"\^FX NUMERO_CONSECUTIVO (\d+)", zpl)]
        self.assertEqual(numbers, list(range(1,36)))
        self.assertIn("^XA^MCY^XZ", zpl)
        original = Path(sample).read_text()
        self.assertFalse(Counter(re.findall(r"\^FD(.*?)\^FS",original,re.S)) -
                         Counter(re.findall(r"\^FD(.*?)\^FS",zpl,re.S)))


if __name__ == "__main__":
    unittest.main()
