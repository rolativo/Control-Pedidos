"""Paneles para ZIP + tabla + etiquetas y acceso al Generador de Excel."""
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from control import ControlError
from etiquetas import bundle_zip, bundle_files, parse_table, copy_to_nas
from generador import prepare_generator, prepare_shortcut
from diagnostico import record_error
from tema import image, INPUT, TEXT, LIME, PURPLE


class BundlePanel:
    def __init__(self, root, parent, open_path):
        self.root, self.open_path = root, open_path
        self.source_zip = self.source_pdf = self.source_txt = self.output_root = None
        self.result = None
        self.busy = False
        self.events = queue.Queue()
        frame = ttk.Frame(parent, padding=18)
        frame.pack(fill="both", expand=True)
        heading = ttk.Frame(frame)
        heading.pack(fill="x")
        ttk.Label(heading, text="Control y etiquetas", font=("Segoe UI", 19, "bold")).pack(side="left")
        self.generator = GeneratorLauncher(root, heading, open_path)
        self.generator.button.pack(side="right")
        ttk.Label(frame, text="Elige el ZIP de Mercado Libre y pega las tres columnas: "
                  "Pack ID o Venta, Cantidad y SKU.", wraplength=900).pack(anchor="w", pady=(4, 12))
        selectors = ttk.Frame(frame)
        selectors.pack(fill="x")
        self.buttons = []
        for title, command in [("Seleccionar ZIP", self.choose_zip),
                               ("Seleccionar PDF", self.choose_pdf),
                               ("Seleccionar TXT", self.choose_txt),
                               ("Carpeta de salida", self.choose_output)]:
            button = ttk.Button(selectors, text=title, command=command)
            button.pack(side="left", padx=(0, 6))
            self.buttons.append(button)
        self.source_status = tk.StringVar(value="También puedes elegir el PDF y el TXT ya descomprimidos.")
        ttk.Label(frame, textvariable=self.source_status, wraplength=900).pack(anchor="w", pady=(6, 4))
        self.folder_status = tk.StringVar(value="Los resultados se guardarán junto al ZIP o PDF seleccionado.")
        ttk.Label(frame, textvariable=self.folder_status, wraplength=900).pack(anchor="w", pady=(0, 10))
        paste_bar = ttk.Frame(frame)
        paste_bar.pack(fill="x")
        paste = ttk.Button(paste_bar, text="Pegar tabla", command=self.paste)
        paste.pack(side="left")
        self.buttons.append(paste)
        clear = ttk.Button(paste_bar, text="Limpiar tabla", command=self.clear)
        clear.pack(side="left", padx=6)
        self.buttons.append(clear)
        ttk.Label(paste_bar, text="Copia las tres columnas desde Excel o desde la tabla del chat.").pack(side="left", padx=6)
        self.text = ScrolledText(frame, height=13, font=("Consolas", 10), wrap="none", undo=True)
        self.text.configure(background=INPUT, foreground=TEXT, insertbackground=LIME,
                            selectbackground=PURPLE, selectforeground=TEXT, relief="flat",
                            highlightthickness=1, highlightbackground=PURPLE, highlightcolor=LIME)
        self.text.vbar.configure(background=PURPLE, troughcolor=INPUT, activebackground=LIME)
        self.text.pack(fill="both", expand=True, pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.generate = ttk.Button(actions, text="Generar PDF y etiquetas", command=self.start,
                                   style="Accent.TButton")
        self.generate.pack(side="left")
        self.buttons.append(self.generate)
        self.open_buttons = []
        for title, key in [("Abrir control", "pdf"), ("Abrir etiquetas", "labels_file"),
                           ("Abrir carpeta", "folder"), ("Ver revisión", "report")]:
            button = ttk.Button(actions, text=title, state="disabled",
                                command=lambda k=key: self.open_result(k))
            button.pack(side="left", padx=(6, 0))
            self.open_buttons.append(button)
        self.status = tk.StringVar(value="Listo para seleccionar archivos y pegar la tabla.")
        ttk.Label(frame, textvariable=self.status, wraplength=900).pack(anchor="w", pady=(10, 0))
        self.root.after(100, self.poll)

    def update_source(self):
        if self.source_zip:
            self.source_status.set("ZIP: " + str(self.source_zip))
        else:
            self.source_status.set("PDF: " + (str(self.source_pdf) if self.source_pdf else "sin seleccionar")
                                   + "\nTXT: " + (str(self.source_txt) if self.source_txt else "sin seleccionar"))

    def choose_zip(self):
        selected = filedialog.askopenfilename(title="ZIP descargado de Mercado Libre",
                                              filetypes=[("Archivo ZIP", "*.zip")])
        if selected:
            self.source_zip = Path(selected)
            self.source_pdf = self.source_txt = None
            self.update_source()

    def choose_pdf(self):
        selected = filedialog.askopenfilename(title="PDF original de control",
                                              filetypes=[("Archivo PDF", "*.pdf")])
        if selected:
            self.source_pdf = Path(selected)
            self.source_zip = None
            self.update_source()

    def choose_txt(self):
        selected = filedialog.askopenfilename(title="TXT original de etiquetas ZPL",
                                              filetypes=[("Archivo TXT", "*.txt")])
        if selected:
            self.source_txt = Path(selected)
            self.source_zip = None
            self.update_source()

    def choose_output(self):
        selected = filedialog.askdirectory(title="Carpeta para los conjuntos de control y etiquetas")
        if selected:
            self.output_root = Path(selected)
            self.folder_status.set("Los resultados se guardarán en: " + selected)

    def clear(self):
        self.text.delete("1.0", "end")
        self.status.set("Tabla vacía.")

    def paste(self):
        try:
            text = self.root.clipboard_get()
            rows = parse_table(text)
        except (tk.TclError, ControlError) as exc:
            self.show_error(str(exc) if isinstance(exc, ControlError) else
                            "El portapapeles no contiene texto. Copia las tres columnas primero.", exc)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.status.set(f"Tabla pegada: {len(rows)} filas. Se usarán tus SKU y cantidades en las etiquetas.")

    def start(self):
        if self.busy:
            return
        try:
            table = self.text.get("1.0", "end-1c")
            parse_table(table)
            if not self.source_zip and not (self.source_pdf and self.source_txt):
                raise ControlError("Selecciona el ZIP, o selecciona el PDF y el TXT por separado.")
        except ControlError as exc:
            self.show_error(str(exc), exc)
            return
        source_zip, source_pdf, source_txt, output = self.source_zip, self.source_pdf, self.source_txt, self.output_root
        self.busy = True
        self.result = None
        self.text.configure(state="disabled")
        for button in self.buttons + self.open_buttons:
            button.configure(state="disabled")
        self.status.set("Validando los pedidos y preparando el control y las etiquetas…")

        def work():
            try:
                result = (bundle_zip(source_zip, table, output) if source_zip else
                          bundle_files(source_pdf, source_txt, table, output))
                self.events.put((True, copy_to_nas(result)))
            except ControlError as exc:
                self.events.put((False, record_error(str(exc), source_zip or source_pdf, output, exc)))
            except Exception as exc:
                self.events.put((False, record_error("No se pudo completar el conjunto: " + str(exc),
                                                     source_zip or source_pdf, output, exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            success, result = self.events.get_nowait()
            self.busy = False
            self.text.configure(state="normal")
            for button in self.buttons:
                button.configure(state="normal")
            if success:
                self.result = result
                for button in self.open_buttons:
                    button.configure(state="normal")
                message = f"Listo: {result.orders} pedidos, {result.labels} etiquetas y {result.pages} hojas de control."
                if result.unused_rows:
                    message += f" {result.unused_rows} filas de la tabla no aparecen en el PDF; están en Ver revisión."
                if result.differences:
                    message += " Se usaron los SKU y cantidades que pegaste."
                if result.nas_copy:
                    message += "\nCopia del TXT: " + result.nas_copy
                self.status.set(message + "\n" + str(result.folder))
                if result.nas_warning:
                    self.status.set(message + "\n" + result.nas_warning + "\n" + str(result.folder))
                    messagebox.showwarning("Archivos generados · Copia no disponible",
                                           result.nas_warning, parent=self.root)
            else:
                self.status.set(result)
                messagebox.showerror("No se generó el conjunto", result, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_error(self, message, exception=None):
        message = record_error(message, self.source_zip or self.source_pdf,
                               self.output_root, exception)
        self.status.set(message)
        messagebox.showerror("No se pudo continuar", message, parent=self.root)

    def open_result(self, key):
        if self.result:
            self.open_path(getattr(self.result, key))


class GeneratorLauncher:
    def __init__(self, root, parent, open_path):
        self.root, self.open_path = root, open_path
        self.folder = Path.home() / "Documents" / "ControlPedidos"
        self.bat = None
        self.mask = image(root, "mask.png", 6)
        self.button = ttk.Button(parent, text="Generador de Excel", image=self.mask, compound="left",
                                 style="Generator.TButton", command=self.launch)

    def launch(self):
        if sys.platform != "win32":
            messagebox.showinfo("Generador de Excel", "El BAT del Generador se abre en Windows.", parent=self.root)
            return
        try:
            self.bat = prepare_generator(self.folder)
            prepare_shortcut(self.bat)
            self.open_path(self.bat)
        except (ControlError, OSError) as exc:
            messagebox.showerror("No se pudo abrir el Generador",
                                 record_error(str(exc), output=self.folder, exception=exc), parent=self.root)
