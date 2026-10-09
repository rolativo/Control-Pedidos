"""Abrir y verificar la interfaz real de Windows, sin ejecutar el BAT."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_window
from PIL import ImageGrab


root = create_window()
try:
    root.update()
    assert root.title() == "El todo poderOSO"
    assert [root.notebook.tab(tab,"text") for tab in root.notebook.tabs()] == ["Principal","Solo control PDF"]
    generator = root.bundle_panel.generator
    assert generator.button.winfo_ismapped()
    with patch("unificado.prepare_generator",return_value=Path("C:/prueba/GENERADOR.bat")) as prepare, \
         patch("unificado.prepare_shortcut") as shortcut, \
         patch.object(generator,"open_path") as opened:
        generator.button.invoke()
        prepare.assert_called_once()
        opened.assert_called_once_with(Path("C:/prueba/GENERADOR.bat"))
        shortcut.assert_called_once()
    for width,height in [(1040,800),(960,720)]:
        root.geometry(f"{width}x{height}")
        root.update()
        for widget in [generator.button,root.bundle_panel.generate,root.bundle_panel.text]:
            assert widget.winfo_ismapped()
            assert widget.winfo_rootx()+widget.winfo_width() <= root.winfo_rootx()+root.winfo_width()+1
            assert widget.winfo_rooty()+widget.winfo_height() <= root.winfo_rooty()+root.winfo_height()+1
    root.geometry("1040x800")
    root.update()
    bounds=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),
            root.winfo_rooty()+root.winfo_height())
    ImageGrab.grab(bbox=bounds).save("Vista_El_todo_poderOSO.png")
    print("Interfaz verificada: colores, titulo, iconos, dos pestanas y boton directo al BAT.")
finally:
    root.destroy()
