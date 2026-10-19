"""Verificar el orden real del PowerShell sin abrir Explorer en el equipo de pruebas."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from generador import prepare_generator


@unittest.skipUnless(sys.platform == "win32", "Prueba del PowerShell de Windows")
class GeneratorCompletionTests(unittest.TestCase):
    def test_folder_is_opened_after_files_exist_and_before_request_to_close(self):
        with tempfile.TemporaryDirectory() as temp:
            bat = prepare_generator(Path(temp))
            environment = os.environ.copy()
            environment["EL_GEN_TEST_DIR"] = str(bat.parent.resolve())
            script = r'''
function Add-Type { param($AssemblyName) throw "usar portapapeles de prueba" }
function Get-Clipboard { param([switch]$Raw) return "SKU-A`t5`nSKU-B`t7" }
function Start-Process {
    param($FilePath, $ArgumentList)
    $d = $env:EL_GEN_TEST_DIR
    if (!(Test-Path (Join-Path $d "lista.pmc")) -or !(Test-Path (Join-Path $d "f5.ahk"))) {
        throw "Se abrio la carpeta antes de crear los archivos"
    }
    if ($ArgumentList -ne ('"{0}"' -f $d)) { throw "Carpeta incorrecta" }
    [System.IO.File]::WriteAllText((Join-Path $d "carpeta-abierta.txt"), "OK")
}
function Read-Host {
    param($Prompt)
    if (!(Test-Path (Join-Path $env:EL_GEN_TEST_DIR "carpeta-abierta.txt"))) {
        throw "No se abrio la carpeta antes de pedir cerrar"
    }
    return ""
}
& (Join-Path $env:EL_GEN_TEST_DIR "Generador.ps1")
'''
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                     "-Command", script], env=environment, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertTrue((bat.parent / "carpeta-abierta.txt").is_file())
            self.assertTrue((bat.parent / "lista.pmc").is_file())
            self.assertTrue((bat.parent / "f5.ahk").is_file())


if __name__ == "__main__":
    unittest.main()
