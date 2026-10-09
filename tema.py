"""Colores e iconos de El todo poderOSO."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk


NAME = "El todo poderOSO"
BG = "#191426"
SURFACE = "#291E40"
PURPLE = "#7940B8"
LIME = "#C5FF00"
TEXT = "#F4EEFF"
MUTED = "#CDBADE"
INPUT = "#110D1C"


def asset(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / name


def image(root, name, divisor=1):
    source = tk.PhotoImage(master=root, file=str(asset(name)))
    return source.subsample(divisor, divisor) if divisor > 1 else source


def apply_theme(root):
    root.configure(background=BG)
    root.title(NAME)
    root.geometry("1040x800")
    root.minsize(960, 720)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Brand.TLabel", foreground=LIME, font=("Segoe UI", 25, "bold"))
    style.configure("TButton", background=PURPLE, foreground=TEXT, padding=(12, 9),
                    borderwidth=0, focusthickness=2, focuscolor=LIME)
    style.map("TButton", background=[("disabled", SURFACE), ("pressed", "#51277E"),
              ("active", "#9559D4")], foreground=[("disabled", "#8A769F")])
    style.configure("Accent.TButton", background=LIME, foreground=BG, font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", SURFACE), ("pressed", "#99C600"),
              ("active", "#D7FF60")], foreground=[("disabled", "#8A769F"), ("!disabled", BG)])
    style.configure("Generator.TButton", padding=(12, 4), font=("Segoe UI", 10, "bold"))
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(18, 4, 18, 0))
    style.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(18, 10))
    style.map("TNotebook.Tab", background=[("selected", LIME), ("active", PURPLE)],
              foreground=[("selected", BG), ("active", TEXT)])
    style.configure("Treeview", background=INPUT, fieldbackground=INPUT, foreground=TEXT,
                    rowheight=30, borderwidth=0)
    style.map("Treeview", background=[("selected", PURPLE)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=PURPLE, foreground=TEXT,
                    font=("Segoe UI", 10, "bold"), padding=8)
    style.map("Treeview.Heading", background=[("active", "#9559D4")])
    for direction in ("Vertical", "Horizontal"):
        style.configure(direction + ".TScrollbar", background=PURPLE, troughcolor=INPUT,
                        arrowcolor=LIME, bordercolor=BG)
    root.app_icon = image(root, "app.png")
    root.iconphoto(True, root.app_icon)
    if sys.platform == "win32":
        root.iconbitmap(str(asset("app.ico")))
    header = ttk.Frame(root, padding=(20, 12, 20, 8))
    header.pack(fill="x")
    root.brand_icon = image(root, "app.png", 4)
    ttk.Label(header, image=root.brand_icon).pack(side="left", padx=(0, 14))
    words = ttk.Frame(header)
    words.pack(side="left", fill="x", expand=True)
    ttk.Label(words, text=NAME, style="Brand.TLabel").pack(anchor="w")
    ttk.Label(words, text="Control de pedidos · Etiquetas · Excel", style="Muted.TLabel").pack(anchor="w")
    tk.Frame(root, background=LIME, height=2).pack(fill="x", padx=20, pady=(0, 6))
