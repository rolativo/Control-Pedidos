"""Abrir y verificar la interfaz real de Windows, sin ejecutar el BAT."""
from pathlib import Path
import sys
import tempfile
import time
import zipfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_window
from PIL import ImageGrab
from test_control import fixture, entries
from test_etiquetas import label, BLOCK


root = create_window()
try:
    root.update()
    assert root.title() == "El todo poderOSO"
    assert [root.notebook.tab(tab,"text") for tab in root.notebook.tabs()] == ["Principal","Solo control PDF"]
    generator = root.bundle_panel.generator
    assert generator.button.winfo_ismapped()
    assert generator.button.cget("text") == ""
    assert generator.mask.width() == 128
    assert generator.folder_button.cget("text") == "Carpeta"
    with patch("unificado.prepare_generator",return_value=Path("C:/prueba/GENERADOR.bat")) as prepare, \
         patch("unificado.prepare_shortcut") as shortcut, \
         patch.object(generator,"open_path") as opened:
        generator.button.invoke()
        prepare.assert_called_once()
        opened.assert_called_once_with(Path("C:/prueba/GENERADOR.bat"))
        shortcut.assert_called_once()
    generator.bat = None
    with patch("unificado.prepare_generator",return_value=Path("C:/prueba/GENERADOR.bat")) as prepare, \
         patch.object(generator,"open_path") as opened:
        generator.folder_button.invoke()
        prepare.assert_called_once()
        opened.assert_called_once_with(Path("C:/prueba"))
    panel = root.bundle_panel
    assert panel.allow_missing.get() is False
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        pdf = directory / "Control.pdf"
        fixture(pdf,[entries()+entries(230,sale="2000019000000002",pack="2000018000000002")])
        archive = directory / "prueba.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr("Control.pdf",pdf.read_bytes())
            z.writestr("etiquetas.txt",label()+label("2000018000000002"))
        panel.source_zip = archive
        panel.output_root = directory / "salida"
        panel.update_source()
        panel.text.insert("1.0","2000018000000001\t40\tSKU-A")
        with patch("unificado.messagebox.askyesno",return_value=True) as offer, \
             patch("unificado.copy_to_nas",side_effect=lambda result:result):
            panel.start()
            deadline = time.monotonic()+15
            while panel.busy and time.monotonic()<deadline:
                root.update()
                time.sleep(0.01)
            assert not panel.busy
            assert panel.result is not None
            assert panel.result.allow_missing
            offer.assert_called_once()
            assert "Venta: 2000019000000002" in offer.call_args.args[1]
            blocks = BLOCK.findall(panel.result.labels_file.read_text(encoding="utf-8"))
            assert "40/SKU-A" in blocks[0]
            assert "NUMERO_CONSECUTIVO 01" in blocks[0]
            assert "DATOS_PACK" not in blocks[1]
            assert "NUMERO_CONSECUTIVO 02" in blocks[1]
            assert len(panel.result.number_only_orders) == 1
            assert panel.source_zip.name == "Surtido prueba.zip"
        panel.numbers_option.invoke()
        assert not panel.allow_missing.get()
        panel.text.delete("1.0","end")
        panel.source_zip = None
        panel.source_pdf = panel.source_txt = None
        panel.update_source()
    for width,height in [(1040,800),(960,720)]:
        root.geometry(f"{width}x{height}")
        root.update()
        for widget in [generator.button,generator.folder_button,panel.numbers_option,panel.generate,panel.text]:
            assert widget.winfo_ismapped(), f"Widget no visible: {widget} en {width}x{height}"
            assert widget.winfo_rootx()+widget.winfo_width() <= root.winfo_rootx()+root.winfo_width()+1
            assert widget.winfo_rooty()+widget.winfo_height() <= root.winfo_rooty()+root.winfo_height()+1
        assert generator.folder_button.winfo_rooty() >= generator.button.winfo_rooty()+generator.button.winfo_height()
    root.geometry("1040x800")
    root.update()
    bounds=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),
            root.winfo_rooty()+root.winfo_height())
    ImageGrab.grab(bbox=bounds).save("Vista_El_todo_poderOSO.png")
    print("Interfaz verificada: colores, titulo, iconos, dos pestanas y boton directo al BAT.")
finally:
    root.destroy()
