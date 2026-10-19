from collections import Counter
import os
from pathlib import Path
import re
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import fitz

from control import ControlError, Order, Product
from etiquetas import (BLOCK, TableRow, bundle_files, bundle_zip, label_identifiers,
                       parse_table, transform_labels, MissingTableError)
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
        self.assertIn("^FD40/SKU-A^FS", result.labels_file.read_text(encoding="utf-8"))

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

    def test_absent_pdf_sku_uses_extra_table_row_only_on_label_and_reports_it(self):
        lines = entries() + [(261,170,"Funda sin SKU",True), (261,182,"Cantidad: 1",False),
                             (261,194,"Color: Gris",False)]
        fixture(self.pdf,[lines])
        self.txt.write_text(label(),encoding="utf-8")
        table = "/2000018000000001\t40\tSKU-A\n/2000018000000001\t2\tFUNDA-TABLA"
        result = bundle_files(self.pdf,self.txt,table,self.output)
        self.assertIn("40/SKU-A /2/FUNDA-TABLA",result.labels_file.read_text(encoding="utf-8"))
        self.assertIn("no se puede verificar",result.report.read_text(encoding="utf-8"))
        with fitz.open(result.pdf) as doc:
            text = doc[0].get_text()
        self.assertIn("Funda sin SKU",text)
        self.assertNotIn("FUNDA-TABLA",text)
        self.assertNotIn("None",text)

    def test_table_has_priority_even_when_known_skus_or_row_count_differ(self):
        self.order.products.append(Product(None,1,"Funda sin SKU"))
        for rows in [self.rows, [TableRow(self.order.pack_id,1,"ERROR")],
                     self.rows + [TableRow(self.order.pack_id,1,"B"),TableRow(self.order.pack_id,1,"C")]]:
            with self.subTest(rows=rows):
                result = transform_labels(label(),[self.order],rows)
                self.assertEqual(result.labels[0].text," /".join(f"{r.quantity}/{r.sku}" for r in rows))
                self.assertEqual(len(result.differences),1)

    def test_100_smen40ne_replaces_label_data_but_not_pdf_sku_or_quantity(self):
        fixture(self.pdf,[entries(products=[("SMEN40NE-100","1","100 Toallas faciales",[])])])
        self.txt.write_text(label(),encoding="utf-8")
        result = bundle_files(self.pdf,self.txt,"/2000018000000001\t100\tSMEN40NE",self.output)
        self.assertIn("^FD100/SMEN40NE^FS",result.labels_file.read_text(encoding="utf-8"))
        with fitz.open(result.pdf) as doc:
            text = doc[0].get_text()
        self.assertIn("SMEN40NE-100",text)
        self.assertIn("×1",text)
        self.assertNotIn("×100",text)
        self.assertEqual(result.differences,1)
        self.assertIn("100/SMEN40NE",result.report.read_text(encoding="utf-8"))

    def test_changed_sku_still_requires_correct_order_id_and_preserves_shipping_fields(self):
        original = label()
        changed = transform_labels(original,[self.order],[TableRow(self.order.sale,100,"OTRO-SKU")])
        fields = Counter(re.findall(r"\^FD(.*?)\^FS",original,re.S))
        self.assertFalse(fields - Counter(re.findall(r"\^FD(.*?)\^FS",changed.text,re.S)))
        with self.assertRaises(ControlError):
            transform_labels(original,[self.order],[TableRow("2000018000000099",100,"OTRO-SKU")])

    def test_zip_without_extracting_member_paths(self):
        fixture(self.pdf, [entries()])
        archive = self.folder / "descarga.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../../original.pdf", self.pdf.read_bytes())
            z.writestr("../../etiquetas.txt", label())
        result = bundle_zip(archive, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertTrue(result.pdf.exists())
        self.assertTrue(result.labels_file.exists())
        second = bundle_zip(result.source_zip, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertNotEqual(result.folder, second.folder)
        self.assertEqual(second.source_zip,result.source_zip)

    def test_bundle_validation_failure_publishes_nothing(self):
        fixture(self.pdf, [entries()])
        self.txt.write_text(label("2000018000000099"), encoding="utf-8")
        with self.assertRaises(ControlError):
            bundle_files(self.pdf, self.txt, "/2000018000000001\t40\tSKU-A", self.output)
        self.assertFalse(self.output.exists())

    def test_generator_scripts_have_matching_names_and_are_persistent(self):
        bat = prepare_generator(self.folder)
        self.assertIn('Generador.ps1', bat.read_text(encoding="utf-8"))
        self.assertTrue((bat.parent / "Generador.ps1").is_file())
        self.assertEqual(bat, prepare_generator(self.folder))
        bat.write_text("archivo modificado")
        alternate = prepare_generator(self.folder)
        self.assertNotEqual(bat, alternate)
        self.assertEqual(bat.read_text(encoding="utf-8"), "archivo modificado")

    def test_missing_table_lists_actual_sales_and_pack_ids_for_all_missing_orders(self):
        other = Order("2000019000000002",None,[Product("SKU-B",1,"Segundo")])
        with self.assertRaises(MissingTableError) as caught:
            transform_labels(label(),[self.order,other],[])
        message = str(caught.exception)
        for value in [self.order.sale,self.order.pack_id,other.sale,"SKU-A","SKU-B"]:
            self.assertIn(value,message)
        self.assertIn("no la fila de Excel",message)

    def test_invalid_quantity_resolves_pack_id_to_sale_and_shows_exact_pasted_line(self):
        fixture(self.pdf,[entries()])
        self.txt.write_text(label(),encoding="utf-8")
        pasted="/2000018000000001\tmal\tSKU-A"
        with self.assertRaises(ControlError) as caught:
            bundle_files(self.pdf,self.txt,pasted,self.output)
        message = str(caught.exception)
        self.assertIn("Venta: 2000019000000001",message)
        self.assertIn("renglón 1",message)
        self.assertIn(pasted,message)
        self.assertNotIn("renglón 0",message)
        self.assertFalse(self.output.exists())

    def test_number_only_needs_no_rows_preserves_shipping_and_uses_pdf_order(self):
        other = Order("2000019000000002","2000018000000002",[Product("SKU-B",1,"Segundo")])
        original = label(other.pack_id)+"^XA^MCY^XZ"+label()
        result = transform_labels(original,[self.order,other],[],allow_missing=True)
        self.assertEqual([x.number for x in result.labels],[2,1])
        self.assertNotIn("DATOS_PACK",result.text)
        self.assertNotIn("SKU-A",result.text)
        self.assertIn("^XA^MCY^XZ",result.text)
        self.assertFalse(Counter(re.findall(r"\^FD(.*?)\^FS",original,re.S)) -
                         Counter(re.findall(r"\^FD(.*?)\^FS",result.text,re.S)))

    def test_number_only_removes_previously_added_skus_without_duplicating_numbers(self):
        full = transform_labels(label(),[self.order],self.rows)
        numbered = transform_labels(full.text,[self.order],[],allow_missing=True)
        self.assertNotIn("40/SKU-A",numbered.text)
        self.assertNotIn("DATOS_PACK",numbered.text)
        self.assertEqual(numbered.text.count("NUMERO_CONSECUTIVO"),1)
        self.assertIn("^FD>:99999999999^FS",numbered.text)

    def test_number_only_still_rejects_a_label_for_another_sale(self):
        with self.assertRaises(ControlError):
            transform_labels(label("2000018000000099"),[self.order],[],allow_missing=True)

    def test_empty_table_can_number_missing_guides_and_keeps_pdf_products(self):
        fixture(self.pdf,[entries()])
        self.txt.write_text(label(),encoding="utf-8")
        result = bundle_files(self.pdf,self.txt,"",self.output,allow_missing=True)
        self.assertTrue(result.allow_missing)
        self.assertNotIn("SKU-A",result.labels_file.read_text(encoding="utf-8"))
        with fitz.open(result.pdf) as pdf:
            self.assertIn("SKU-A",pdf[0].get_text())
            self.assertIn("×2",pdf[0].get_text())

    def test_missing_guide_only_loses_sku_and_others_keep_pasted_override(self):
        other = Order("2000019000000002","2000018000000002",[Product("SKU-B",1,"Segundo")])
        original = label(other.pack_id)+"^XA^MCY^XZ"+label()
        result = transform_labels(original,[self.order,other],
                                  [TableRow(self.order.sale,100,"SMEN40NE")],allow_missing=True)
        blocks = BLOCK.findall(result.text)
        self.assertNotIn("DATOS_PACK",blocks[0])
        self.assertIn("NUMERO_CONSECUTIVO 02",blocks[0])
        self.assertIn("100/SMEN40NE",blocks[2])
        self.assertIn("NUMERO_CONSECUTIVO 01",blocks[2])
        self.assertEqual(len(result.number_only_orders),1)
        self.assertIn(other.sale,result.number_only_orders[0])
        self.assertNotIn(self.order.sale,result.number_only_orders[0])
        self.assertFalse(Counter(re.findall(r"\^FD(.*?)\^FS",original,re.S)) -
                         Counter(re.findall(r"\^FD(.*?)\^FS",result.text,re.S)))

    def test_valid_table_never_loses_sku_with_allow_missing_enabled(self):
        result = transform_labels(label(),[self.order],self.rows,allow_missing=True)
        self.assertIn("40/SKU-A",result.text)
        self.assertEqual(result.number_only_orders,[])

    def test_invalid_known_row_only_numbers_its_order_and_never_partially_prints_it(self):
        fixture(self.pdf,[entries()+entries(230,sale="2000019000000002",pack="2000018000000002")])
        self.txt.write_text(label()+label("2000018000000002"),encoding="utf-8")
        table = ("2000018000000001\t100\tSMEN40NE\n"
                 "2000018000000002\t5\tVALIDO\n"
                 "2000019000000002\tmal\tOTRO")
        result = bundle_files(self.pdf,self.txt,table,self.output,allow_missing=True)
        blocks = BLOCK.findall(result.labels_file.read_text(encoding="utf-8"))
        self.assertIn("100/SMEN40NE",blocks[0])
        self.assertNotIn("DATOS_PACK",blocks[1])
        self.assertNotIn("VALIDO",blocks[1])
        self.assertIn("NUMERO_CONSECUTIVO 02",blocks[1])
        self.assertEqual(len(result.number_only_orders),1)
        self.assertIn("Venta: 2000019000000002",result.number_only_orders[0])
        self.assertIn("renglón 3",result.report.read_text(encoding="utf-8"))

    def test_unidentifiable_bad_row_cannot_remove_sku_from_an_arbitrary_guide(self):
        fixture(self.pdf,[entries()])
        self.txt.write_text(label(),encoding="utf-8")
        with self.assertRaises(ControlError):
            bundle_files(self.pdf,self.txt,"fila sin identificador",self.output,allow_missing=True)
        self.assertFalse(self.output.exists())

    def make_zip(self):
        fixture(self.pdf,[entries()])
        archive = self.folder / "Original.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr("Control.pdf",self.pdf.read_bytes())
            z.writestr("etiquetas.txt",label())
        return archive

    def test_success_marks_original_zip_and_preserves_bytes_without_overwriting(self):
        archive = self.make_zip()
        data = archive.read_bytes()
        existing = self.folder / "Surtido Original.zip"
        existing.write_bytes(b"existing zip")
        result = bundle_zip(archive,"",self.output,allow_missing=True)
        self.assertFalse(archive.exists())
        self.assertEqual(result.source_zip.name,"Surtido Original (2).zip")
        self.assertEqual(result.source_zip.read_bytes(),data)
        self.assertEqual(existing.read_bytes(),b"existing zip")

    def test_failure_does_not_mark_or_modify_original_zip(self):
        archive = self.make_zip()
        data = archive.read_bytes()
        with self.assertRaises(MissingTableError):
            bundle_zip(archive,"2000018000000099\t1\tOTRO",self.output)
        self.assertEqual(archive.read_bytes(),data)
        self.assertFalse((self.folder / "Surtido Original.zip").exists())

    def test_zip_rename_failure_does_not_cancel_completed_outputs(self):
        archive = self.make_zip()
        with patch("etiquetas.rename_processed_zip",side_effect=PermissionError("solo lectura")):
            result = bundle_zip(archive,"",self.output,allow_missing=True)
        self.assertTrue(result.pdf.exists())
        self.assertTrue(result.labels_file.exists())
        self.assertTrue(archive.exists())
        self.assertIsNotNone(result.source_warning)
        self.assertIn("no se pudo",result.report.read_text(encoding="utf-8"))

    def test_real_35_labels_if_provided(self):
        sample, table_path = os.environ.get("CONTROL_SAMPLE_ZPL"), os.environ.get("CONTROL_SAMPLE_TABLE")
        if not sample or not table_path:
            self.skipTest("Muestra real opcional; no se incluye en GitHub")
        result = bundle_files(Path(os.environ["CONTROL_SAMPLE_PDF"]), Path(sample),
                              Path(table_path).read_text(encoding="utf-8"), self.output)
        self.assertEqual((result.orders,result.labels,result.pages,result.unused_rows), (35,35,2,3))
        zpl = result.labels_file.read_text(encoding="utf-8")
        numbers = [int(n) for n in re.findall(r"\^FX NUMERO_CONSECUTIVO (\d+)", zpl)]
        self.assertEqual(numbers, list(range(1,36)))
        self.assertIn("^XA^MCY^XZ", zpl)
        original = Path(sample).read_text(encoding="utf-8")
        self.assertFalse(Counter(re.findall(r"\^FD(.*?)\^FS",original,re.S)) -
                         Counter(re.findall(r"\^FD(.*?)\^FS",zpl,re.S)))


if __name__ == "__main__":
    unittest.main()
