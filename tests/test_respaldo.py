from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from respaldo import backup_labels, CopyResult, DESTINATIONS
from etiquetas import BundleResult, copy_to_nas


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name).resolve()
        self.source = self.folder / "etiquetas.txt"
        self.source.write_bytes(b"^XA\n^FD100/SMEN40NE^FS\n^XZ")
        self.when = datetime(2026,10,9,17,12,34)

    def test_primary_gets_only_identical_txt_with_date_and_seconds(self):
        primary, secondary = self.folder / "primario", self.folder / "secundario"
        result = backup_labels(self.source,[primary,secondary],now=self.when)
        target = primary / "2026-10-09_17-12-34.txt"
        self.assertEqual(result.path,str(target))
        self.assertEqual(target.read_bytes(),self.source.read_bytes())
        self.assertEqual(list(primary.iterdir()),[target])
        self.assertFalse(secondary.exists())

    def test_failed_primary_uses_secondary_and_never_overwrites_a_copy(self):
        blocked = self.folder / "bloqueado"
        blocked.write_bytes(b"keep")
        secondary = self.folder / "secundario"
        first = backup_labels(self.source,[blocked,secondary],now=self.when)
        old = Path(first.path).read_bytes()
        self.source.write_bytes(b"new label")
        second = backup_labels(self.source,[blocked,secondary],now=self.when)
        self.assertNotEqual(first.path,second.path)
        self.assertEqual(Path(first.path).read_bytes(),old)
        self.assertEqual(Path(second.path).name,"2026-10-09_17-12-34_01.txt")
        self.assertEqual(Path(second.path).read_bytes(),b"new label")

    def test_both_failures_warn_but_preserve_local_output(self):
        blocked = self.folder / "bloqueado"
        blocked.write_bytes(b"keep")
        result = backup_labels(self.source,[blocked,blocked],now=self.when)
        self.assertIsNone(result.path)
        self.assertIn("se generaron correctamente",result.warning)
        self.assertIn("100/SMEN40NE",self.source.read_text())

    def test_unresponsive_network_attempt_is_terminated_and_fallback_is_attempted(self):
        context = Mock()
        process = context.Process.return_value
        process.is_alive.return_value = True
        with patch("respaldo.mp.get_context",return_value=context):
            result = backup_labels(self.source,DESTINATIONS,timeout=0.1,now=self.when)
        self.assertEqual(context.Process.call_count,2)
        self.assertGreaterEqual(process.terminate.call_count,2)
        self.assertIsNotNone(result.warning)

    def test_copy_warning_is_reported_without_turning_generation_into_error(self):
        report = self.folder / "Revision.txt"
        report.write_text("Archivos generados\n",encoding="utf-8")
        result = BundleResult(self.folder,self.folder / "Control_resumido.pdf",self.source,report,1,1,1,0)
        with patch("respaldo.backup_labels",return_value=CopyResult(warning="NAS no disponible")):
            self.assertIs(copy_to_nas(result),result)
        self.assertEqual(result.nas_warning,"NAS no disponible")
        self.assertTrue(self.source.exists())
        self.assertIn("NAS no disponible",report.read_text(encoding="utf-8"))

    def test_unexpected_backup_error_cannot_hide_a_completed_local_bundle(self):
        report = self.folder / "Revision.txt"
        report.write_text("Listo\n",encoding="utf-8")
        result = BundleResult(self.folder,self.folder / "Control_resumido.pdf",self.source,report,1,1,1,0)
        with patch("respaldo.backup_labels",side_effect=RuntimeError("fallo de red")):
            copy_to_nas(result)
        self.assertTrue(self.source.is_file())
        self.assertIsNotNone(result.nas_warning)


if __name__ == "__main__":
    unittest.main()
