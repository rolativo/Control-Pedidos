from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from diagnostico import record_error, install_handlers
from control import ControlError
from unificado import BundlePanel


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name).resolve()

    def test_records_cause_without_overwriting_previous_error(self):
        try:
            raise ControlError("Cantidad ilegible")
        except ControlError as exc:
            message = record_error(str(exc),self.folder / "entrada.pdf",exception=exc)
        first = self.folder / "Error_Control.txt"
        contents = first.read_text(encoding="utf-8")
        self.assertIn(str(first),message)
        self.assertIn("ControlError: Cantidad ilegible",contents)
        record_error("Segundo error",output=self.folder)
        self.assertEqual(first.read_text(encoding="utf-8"),contents)
        self.assertIn("Segundo error",(self.folder / "Error_Control_1.txt").read_text(encoding="utf-8"))

    def test_unwritable_output_falls_back_to_source_folder(self):
        blocked = self.folder / "not-a-directory"
        blocked.write_text("keep")
        message = record_error("Fallo",source=self.folder / "entrada.pdf",output=blocked)
        self.assertTrue((self.folder / "Error_Control.txt").is_file())
        self.assertIn(str(self.folder / "Error_Control.txt"),message)
        self.assertEqual(blocked.read_text(),"keep")

    def test_callback_error_is_saved_and_shown(self):
        root = Mock()
        install_handlers(root)
        with patch("diagnostico.record_error",return_value="Detalle y archivo de error") as saved, \
             patch("tkinter.messagebox.showerror") as shown:
            root.report_callback_exception(ValueError,ValueError("Fallo de ventana"),None)
            saved.assert_called_once()
            shown.assert_called_once_with("No se pudo completar la operación",
                                          "Detalle y archivo de error",parent=root)

    def test_empty_table_shows_error_and_saves_log_instead_of_silent_return(self):
        panel = object.__new__(BundlePanel)
        panel.busy = False
        panel.text = Mock()
        panel.text.get.return_value = ""
        panel.source_zip = self.folder / "entrada.zip"
        panel.source_pdf = panel.source_txt = panel.output_root = None
        panel.status = Mock()
        panel.root = Mock()
        with patch("tkinter.messagebox.showerror") as shown:
            panel.start()
            shown.assert_called_once()
        self.assertFalse(panel.busy)
        self.assertIn("tabla está vacía",(self.folder / "Error_Control.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
