"""Formatos antiguos/nuevos y cruces por número de guía, sin datos de clientes."""
from collections import Counter
from pathlib import Path
import re
import tempfile
import unittest

import fitz

from control import ControlError, Order, Product, read_orders, convert
from etiquetas import (BLOCK, TableRow, parse_table, transform_labels, bundle_files,
                       label_identifiers, MissingTableError)
from test_control import entries, fixture
from test_etiquetas import label


def shipping_entries(y=95, shipping="48580000001", **kwargs):
    result = entries(y, sale=None, pack=None, **kwargs)
    result.append((31,y+12,"Envio: " + shipping,False))
    return result


def shipping_label(shipping="48580000001"):
    # Mismo formato que la cabecera nueva: 6 + 5 dígitos, segunda parte en negrita doble.
    return label(shipping,"Envío")


class ShippingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.pdf = self.folder / "source.pdf"
        self.txt = self.folder / "source.txt"
        self.output = self.folder / "output"
        self.first = Order(products=[Product("SKU-A",2,"Prueba")],shipping_id="48580000001")
        self.second = Order(products=[Product("SKU-B",1,"Prueba")],shipping_id="48580000002")

    def test_pdf_mixed_old_new_formats_and_source_counts(self):
        fixture(self.pdf,[shipping_entries()+entries(230)])
        orders,pages = read_orders(self.pdf)
        self.assertEqual((len(orders),pages),(2,1))
        self.assertEqual(orders[0].shipping_id,"48580000001")
        self.assertIsNone(orders[0].sale)
        self.assertEqual(orders[1].sale,"2000019000000001")
        result = convert(self.pdf,self.output)
        with fitz.open(result.path) as pdf:
            text = "".join(p.get_text() for p in pdf)
        self.assertIn("Guía / Envío: 48580000001",text)
        self.assertIn("Venta: 2000019000000001",text)
        self.assertIn("×2",text)

    def test_three_id_fields_stay_in_one_order_and_shipping_continues_across_pages(self):
        first = entries()+[(31,131,"Envío: 48580000001",False)]
        fixture(self.pdf,[first])
        orders,_=read_orders(self.pdf)
        self.assertEqual(len(orders),1)
        self.assertEqual(orders[0].shipping_id,"48580000001")
        fixture(self.folder / "multi.pdf",[shipping_entries(),shipping_entries()])
        orders,_=read_orders(self.folder / "multi.pdf")
        self.assertEqual(len(orders),1)
        self.assertEqual(len(orders[0].products),2)

    def test_unknown_pdf_order_error_shows_its_own_sku_and_title(self):
        fixture(self.pdf,[entries()+entries(230,sale=None,pack=None,
                         products=[("OTRO-SKU","5","Articulo identificable",[])])])
        with self.assertRaises(ControlError) as caught:
            read_orders(self.pdf)
        self.assertIn("OTRO-SKU",str(caught.exception))
        self.assertIn("Articulo identificable",str(caught.exception))
        self.assertNotIn("SKU: SKU-A",str(caught.exception))

    def test_bad_pdf_quantity_includes_shipping_and_sku(self):
        fixture(self.pdf,[shipping_entries(products=[("SKU-ERROR","mal","Articulo",[])])])
        with self.assertRaises(ControlError) as caught:
            read_orders(self.pdf)
        self.assertIn("48580000001",str(caught.exception))
        self.assertIn("SKU-ERROR",str(caught.exception))

    def test_four_columns_headers_and_empty_sale_preserve_the_guide(self):
        table = ("Venta\tCantidad\tSKU\tNúmero de guía\n"
                 "2000019000000001\t100\tSMEN40NE\t48580000001\n"
                 "\t2\tSKU-B\t48580000002")
        rows = parse_table(table)
        self.assertEqual(rows,[TableRow("2000019000000001",100,"SMEN40NE","48580000001"),
                               TableRow("",2,"SKU-B","48580000002")])
        self.assertEqual(parse_table("| Venta | Cantidad | SKU | Guía |\n|---|---|---|---|\n"
                                     "| | 2 | SKU-B | 48580000002 |"),[rows[1]])
        self.assertEqual(parse_table("48580000001\t1\tSKU-A"),[TableRow("48580000001",1,"SKU-A")])

    def test_new_zpl_split_shipping_and_original_fields_preserved(self):
        original=shipping_label()
        self.assertEqual(label_identifiers(original),[("Número de guía / Envío","48580000001")])
        result=transform_labels(original,[self.first],[TableRow("2000019000000001",100,"SMEN40NE","48580000001")])
        self.assertIn("100/SMEN40NE",result.text)
        self.assertIn("NUMERO_CONSECUTIVO 01",result.text)
        fields=lambda t:Counter(re.findall(r"\^FD(.*?)\^FS",t,re.S))
        self.assertFalse(fields(original)-fields(result.text))

    def test_table_bridges_old_pdf_to_new_label_and_new_pdf_to_old_label(self):
        old=Order("2000019000000001","2000018000000001",[Product("SKU-A",2,"Prueba")])
        rows=[TableRow(old.sale,20,"CAMBIADO","48580000001")]
        self.assertIn("20/CAMBIADO",transform_labels(shipping_label(),[old],rows).text)
        self.assertIn("20/CAMBIADO",transform_labels(label(old.sale,"Venta"),[self.first],rows).text)

    def test_conflicting_sale_and_guide_rejected_with_both_order_details(self):
        old=Order("2000019000000001",products=[Product("SKU-A",1,"Uno")])
        with self.assertRaises(ControlError) as caught:
            transform_labels(label(old.sale,"Venta")+shipping_label(),[old,self.first],
                             [TableRow(old.sale,1,"SKU-C","48580000001")])
        message=str(caught.exception)
        for value in (old.sale,"48580000001","SKU-C","SKU-A"):
            self.assertIn(value,message)

    def test_missing_only_one_guide_preserves_other_pasted_values(self):
        result=transform_labels(shipping_label()+shipping_label(self.second.shipping_id),
                                [self.first,self.second],
                                [TableRow("2000019000000001",100,"SMEN40NE",self.first.shipping_id)],
                                allow_missing=True)
        blocks=BLOCK.findall(result.text)
        self.assertIn("100/SMEN40NE",blocks[0])
        self.assertNotIn("DATOS_PACK",blocks[1])
        self.assertIn("NUMERO_CONSECUTIVO 02",blocks[1])
        self.assertEqual(len(result.number_only_orders),1)
        self.assertIn(self.second.shipping_id,result.number_only_orders[0])

    def test_missing_table_error_includes_guide_and_sku(self):
        with self.assertRaises(MissingTableError) as caught:
            transform_labels(shipping_label(),[self.first],[])
        self.assertIn(self.first.shipping_id,str(caught.exception))
        self.assertIn("SKU-A",str(caught.exception))

    def test_bad_table_reports_pasted_sale_guide_sku_and_pdf_sku(self):
        fixture(self.pdf,[shipping_entries()])
        self.txt.write_text(shipping_label(),encoding="utf-8")
        table="2000019000000001\tmal\tSKU-PEGADO\t48580000001"
        with self.assertRaises(ControlError) as caught:
            bundle_files(self.pdf,self.txt,table,self.output)
        for value in ("2000019000000001","48580000001","SKU-PEGADO","SKU-A","mal"):
            self.assertIn(value,str(caught.exception))
        self.assertNotIn("renglón",str(caught.exception))

    def test_invalid_quantity_can_number_only_that_guide_while_keeping_its_id_bridge(self):
        fixture(self.pdf,[entries()+shipping_entries(230,shipping=self.second.shipping_id)])
        self.txt.write_text(shipping_label()+shipping_label(self.second.shipping_id),encoding="utf-8")
        table=("2000019000000001\tmal\tSKU-A\t48580000001\n"
               "2000019000000002\t20\tSKU-B\t48580000002")
        result=bundle_files(self.pdf,self.txt,table,self.output,allow_missing=True)
        blocks=BLOCK.findall(result.labels_file.read_text(encoding="utf-8"))
        self.assertNotIn("DATOS_PACK",blocks[0])
        self.assertIn("20/SKU-B",blocks[1])
        self.assertEqual(len(result.number_only_orders),1)

    def test_many_skus_share_same_guide_and_one_consecutive(self):
        rows=[TableRow("2000019000000001",100,"SMEN40NE","48580000001"),
              TableRow("2000019000000001",3,"SKU-B","48580000001")]
        result=transform_labels(shipping_label(),[self.first],rows)
        self.assertEqual(len(result.labels),1)
        self.assertEqual(result.labels[0].text,"100/SMEN40NE /3/SKU-B")
        self.assertEqual(result.text.count("NUMERO_CONSECUTIVO"),1)


if __name__ == "__main__":
    unittest.main()
