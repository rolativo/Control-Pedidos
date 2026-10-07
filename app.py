"""Ventana en español y entrada opcional de archivos por línea de comandos."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from control import ControlError, convert
from diagnostico import record_error, install_handlers, startup_error


def open_path(path: Path):
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Application:
    def __init__(self, root: tk.Tk, initial_files: list[str] | None = None, container=None):
        self.root = root
        self.events = queue.Queue()
        self.outputs: dict[str, Path] = {}
        self.errors: dict[str, str] = {}
        self.busy = False
        self.folder: Path | None = None
        root.title("Control de pedidos · Mercado Libre")
        root.geometry("880x530")
        root.minsize(700, 420)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TButton", padding=8)
        style.configure("Treeview", rowheight=28)
        frame = ttk.Frame(container if container is not None else root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Control de pedidos", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Selecciona tus PDF. El control se genera automáticamente.",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 15))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.select_button = ttk.Button(buttons, text="Seleccionar PDF", command=self.select)
        self.select_button.pack(side="left")
        self.folder_button = ttk.Button(buttons, text="Elegir carpeta de salida", command=self.choose_folder)
        self.folder_button.pack(side="left", padx=8)
        self.location = tk.StringVar(value="Se guardará junto a cada PDF original.")
        ttk.Label(frame, textvariable=self.location, wraplength=800).pack(anchor="w", pady=(8, 12))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("file", "status", "orders", "pages"),
                                  show="headings", selectmode="browse")
        for column, title, width in [("file", "Archivo", 350), ("status", "Estado", 210),
                                     ("orders", "Pedidos", 80), ("pages", "Hojas", 90)]:
            self.table.heading(column, text=title)
            self.table.column(column, width=width, anchor="w" if column in ("file", "status") else "center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self.show_details)
        self.table.bind("<Double-1>", lambda event: self.open_selected())
        self.detail = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.detail, wraplength=810).pack(anchor="w", pady=10)
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")
        self.open_button = ttk.Button(bottom, text="Abrir control", command=self.open_selected, state="disabled")
        self.open_button.pack(side="left")
        self.explore_button = ttk.Button(bottom, text="Abrir carpeta", command=self.open_folder, state="disabled")
        self.explore_button.pack(side="left", padx=8)
        self.status = tk.StringVar(value="Listo para seleccionar archivos.")
        ttk.Label(bottom, textvariable=self.status).pack(side="right")
        self.root.after(100, self.poll)
        if initial_files:
            self.root.after(200, lambda: self.process(initial_files))

    def choose_folder(self):
        selected = filedialog.askdirectory(title="Carpeta para los controles resumidos")
        if selected:
            self.folder = Path(selected)
            self.location.set("Se guardará en: " + selected)

    def select(self):
        files = filedialog.askopenfilenames(title="Selecciona uno o varios PDF de Mercado Libre",
                                            filetypes=[("Archivos PDF", "*.pdf")])
        if files:
            self.process(list(files))

    def process(self, files):
        if self.busy:
            return
        self.busy = True
        self.select_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.status.set("Procesando…")
        jobs = []
        for file in files:
            row = self.table.insert("", "end", values=(Path(file).name, "En espera", "", ""))
            jobs.append((row, Path(file)))
        folder = self.folder

        def work():
            for row, file in jobs:
                self.events.put(("start", row, None))
                try:
                    result = convert(file, folder)
                    self.events.put(("success", row, result))
                except ControlError as exc:
                    self.events.put(("error", row, record_error(str(exc), file, folder, exc)))
                except Exception as exc:
                    self.events.put(("error", row, record_error("No se pudo completar la conversión: "
                                      + str(exc), file, folder, exc)))
            self.events.put(("done", "", None))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, row, payload = self.events.get_nowait()
                if kind == "done":
                    self.busy = False
                    self.select_button.configure(state="normal")
                    self.folder_button.configure(state="normal")
                    self.status.set("Proceso terminado.")
                    continue
                values = list(self.table.item(row, "values"))
                if kind == "start":
                    values[1] = "Procesando…"
                elif kind == "success":
                    values[1:] = ["Listo", payload.orders, f"{payload.original_pages} → {payload.pages}"]
                    self.outputs[row] = payload.path
                else:
                    values[1] = "No se generó"
                    self.errors[row] = payload
                    messagebox.showerror("No se generó el control", payload, parent=self.root)
                self.table.item(row, values=values)
                self.table.selection_set(row)
                self.table.see(row)
                self.show_details()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def selected(self):
        selection = self.table.selection()
        return selection[0] if selection else None

    def show_details(self, event=None):
        row = self.selected()
        output = self.outputs.get(row)
        state = "normal" if output else "disabled"
        self.open_button.configure(state=state)
        self.explore_button.configure(state=state)
        self.detail.set(str(output) if output else self.errors.get(row, ""))

    def open_selected(self):
        output = self.outputs.get(self.selected())
        if output:
            open_path(output)

    def open_folder(self):
        output = self.outputs.get(self.selected())
        if output:
            open_path(output.parent)


def main():
    parser = argparse.ArgumentParser(description="Generar controles compactos de Mercado Libre.")
    parser.add_argument("files", nargs="*", help="PDF originales")
    parser.add_argument("--sin-ventana", action="store_true", help="Procesar sin interfaz")
    parser.add_argument("--salida", help="Carpeta para los PDF generados")
    parser.add_argument("--zip", dest="zip_path", help="ZIP con el PDF y el TXT")
    parser.add_argument("--txt", help="TXT de etiquetas, para combinar con un PDF")
    parser.add_argument("--tabla", help="Archivo con las tres columnas copiadas")
    args = parser.parse_args()
    if args.sin_ventana:
        if args.zip_path or args.txt:
            from etiquetas import bundle_zip, bundle_files
            if not args.tabla:
                parser.error("Selecciona el archivo de tabla con --tabla.")
            if args.txt and len(args.files) != 1:
                parser.error("Selecciona un PDF para combinarlo con --txt.")
            try:
                table = Path(args.tabla).read_text(encoding="utf-8-sig")
                result = (bundle_zip(Path(args.zip_path), table, Path(args.salida) if args.salida else None)
                          if args.zip_path else bundle_files(Path(args.files[0]), Path(args.txt), table,
                          Path(args.salida) if args.salida else None))
                if sys.stdout:
                    print(result.folder)
                return 0
            except Exception as exc:
                message = record_error(str(exc), args.zip_path or args.files[0], args.salida, exc)
                if sys.stderr:
                    print(f"ERROR: {message}", file=sys.stderr)
                return 1
        if not args.files:
            parser.error("Selecciona por lo menos un PDF.")
        failed = False
        for file in args.files:
            try:
                result = convert(file, args.salida)
                if sys.stdout:
                    print(result.path)
            except Exception as exc:
                message = record_error(str(exc), file, args.salida, exc)
                if sys.stderr:
                    print(f"ERROR: {message}", file=sys.stderr)
                failed = True
        return 1 if failed else 0
    root = tk.Tk()
    install_handlers(root)
    from unificado import BundlePanel, GeneratorPanel
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    control_tab, bundle_tab, generator_tab = [ttk.Frame(notebook) for _ in range(3)]
    notebook.add(control_tab, text="Solo control PDF")
    notebook.add(bundle_tab, text="Control y etiquetas")
    notebook.add(generator_tab, text="Generador de Excel")
    initial_pdfs = [f for f in args.files if Path(f).suffix.lower() == ".pdf"] if not args.txt else []
    app = Application(root, initial_pdfs, control_tab)
    panel = BundlePanel(root, bundle_tab, open_path)
    generator = GeneratorPanel(root, generator_tab, open_path)
    root.geometry("1000x720")
    root.minsize(960, 660)
    root.title("Control de pedidos · PDF, etiquetas y Generador")
    zipped = args.zip_path or next((f for f in args.files if Path(f).suffix.lower() == ".zip"), None)
    if zipped:
        panel.source_zip = Path(zipped)
        panel.update_source()
    if args.tabla:
        panel.text.insert("1.0", Path(args.tabla).read_text(encoding="utf-8-sig"))
    if zipped or args.txt:
        if args.txt:
            panel.source_pdf = Path(args.files[0]) if args.files else None
            panel.source_txt = Path(args.txt)
            panel.update_source()
        notebook.select(bundle_tab)
    elif initial_pdfs:
        notebook.select(control_tab)
    else:
        notebook.select(bundle_tab)
    if args.salida:
        app.folder = Path(args.salida)
        app.location.set("Se guardará en: " + args.salida)
        panel.output_root = Path(args.salida)
        panel.folder_status.set("Los resultados se guardarán en: " + args.salida)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        startup_error(exc)
        code = 1
    raise SystemExit(code)
