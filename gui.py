"""
gui.py
======
Interfaz de escritorio multiplataforma (Windows / macOS / Linux) para
analizar archivos PSD en busca de:
    - Text layers desincronizados (bounds visual vs transform interno).
    - Smart objects compartidos (instancias del mismo asset embebido).

Layout: panel de archivos a la izquierda + panel de detalle a la derecha
(50/50, sin modales).

Concurrencia: ProcessPoolExecutor (cpu_count - 1 procesos) para sortear
el GIL y procesar PSDs realmente en paralelo. Soporta lotes grandes
(30+ archivos) sin bloquear la UI.

Ejecutar:
    python gui.py
"""

import base64
import io
import multiprocessing
import os
import platform
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox
from concurrent.futures import ProcessPoolExecutor
from queue import Empty, Queue
from tkinter import filedialog, ttk

from PIL import Image, ImageDraw

from detector import analyze_psd
from fixer import fix_layers_in_psd
from utils import reveal_in_file_manager, check_node_available

APP_TITLE = "Layer Audit PSD"
APP_VERSION = "2.1.0"


def _asset_path(name):
    """Ruta a un archivo de assets/, funcione en dev o empaquetado (_MEIPASS)."""
    if hasattr(sys, '_MEIPASS'):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'assets', name)


def _apply_dark_titlebar(window):
    """Pinta la barra de título de una ventana Windows en oscuro (DWM).

    Silencioso en plataformas/versiones sin soporte. Se usa tanto en la
    ventana principal como en los popups (Toplevel)."""
    if platform.system() != 'Windows':
        return
    try:
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / Win10)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(attr),
                ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

# Paleta oscura "morado casi negro" (tema v2). clam permite colores custom
# en Win/Mac/Linux. La estructura la da la tipografia y el espaciado; el
# color es acento (violeta), no andamiaje.
BG          = "#120b1e"   # morado casi negro — fondo de pagina (fuera de cards)
SURFACE     = "#1b1330"   # card / panel (morado elevado)
SURFACE_ALT = "#241a3d"   # superficie secundaria (barra de filtros, badges, footer)
BORDER      = "#342a4d"   # separadores 1px e indicadores inactivos
TEXT        = "#ece9f7"   # texto primario (casi blanco con tinte lila)
TEXT_MUTED  = "#9a90b8"   # texto secundario, captions, placeholders
PRIMARY     = "#8b5cf6"   # violeta — acciones primarias, acentos, foco
PRIMARY_HOV = "#a78bfa"   # violeta hover (mas claro)
PRIMARY_DIM = "#4c3a7a"   # violeta bajo enfasis (estado en cola)
OK          = "#34d399"   # verde — estado OK/exito
OK_BG       = "#123227"   # verde fondo pill (oscuro)
ERR         = "#fb7185"   # rojo/rosa — error/problema
ERR_BG      = "#3a1622"   # rojo fondo pill (oscuro)
WARN        = "#fbbf24"   # ambar — operaciones destructivas en curso (Reparando)
WARN_BG     = "#3a2c10"   # ambar fondo pill (oscuro)
SELECTED_BG = "#2a2148"   # fondo de fila seleccionada (tinte violeta)
HOVER_BG    = "#221936"   # fondo de fila en hover

# Grises-violeta para el scrollbar (thumb sobre track oscuro).
SCROLL_THUMB     = "#3f3560"
SCROLL_THUMB_HOV = "#4c3a7a"
SCROLL_THUMB_ACT = "#5b4a8a"

# Botones secundarios: un tono elevado que contrasta tanto sobre SURFACE
# como sobre SURFACE_ALT, para que se lean como botones (no como texto).
BTN_BG  = "#2b2348"
BTN_HOV = "#372c5c"

# Degradado de los botones primarios (violeta → púrpura).
GRAD_1 = (124, 92, 255)   # #7c5cff
GRAD_2 = (168, 85, 247)   # #a855f7

# --- Typography scale ------------------------------------------------------
# Pick the closest role instead of declaring a new ('Segoe UI', N) tuple.
FONT_TITLE     = ('Segoe UI', 13, 'bold')   # panel headings
FONT_SUBTITLE  = ('Segoe UI', 10)           # subtitles, file paths
FONT_BODY_BOLD = ('Segoe UI', 10, 'bold')   # row file name, important labels
FONT_BODY      = ('Segoe UI', 10)           # default text, list items
FONT_CAPTION   = ('Segoe UI', 9)            # status text, secondary metadata
FONT_MICRO     = ('Segoe UI', 8)            # paths, version tag, footnotes
FONT_MONO      = ('Consolas', 9)            # numeric values, layer IDs

# --- Spacing scale (4-px grid) --------------------------------------------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# Estados de analisis por fila
ST_IDLE    = 'idle'
ST_QUEUED  = 'queued'
ST_RUNNING = 'running'
ST_DONE    = 'done'
ST_FIXING  = 'fixing'
ST_FIXED   = 'fixed'


def _default_workers():
    n = (os.cpu_count() or 4) - 1
    return max(2, min(8, n))


def _truncate_path(path, max_len=64):
    """Acorta un path largo manteniendo inicio y final con '…' al medio."""
    if len(path) <= max_len:
        return path
    keep = (max_len - 1) // 2
    return path[:keep] + '…' + path[-keep:]


# ===========================================================================
# ToggleCheck — checkbox custom
# ===========================================================================

def _make_checkbox_img(size, state, master=None):
    """Renderiza la casilla como imagen anti-aliased (supersampling + LANCZOS).

    state: 'on' (violeta con ✓ blanco), 'off' (borde), 'off_hover' (borde
    violeta). El ✓ se dibuja como un trazo suave, no un carácter de fuente,
    así que no se ve dentado como el glifo Unicode.
    """
    scale = 4
    s = size * scale
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(s * 0.30)

    if state == 'on':
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius,
                            fill=_rgb(PRIMARY))
        lw = max(2, int(s * 0.11))
        d.line([(s * 0.26, s * 0.52), (s * 0.43, s * 0.69),
                (s * 0.75, s * 0.31)],
               fill=(255, 255, 255, 255), width=lw, joint='curve')
        # Redondear las puntas del trazo del check.
        r = lw / 2
        for (px, py) in ((s * 0.26, s * 0.52), (s * 0.43, s * 0.69),
                         (s * 0.75, s * 0.31)):
            d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255, 255))
    else:
        border = _rgb(PRIMARY_DIM if state == 'off_hover' else BORDER)
        bw = max(2, int(s * 0.09))
        off = bw / 2
        d.rounded_rectangle([off, off, s - 1 - off, s - 1 - off],
                            radius=radius, outline=border, width=bw,
                            fill=_rgb(SURFACE))

    img = img.resize((size, size), Image.LANCZOS)
    return _pil_to_photo(img, master=master)


class ToggleCheck(tk.Frame):
    """Checkbox legible en tema oscuro, con la casilla renderizada como
    imagen anti-aliased (esquinas y ✓ suaves, sin el dentado del glifo
    Unicode). Usa la misma `tk.BooleanVar`, así que el resto del código no
    cambia.
    """

    _SIZE = 18

    def __init__(self, parent, text, variable, bg):
        super().__init__(parent, bg=bg, cursor='hand2')
        self.var = variable
        self._bg = bg

        self._img_on = _make_checkbox_img(self._SIZE, 'on', master=self)
        self._img_off = _make_checkbox_img(self._SIZE, 'off', master=self)
        self._img_off_hover = _make_checkbox_img(self._SIZE, 'off_hover',
                                                 master=self)

        self.box = tk.Label(self, bg=bg, bd=0, highlightthickness=0)
        self.box.pack(side='left')

        self.lbl = tk.Label(self, text=text, bg=bg, fg=TEXT,
                            font=('Segoe UI', 9), cursor='hand2')
        self.lbl.pack(side='left', padx=(SPACE_SM, 0))

        for w in (self, self.box, self.lbl):
            w.bind('<Button-1>', self._toggle)
            w.bind('<Enter>', self._hover_in)
            w.bind('<Leave>', self._hover_out)

        self._hovering = False
        self._render()

    def _toggle(self, _e=None):
        self.var.set(not bool(self.var.get()))
        self._render()
        return 'break'

    def _render(self):
        if self.var.get():
            self.box.config(image=self._img_on)
        elif self._hovering:
            self.box.config(image=self._img_off_hover)
        else:
            self.box.config(image=self._img_off)

    def _hover_in(self, _e=None):
        self._hovering = True
        self.lbl.config(fg=PRIMARY_HOV)
        self._render()

    def _hover_out(self, _e=None):
        self._hovering = False
        self.lbl.config(fg=TEXT)
        self._render()


# ===========================================================================
# Imágenes de assets (con caché por tamaño)
# ===========================================================================

_IMG_CACHE = {}


def _rgb(hexstr):
    """'#rrggbb' -> (r, g, b)."""
    h = hexstr.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _pil_to_photo(img, master=None):
    """Convierte una imagen PIL a tk.PhotoImage vía PNG en memoria.

    Usamos tk.PhotoImage(data=PNG) en vez de ImageTk.PhotoImage porque
    ImageTk falla de forma intermitente al componerse sobre un Canvas en
    este entorno ("invalid command name"). tk.PhotoImage con datos PNG
    (Tk 8.6+) es estable tanto en Label como en Canvas.
    """
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    data = base64.b64encode(buf.getvalue())
    return tk.PhotoImage(data=data, master=master)


def load_asset_image(name, size=None):
    """Carga assets/<name> y devuelve un tk.PhotoImage (cacheado).

    size: (w, h) para redimensionar con LANCZOS, o None para el tamaño
    original. Devuelve None si el archivo no existe. Mantener la referencia
    viva (la caché lo hace) es imprescindible: Tk descarta las imágenes sin
    referencias en Python.
    """
    key = (name, size)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    path = _asset_path(name)
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert('RGBA')
        if size is not None:
            img = img.resize(size, Image.LANCZOS)
        photo = _pil_to_photo(img)
        _IMG_CACHE[key] = photo
        return photo
    except Exception:
        return None


# ===========================================================================
# GradientButton — botón primario con degradado y esquinas redondeadas
# ===========================================================================

class GradientButton(tk.Canvas):
    """Botón con fondo de degradado violeta→púrpura y esquinas redondeadas.

    Tkinter no dibuja degradados ni bordes redondeados en widgets nativos,
    así que el fondo se renderiza como imagen (Pillow) y se compone sobre un
    Canvas. El color de fondo del Canvas debe ser el del contenedor para que
    las esquinas transparentes se integren.
    """

    def __init__(self, parent, text, command, bg,
                 height=40, padx=24, radius=11,
                 fg='#ffffff', font=('Segoe UI', 10, 'bold')):
        self._font = tkfont.Font(family=font[0], size=font[1],
                                 weight='bold')
        width = self._font.measure(text) + padx * 2
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor='hand2',
                         takefocus=0)
        self._command = command
        # OJO: no usar self._w / self._h — son el pathname interno del
        # widget en tkinter. Usamos _bw / _bh (button width/height).
        self._bw, self._bh, self._radius = width, height, radius
        self._enabled = True

        self._img_normal = self._render(1.0)
        self._img_hover = self._render(1.14)
        self._img_disabled = self._render(1.0, disabled=True)

        self._bg_id = self.create_image(0, 0, anchor='nw',
                                        image=self._img_normal)
        self._txt_id = self.create_text(width // 2, height // 2 + 1,
                                        text=text, fill=fg,
                                        font=(font[0], font[1], 'bold'))
        self.bind('<Button-1>', self._on_click)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)

    def _render(self, bright, disabled=False):
        scale = 2  # supersample para bordes nítidos
        w, h = self._bw * scale, self._bh * scale
        # Fila de degradado horizontal, luego se estira en alto.
        row = Image.new('RGB', (w, 1))
        px = row.load()
        for x in range(w):
            t = x / (w - 1)
            r = GRAD_1[0] + (GRAD_2[0] - GRAD_1[0]) * t
            g = GRAD_1[1] + (GRAD_2[1] - GRAD_1[1]) * t
            b = GRAD_1[2] + (GRAD_2[2] - GRAD_1[2]) * t
            if disabled:
                r, g, b = r * 0.45 + 40, g * 0.45 + 35, b * 0.45 + 60
            else:
                r, g, b = r * bright, g * bright, b * bright
            px[x, 0] = (min(255, int(r)), min(255, int(g)), min(255, int(b)))
        grad = row.resize((w, h))
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=self._radius * scale, fill=255)
        out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        out.paste(grad, (0, 0), mask)
        out = out.resize((self._bw, self._bh), Image.LANCZOS)
        return _pil_to_photo(out, master=self)

    def _on_click(self, _e=None):
        if self._enabled and self._command:
            self._command()
        return 'break'

    def _on_enter(self, _e=None):
        if self._enabled:
            self.itemconfig(self._bg_id, image=self._img_hover)

    def _on_leave(self, _e=None):
        if self._enabled:
            self.itemconfig(self._bg_id, image=self._img_normal)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self.itemconfig(self._bg_id,
                        image=self._img_normal if enabled else self._img_disabled)
        self.config(cursor='hand2' if enabled else '')


# ===========================================================================
# FileRow
# ===========================================================================

class FileRow(tk.Frame):
    def __init__(self, parent, filepath,
                 on_select, on_remove, on_run, on_reveal):
        super().__init__(parent, bg=SURFACE, bd=0, highlightthickness=0)
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.result = None
        self.state = ST_IDLE
        self._on_select = on_select
        self._on_remove = on_remove
        self._on_run = on_run
        self._on_reveal = on_reveal
        self._selected = False

        self.indicator = tk.Frame(self, bg=BORDER, width=4)
        self.indicator.pack(side='left', fill='y')

        self.body = tk.Frame(self, bg=SURFACE, padx=SPACE_LG, pady=SPACE_MD)
        self.body.pack(side='left', fill='both', expand=True)

        top = tk.Frame(self.body, bg=SURFACE)
        top.pack(fill='x')

        self.name_lbl = tk.Label(
            top, text=self.filename, bg=SURFACE, fg=TEXT,
            font=FONT_BODY_BOLD, anchor='w'
        )
        self.name_lbl.pack(side='left')

        actions = tk.Frame(top, bg=SURFACE)
        actions.pack(side='right')

        self.reveal_btn = tk.Label(
            actions, text="Carpeta", bg=SURFACE, fg=TEXT_MUTED, cursor='hand2',
            font=FONT_CAPTION, padx=SPACE_XS, pady=2
        )
        self.reveal_btn.pack(side='right')
        self.reveal_btn.bind('<Button-1>', self._handle_reveal)
        self.reveal_btn.bind('<Enter>',
                             lambda e: self.reveal_btn.config(fg=PRIMARY))
        self.reveal_btn.bind('<Leave>',
                             lambda e: self.reveal_btn.config(fg=TEXT_MUTED))

        self.run_btn = tk.Label(
            actions, text="▶", bg=SURFACE, fg=PRIMARY, cursor='hand2',
            font=FONT_BODY_BOLD, padx=SPACE_SM, pady=2
        )
        self.run_btn.pack(side='right', padx=(0, SPACE_XS))
        self.run_btn.bind('<Button-1>', self._handle_run)
        self.run_btn.bind('<Enter>',
                          lambda e: self._on_run_hover(True))
        self.run_btn.bind('<Leave>',
                          lambda e: self._on_run_hover(False))

        self.remove_btn = tk.Label(
            actions, text="✕", bg=SURFACE, fg=TEXT_MUTED, cursor='hand2',
            font=('Segoe UI', 11), padx=SPACE_XS
        )
        self.remove_btn.pack(side='right', padx=(2, 0))
        self.remove_btn.bind('<Button-1>', self._handle_remove)
        self.remove_btn.bind('<Enter>', self._on_remove_hover_in)
        self.remove_btn.bind('<Leave>', self._on_remove_hover_out)

        self.path_lbl = tk.Label(
            self.body, text=_truncate_path(filepath, 80),
            bg=SURFACE, fg=TEXT_MUTED,
            font=FONT_MICRO, anchor='w'
        )
        self.path_lbl.pack(fill='x', pady=(2, SPACE_SM))

        bot = tk.Frame(self.body, bg=SURFACE)
        bot.pack(fill='x')

        # Pill de status — comunicacion primaria del estado de la fila.
        self.status_pill = tk.Label(
            bot, text="Pendiente", bg=SURFACE_ALT, fg=TEXT_MUTED,
            font=FONT_CAPTION, padx=SPACE_SM, pady=2,
            highlightthickness=0
        )
        # Preservar el bg de la pill durante hover/seleccion (que repintan el row).
        self.status_pill._keep_bg = True
        self.status_pill.pack(side='left')

        # Detalle opcional a la derecha de la pill (counts, error, etc.)
        self.status_detail = tk.Label(
            bot, text="", bg=SURFACE, fg=TEXT_MUTED,
            font=FONT_CAPTION, anchor='w'
        )
        self.status_detail.pack(side='left', padx=(SPACE_SM, 0), fill='x',
                                expand=True)

        # Barra de progreso — solo visible mientras se procesa.
        self.bar = ttk.Progressbar(
            bot, length=120, mode='determinate', maximum=100.0,
            style='Running.Horizontal.TProgressbar'
        )
        # bar se hace pack/forget segun estado para no robar espacio en idle.

        self._clickable = (self, self.body, top, bot,
                           self.name_lbl, self.path_lbl,
                           self.status_pill, self.status_detail)
        for w in self._clickable:
            w.bind('<Button-1>', self._handle_click)
            w.bind('<Enter>', self._row_hover_in)
            w.bind('<Leave>', self._row_hover_out)

    def _handle_click(self, _e=None):
        self._on_select(self)

    def _handle_run(self, _e=None):
        if self.state in (ST_RUNNING, ST_QUEUED, ST_FIXING):
            return
        self._on_run(self)
        return 'break'

    def _handle_remove(self, _e=None):
        if self.state in (ST_RUNNING, ST_QUEUED, ST_FIXING):
            return
        self._on_remove(self)
        return 'break'

    def _handle_reveal(self, _e=None):
        self._on_reveal(self)
        return 'break'

    def _on_run_hover(self, entering):
        if self.state in (ST_RUNNING, ST_QUEUED):
            return
        self.run_btn.config(fg=PRIMARY_HOV if entering else PRIMARY)

    def _on_remove_hover_in(self, _e):
        if self.state not in (ST_RUNNING, ST_QUEUED):
            self.remove_btn.config(fg=ERR)

    def _on_remove_hover_out(self, _e):
        if self.state not in (ST_RUNNING, ST_QUEUED):
            self.remove_btn.config(fg=TEXT_MUTED)

    def _row_hover_in(self, _e):
        if not self._selected:
            self._set_row_bg(HOVER_BG)

    def _row_hover_out(self, _e):
        if not self._selected:
            self._set_row_bg(SURFACE)

    def _set_pill(self, text, fg, bg):
        self.status_pill.config(text=text, fg=fg, bg=bg)

    def _set_detail(self, text, fg=TEXT_MUTED):
        self.status_detail.config(text=text, fg=fg)

    def _show_bar(self, mode, style_name='Running.Horizontal.TProgressbar'):
        """mode: 'running' (indeterminate animado) o None (oculta)."""
        try:
            self.bar.stop()
        except tk.TclError:
            pass
        if mode == 'running':
            self.bar.config(mode='indeterminate', value=0, style=style_name)
            if not self.bar.winfo_ismapped():
                self.bar.pack(side='right', padx=(SPACE_SM, 0))
            self.bar.start(35)
        else:
            if self.bar.winfo_ismapped():
                self.bar.pack_forget()

    def set_state(self, state, result=None):
        self.state = state

        if state == ST_IDLE:
            self.result = None
            self.indicator.config(bg=BORDER)
            self._set_pill("Pendiente", TEXT_MUTED, SURFACE_ALT)
            self._set_detail("")
            self._show_bar(None)
            self.run_btn.config(text="▶", fg=PRIMARY, cursor='hand2')
            self.remove_btn.config(fg=TEXT_MUTED, cursor='hand2')

        elif state == ST_QUEUED:
            self.indicator.config(bg=PRIMARY_DIM)
            self._set_pill("En cola", PRIMARY, SELECTED_BG)
            self._set_detail("")
            self._show_bar(None)
            self.run_btn.config(text="…", fg=BORDER, cursor='')
            self.remove_btn.config(fg=BORDER, cursor='')

        elif state == ST_RUNNING:
            self.indicator.config(bg=PRIMARY)
            self._set_pill("Analizando", PRIMARY, SELECTED_BG)
            self._set_detail("")
            self._show_bar('running')
            self.run_btn.config(text="…", fg=BORDER, cursor='')
            self.remove_btn.config(fg=BORDER, cursor='')

        elif state == ST_FIXING:
            self.indicator.config(bg=WARN)
            self._set_pill("Reparando", WARN, WARN_BG)
            self._set_detail("")
            self._show_bar('running', 'Warn.Horizontal.TProgressbar')
            self.run_btn.config(text="…", fg=BORDER, cursor='')
            self.remove_btn.config(fg=BORDER, cursor='')

        elif state == ST_FIXED:
            self.indicator.config(bg=OK)
            self._set_pill("Reparado", OK, OK_BG)
            self._set_detail("")
            self._show_bar(None)
            self.run_btn.config(text="↻", fg=PRIMARY, cursor='hand2')
            self.remove_btn.config(fg=TEXT_MUTED, cursor='hand2')

        elif state == ST_DONE:
            self.result = result
            self._show_bar(None)
            self.run_btn.config(text="↻", fg=PRIMARY, cursor='hand2')
            self.remove_btn.config(fg=TEXT_MUTED, cursor='hand2')

            # Archivo con sufijo _fixed: tratar como ya-reparado.
            fp_low = self.filepath.lower()
            if "_fixed.psd" in fp_low or "_fixed.psb" in fp_low:
                self.indicator.config(bg=OK)
                self._set_pill("Reparado", OK, OK_BG)
                self._set_detail("")
                return

            self._apply_done_visuals(result)

    def _apply_done_visuals(self, result):
        if result is None or result.get('error'):
            self.indicator.config(bg=ERR)
            self._set_pill("Error", ERR, ERR_BG)
            self._set_detail("no se pudo abrir el PSD", ERR)
            return

        text_problems = len(result.get('problems', []))
        shared_so = len(result.get('shared_smart_objects', []))
        dup_names = len(result.get('duplicate_name_groups', []))
        total_layers = result.get('total', 0)
        total_so = result.get('smart_object_total', 0)

        if text_problems == 0 and shared_so == 0 and dup_names == 0:
            if total_layers == 0 and total_so == 0:
                self.indicator.config(bg=BORDER)
                self._set_pill("Vacio", TEXT_MUTED, SURFACE_ALT)
                self._set_detail("sin capas analizables")
            else:
                self.indicator.config(bg=OK)
                self._set_pill("OK", OK, OK_BG)
                self._set_detail(
                    f"{total_layers} text · {total_so} SO"
                )
            return

        # Hay al menos un problema.
        self.indicator.config(bg=ERR)
        self._set_pill("Problemas", ERR, ERR_BG)
        parts = []
        if text_problems:
            parts.append(
                "1 texto" if text_problems == 1 else f"{text_problems} textos"
            )
        if shared_so:
            parts.append(
                "1 SO compartido" if shared_so == 1
                else f"{shared_so} SO compartidos"
            )
        if dup_names:
            parts.append(
                "1 nombre dup." if dup_names == 1
                else f"{dup_names} nombres dup."
            )
        self._set_detail(" + ".join(parts), ERR)

    def set_selected(self, selected):
        self._selected = selected
        self._set_row_bg(SELECTED_BG if selected else SURFACE)
        # Reforzar la seleccion engrosando el indicator: cuando esta seleccionado
        # pasa de 4 a 6 px y, si esta idle, recibe el color PRIMARY para sumar
        # contraste sobre el simple cambio de fondo.
        if selected:
            self.indicator.config(width=6)
            if self.state == ST_IDLE:
                self.indicator.config(bg=PRIMARY)
        else:
            self.indicator.config(width=4)
            if self.state == ST_IDLE:
                self.indicator.config(bg=BORDER)

    def _set_row_bg(self, color):
        try:
            self.body.config(bg=color)
            for child in self.body.winfo_children():
                self._recursive_bg(child, color)
        except tk.TclError:
            pass

    def _recursive_bg(self, widget, color):
        # Algunos widgets tienen color propio (pills) que NO debe ser sobre-
        # escrito por el repintado de seleccion/hover. Se marcan con
        # `widget._keep_bg = True` cuando se crean.
        if getattr(widget, '_keep_bg', False):
            return
        try:
            widget.config(bg=color)
        except tk.TclError:
            pass
        for c in widget.winfo_children():
            self._recursive_bg(c, color)

    def destroy(self):
        try:
            self.bar.stop()
        except tk.TclError:
            pass
        super().destroy()


# ===========================================================================
# DetailsPanel
# ===========================================================================

class DetailsPanel(tk.Frame):
    def __init__(self, parent, on_reveal=None, on_fix=None):
        super().__init__(parent, bg=SURFACE, bd=0, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BORDER)
        self._on_reveal = on_reveal
        self._on_fix = on_fix
        self.current_row = None

        self.header = tk.Frame(self, bg=SURFACE)
        self.header.pack(fill='x', padx=SPACE_XL, pady=(SPACE_LG + 4, SPACE_MD))

        title_row = tk.Frame(self.header, bg=SURFACE)
        title_row.pack(fill='x')
        self.title_lbl = tk.Label(
            title_row, text="Detalles", bg=SURFACE, fg=TEXT,
            font=FONT_TITLE, anchor='w'
        )
        self.title_lbl.pack(side='left', fill='x', expand=True)

        self.reveal_action_btn = ttk.Button(
            title_row, text="Mostrar en carpeta",
            command=self._handle_reveal_click
        )

        self.fonts_action_btn = ttk.Button(
            title_row, text="Fuentes",
            command=self._show_fonts_popup
        )

        self.fix_action_btn = GradientButton(
            title_row, "Corregir capas",
            self._handle_fix_click, bg=SURFACE)

        self.subtitle_lbl = tk.Label(
            self.header,
            text="Selecciona un archivo a la izquierda para ver el desglose.",
            bg=SURFACE, fg=TEXT_MUTED, font=FONT_CAPTION, anchor='w',
            justify='left', wraplength=420
        )
        self.subtitle_lbl.pack(fill='x', pady=(SPACE_XS, 0))
        # Ajusta wraplength dinamicamente al ancho del panel
        self.bind('<Configure>',
                  lambda e: self.subtitle_lbl.config(
                      wraplength=max(200, self.winfo_width() - 60)))

        self.badge_holder = tk.Frame(self.header, bg=SURFACE)
        self.badge_holder.pack(fill='x', pady=(SPACE_MD, 0))
        self.badge = tk.Label(
            self.badge_holder, text="", bg=SURFACE, fg=TEXT_MUTED,
            font=FONT_CAPTION, padx=SPACE_SM, pady=SPACE_XS
        )
        self.badge._keep_bg = True

        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')

        self._body = tk.Frame(self, bg=SURFACE)
        self._body.pack(fill='both', expand=True, padx=SPACE_XS, pady=SPACE_XS)

        # Fila de chips de estadística (Documento, Text layers, ...): solo en
        # resultados. Reemplaza la vieja línea de resumen en monospace.
        self.stats_bar = tk.Frame(self._body, bg=SURFACE)

        # Contenedor de texto + scrollbar (se oculta en modo hero).
        self._text_wrap = tk.Frame(self._body, bg=SURFACE)
        self.text = tk.Text(
            self._text_wrap, wrap='word', bg=SURFACE, fg=TEXT, bd=0,
            highlightthickness=0, padx=SPACE_LG + 2, pady=SPACE_MD,
            font=FONT_BODY, spacing1=2, spacing3=2, cursor='arrow'
        )
        self._sb = ttk.Scrollbar(self._text_wrap, command=self.text.yview)
        self.text.configure(yscrollcommand=self._sb.set)
        self.text.pack(side='left', fill='both', expand=True)
        self._sb.pack(side='right', fill='y')

        # Overlay para los estados "hero" (vacío / pendiente / analizando):
        # widgets reales centrados con ilustración, en vez del Text widget.
        self.hero_frame = tk.Frame(self._body, bg=SURFACE)

        self._configure_tags()
        self.show_empty()

    def _configure_tags(self):
        self.text.tag_configure('h', font=FONT_BODY_BOLD,
                                foreground=TEXT, spacing1=10, spacing3=6)
        self.text.tag_configure('err',  foreground=ERR, font=FONT_BODY_BOLD)
        self.text.tag_configure('ok',   foreground=OK,  font=FONT_BODY_BOLD)
        self.text.tag_configure('warn', foreground=WARN, font=FONT_BODY_BOLD)
        self.text.tag_configure('muted', foreground=TEXT_MUTED,
                                font=FONT_CAPTION)
        self.text.tag_configure('mono', font=FONT_MONO, foreground=TEXT)
        self.text.tag_configure('mono_muted', font=FONT_MONO,
                                foreground=TEXT_MUTED)
        # Tags para empty / pending / running states con jerarquia visual.
        self.text.tag_configure('hero_glyph',
                                font=('Segoe UI', 36),
                                foreground=BORDER, justify='center',
                                spacing1=18, spacing3=4)
        self.text.tag_configure('hero_title',
                                font=('Segoe UI', 14, 'bold'),
                                foreground=TEXT, justify='center',
                                spacing1=6, spacing3=4)
        self.text.tag_configure('hero_caption',
                                font=FONT_BODY, foreground=TEXT_MUTED,
                                justify='center',
                                lmargin1=24, lmargin2=24, rmargin=24,
                                spacing1=2, spacing3=2)
        self.text.tag_configure('bullet_label',
                                font=FONT_CAPTION, foreground=TEXT,
                                lmargin1=32, lmargin2=44,
                                spacing1=6, spacing3=2)
        self.text.tag_configure('bullet_muted',
                                font=FONT_CAPTION, foreground=TEXT_MUTED,
                                lmargin1=32, lmargin2=44, rmargin=24,
                                spacing1=0, spacing3=2)
        # Caja de sugerencia: padding lateral consistente, padding vertical
        # justo (no exagerado).
        self.text.tag_configure('hint_box', background=WARN_BG,
                                foreground=TEXT, font=('Segoe UI', 9),
                                lmargin1=10, lmargin2=10, rmargin=10,
                                spacing1=4, spacing3=4)
        # 'h' headers — espaciado moderado arriba para separar secciones.
        self.text.tag_configure('h2', font=('Segoe UI', 9, 'bold'),
                                foreground=TEXT_MUTED,
                                spacing1=8, spacing3=2)

    def _set_badge(self, text, fg, bg):
        if not text:
            self.badge.pack_forget()
            return
        self.badge.config(text=text, fg=fg, bg=bg)
        self.badge.pack(side='left')

    def _handle_reveal_click(self):
        if self.current_row and self._on_reveal:
            if self.current_row.state == ST_FIXED:
                orig = self.current_row.filepath
                base, ext = os.path.splitext(orig)
                fixed = f"{base}_fixed{ext}"
                if os.path.exists(fixed):
                    reveal_in_file_manager(fixed)
                    return
            self._on_reveal(self.current_row)

    def _handle_fix_click(self):
        if not self.current_row or not self.current_row.result:
            return

        # El nuevo motor de reparacion corre en Node + ag-psd, no Photoshop.
        if not check_node_available():
            messagebox.showerror(
                "Node.js no detectado",
                "El motor de reparacion requiere Node.js instalado y accesible "
                "en el PATH.\n\nDescargalo desde https://nodejs.org/ "
                "(version 18 o superior)."
            )
            return

        problems = self.current_row.result.get('problems', [])
        if not problems:
            return

        layer_data = []
        for p in problems:
            bl, bt = p['bounds']
            layer_data.append({
                'name': p['name'],
                'width': p['width'],
                'height': p['height'],
                'left': bl,
                'top': bt,
                'right': p.get('bounds_full', (bl, bt, bl + p['width'], bt + p['height']))[2],
                'bottom': p.get('bounds_full', (bl, bt, bl + p['width'], bt + p['height']))[3],
            })

        row = self.current_row
        row.set_state(ST_FIXING)
        if self._on_fix:
            self._on_fix(row, layer_data)

    def _update_action_bar(self, row):
        if row is None:
            self.reveal_action_btn.pack_forget()
            self.fonts_action_btn.pack_forget()
            self.fix_action_btn.pack_forget()
            return

        # Orden con side='right': lo primero empacado queda más a la derecha.
        # Resultado visual izq→der: [Corregir capas] [Fuentes] [Mostrar…]
        self.reveal_action_btn.config(text="Mostrar en carpeta")
        self.reveal_action_btn.pack(side='right')

        # Boton Fuentes: siempre que el análisis haya encontrado fuentes.
        has_fonts = False
        if row.result and not row.result.get('error'):
            fr = row.result.get('fonts_report') or {}
            has_fonts = fr.get('total_fonts', 0) > 0
        if has_fonts:
            self.fonts_action_btn.pack(side='right', padx=(0, SPACE_SM))
        else:
            self.fonts_action_btn.pack_forget()

        # Boton Corregir solo si hay problemas de texto
        show_fix = False
        is_fixed_file = "_fixed.psd" in row.filepath.lower() or "_fixed.psb" in row.filepath.lower()

        if row.result and not row.result.get('error'):
            if row.result.get('problems'):
                show_fix = True

        if row.state == ST_FIXED:
            self.fix_action_btn.pack_forget()
            self.reveal_action_btn.config(text="Ver archivo reparado")
        elif is_fixed_file:
            # Si ya es un archivo reparado, no mostramos botón de corregir,
            # pero el de revelar carpeta sigue ahí.
            self.fix_action_btn.pack_forget()
            self.reveal_action_btn.config(text="Ver archivo reparado")
        elif show_fix:
            self.fix_action_btn.pack(side='right', padx=(0, SPACE_SM))
        else:
            self.fix_action_btn.pack_forget()

    def _show_fonts_popup(self):
        """Popup con el inventario de fuentes (PostScript names) del PSD:
        el total de fuentes únicas + desglose por artboard, para no tener
        que abrir el PSD y revisar capa por capa."""
        if not self.current_row or not self.current_row.result:
            return
        fr = self.current_row.result.get('fonts_report') or {}
        fonts = fr.get('fonts', [])
        if not fonts:
            return
        filename = self.current_row.filename

        existing = getattr(self, '_fonts_popup', None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()

        top = self.winfo_toplevel()
        popup = tk.Toplevel(top)
        self._fonts_popup = popup
        popup.title(f"Fuentes — {filename}")
        popup.configure(bg=SURFACE)
        popup.minsize(440, 420)
        popup.transient(top)
        # Centrar sobre la ventana principal.
        try:
            top.update_idletasks()
            w, h = 540, 640
            x = top.winfo_rootx() + (top.winfo_width() - w) // 2
            y = top.winfo_rooty() + (top.winfo_height() - h) // 2
            popup.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            popup.geometry("540x640")
        _apply_dark_titlebar(popup)

        header = tk.Frame(popup, bg=SURFACE)
        header.pack(fill='x', padx=SPACE_XL, pady=(SPACE_LG, SPACE_SM))
        tk.Label(header, text="Fuentes del documento", bg=SURFACE, fg=TEXT,
                 font=FONT_TITLE, anchor='w').pack(anchor='w')
        tk.Label(header,
                 text=f"{filename}   ·   {fr.get('total_fonts', 0)} "
                      f"fuente(s) única(s)",
                 bg=SURFACE, fg=TEXT_MUTED, font=FONT_CAPTION,
                 anchor='w').pack(anchor='w', pady=(2, 0))

        tk.Frame(popup, bg=BORDER, height=1).pack(fill='x')

        body = tk.Frame(popup, bg=SURFACE)
        body.pack(fill='both', expand=True, padx=SPACE_XS, pady=SPACE_XS)
        txt = tk.Text(body, wrap='word', bg=SURFACE, fg=TEXT, bd=0,
                      highlightthickness=0, padx=SPACE_LG, pady=SPACE_MD,
                      font=FONT_MONO, cursor='arrow', spacing1=1, spacing3=1)
        sb = ttk.Scrollbar(body, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        txt.tag_configure('h', font=('Segoe UI', 10, 'bold'), foreground=TEXT,
                          spacing1=12, spacing3=6)
        txt.tag_configure('font', font=('Segoe UI', 10, 'bold'),
                          foreground=TEXT, spacing1=3)
        txt.tag_configure('muted', font=FONT_CAPTION, foreground=TEXT_MUTED)
        txt.tag_configure('ab', font=('Segoe UI', 9, 'bold'),
                          foreground=PRIMARY_HOV, spacing1=10, spacing3=2)

        txt.insert('end', "  TODAS LAS FUENTES\n", 'h')
        for x in fonts:
            n = x['layer_count']
            txt.insert('end', f"  •  {x['name']}", 'font')
            txt.insert('end', f"    en {n} capa{'s' if n != 1 else ''}\n",
                       'muted')

        by_ab = fr.get('by_artboard', [])
        if by_ab:
            txt.insert('end', "\n  POR ARTBOARD\n", 'h')
            for ab in by_ab:
                txt.insert('end', f"\n  {ab['artboard']}\n", 'ab')
                for name in ab['fonts']:
                    txt.insert('end', f"      –  {name}\n", 'muted')
        txt.config(state='disabled')

        footer = tk.Frame(popup, bg=SURFACE_ALT)
        footer.pack(fill='x')

        def _copy():
            names = "\n".join(x['name'] for x in fonts)
            popup.clipboard_clear()
            popup.clipboard_append(names)
            copy_btn.config(text="¡Copiado!")
            popup.after(1300, lambda: copy_btn.winfo_exists()
                        and copy_btn.config(text="Copiar lista"))

        copy_btn = ttk.Button(footer, text="Copiar lista", command=_copy)
        copy_btn.pack(side='left', padx=SPACE_LG, pady=SPACE_SM)
        ttk.Button(footer, text="Cerrar",
                   command=popup.destroy).pack(side='right', padx=SPACE_LG,
                                               pady=SPACE_SM)
        popup.bind('<Escape>', lambda e: popup.destroy())

    def _show_reveal_btn(self, show):
        if show:
            if not self.reveal_action_btn.winfo_ismapped():
                self.reveal_action_btn.pack(side='right')
        else:
            self.reveal_action_btn.pack_forget()

    def _enter_hero_mode(self):
        """Oculta el Text widget y muestra el overlay hero.

        Determinista (no depende de winfo_ismapped, que es falso durante la
        construcción): pack_forget es no-op si no está empacado.
        """
        self.stats_bar.pack_forget()
        self._text_wrap.pack_forget()
        self.hero_frame.pack(fill='both', expand=True)

    def _exit_hero_mode(self):
        """Oculta el overlay hero y restaura los chips + el Text widget."""
        self.hero_frame.pack_forget()
        self.stats_bar.pack(side='top', fill='x',
                            padx=SPACE_LG, pady=(SPACE_MD, 0))
        self._text_wrap.pack(side='top', fill='both', expand=True)

    def _render_hero(self, title, caption, image='hero.png', bullets=None):
        """Dibuja un estado centrado con ilustración + título + caption
        (+ checklist opcional) en el overlay hero."""
        for w in self.hero_frame.winfo_children():
            w.destroy()
        inner = tk.Frame(self.hero_frame, bg=SURFACE)
        inner.place(relx=0.5, rely=0.5, anchor='center')

        img = load_asset_image(image, (168, 168)) if image else None
        if img is not None:
            tk.Label(inner, image=img, bg=SURFACE).pack()
        tk.Label(inner, text=title, bg=SURFACE, fg=TEXT,
                 font=('Segoe UI', 15, 'bold')).pack(pady=(SPACE_LG, SPACE_XS))
        tk.Label(inner, text=caption, bg=SURFACE, fg=TEXT_MUTED,
                 font=FONT_BODY, justify='center', wraplength=380).pack()

        if bullets:
            box = tk.Frame(inner, bg=SURFACE_ALT)
            box.pack(pady=(SPACE_XL, 0), ipadx=SPACE_MD, ipady=SPACE_SM)
            tk.Label(box, text="Después del análisis verás:",
                     bg=SURFACE_ALT, fg=TEXT, font=FONT_CAPTION,
                     anchor='w').pack(fill='x', padx=SPACE_MD,
                                      pady=(SPACE_SM, SPACE_XS))
            for b in bullets:
                tk.Label(box, text=f"•  {b}", bg=SURFACE_ALT, fg=TEXT_MUTED,
                         font=FONT_CAPTION, anchor='w',
                         justify='left').pack(fill='x', padx=SPACE_MD)
        self._enter_hero_mode()

    def show_empty(self):
        self.current_row = None
        self.title_lbl.config(text="Detalles")
        self.subtitle_lbl.config(
            text="Selecciona un archivo a la izquierda para ver el desglose."
        )
        self._set_badge("", TEXT_MUTED, SURFACE)
        self._show_reveal_btn(False)
        self._update_action_bar(None)
        self._render_hero(
            "Nada seleccionado",
            "Carga uno o más PSD a la izquierda y pulsa Analizar Todo.",
            bullets=(
                "text layers con transform desincronizado",
                "delta entre bounds visuales y transform interno",
                "shape type (point vs paragraph) y orientación",
                "smart objects compartidos y nombres duplicados",
            ),
        )

    def show_pending(self, row):
        self.current_row = row
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._set_badge("Pendiente", TEXT_MUTED, SURFACE_ALT)
        self._show_reveal_btn(True)
        self._update_action_bar(row)
        self._render_hero(
            "Aún sin analizar",
            "Pulsa ▶ en la fila o Analizar Todo para procesar este archivo.",
        )

    def show_running(self, row):
        self.current_row = row
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._set_badge("Analizando", PRIMARY, SELECTED_BG)
        self._show_reveal_btn(True)
        self._update_action_bar(row)
        self._render_hero(
            "Procesando…",
            "Para PSDs grandes esto puede tardar varios segundos.",
        )

    def show_result(self, row):
        self.current_row = row
        result = row.result
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._show_reveal_btn(True)
        self._exit_hero_mode()

        if result is None:
            self.show_pending(row)
            return

        if row.state == ST_FIXED:
            self._set_badge("Reparado", OK, OK_BG)
        elif result.get('error'):
            self._set_badge("Error", ERR, ERR_BG)
        else:
            text_p = len(result.get('problems', []))
            shared_so = len(result.get('shared_smart_objects', []))
            dup_names = len(result.get('duplicate_name_groups', []))
            total_layers = result.get('total', 0)
            total_so = result.get('smart_object_total', 0)

            if text_p == 0 and shared_so == 0 and dup_names == 0:
                if total_layers == 0 and total_so == 0:
                    self._set_badge("Sin layers analizables",
                                    TEXT_MUTED, SURFACE_ALT)
                else:
                    self._set_badge("Todo sincronizado", OK, OK_BG)
            else:
                total_problems = text_p + shared_so + dup_names
                label = ("1 problema" if total_problems == 1
                         else f"{total_problems} problemas")
                self._set_badge(label, ERR, ERR_BG)

        self._update_action_bar(row)

        self._render_stats(result)
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self._render(result)
        self.text.config(state='disabled')

    def _chip(self, label, value, accent=TEXT):
        """Un tile de estadística: etiqueta pequeña arriba, valor grande abajo."""
        c = tk.Frame(self.stats_bar, bg=SURFACE_ALT)
        c.pack(side='left', padx=(0, SPACE_SM))
        tk.Label(c, text=label.upper(), bg=SURFACE_ALT, fg=TEXT_MUTED,
                 font=('Segoe UI', 8), anchor='w').pack(
                     anchor='w', padx=SPACE_MD, pady=(SPACE_SM, 0))
        tk.Label(c, text=value, bg=SURFACE_ALT, fg=accent,
                 font=('Segoe UI', 12, 'bold'), anchor='w').pack(
                     anchor='w', padx=SPACE_MD, pady=(0, SPACE_SM))

    def _render_stats(self, result):
        """Fila de chips con las cifras clave del documento."""
        for w in self.stats_bar.winfo_children():
            w.destroy()
        if result.get('error'):
            return

        text_p = len(result.get('problems', []))
        shared_so = len(result.get('shared_smart_objects', []))
        dup = len(result.get('duplicate_name_groups', []))
        total_layers = result.get('total', 0)
        total_so = result.get('smart_object_total', 0)
        fonts = (result.get('fonts_report') or {}).get('total_fonts', 0)

        self._chip("Documento", f"{result['width']} × {result['height']}")
        self._chip("Text layers",
                   f"{total_layers}" + (f"  ·  {text_p}⚠" if text_p else ""),
                   ERR if text_p else TEXT)
        self._chip("Smart objects",
                   f"{total_so}" + (f"  ·  {shared_so}⚠" if shared_so else ""),
                   ERR if shared_so else TEXT)
        self._chip("Nombres dup.", f"{dup}", ERR if dup else TEXT)
        self._chip("Fuentes", f"{fonts}", PRIMARY_HOV if fonts else TEXT)

    def _render(self, result):
        if self.current_row.state == ST_FIXED:
            self.text.insert('end', "\n  ARCHIVO REPARADO CON EXITO\n", 'h')
            self.text.insert('end', 
                "  Se ha generado una copia corregida del archivo original.\n"
                "  Puedes abrirla pulsando el boton 'Ver archivo reparado'.\n", 
                'ok')
            self.text.insert('end', "\n" + "-"*40 + "\n", 'muted')

        if result.get('error'):
            self.text.insert('end', "\n  ERROR DE LECTURA\n", 'h')
            self.text.insert('end', f"  {result['error']}\n", 'err')
            return

        text_p = result.get('problems', [])
        shared_so = result.get('shared_smart_objects', [])
        dup_groups = result.get('duplicate_name_groups', [])

        # (El resumen del documento ahora vive en los chips de self.stats_bar.)

        # ---- Text layers desincronizados ---------------------------------
        if text_p:
            self.text.insert('end',
                "\n  TEXT LAYERS QUE FALLARAN AL REEMPLAZAR TEXTO\n", 'h')
            for p in text_p:
                bl, bt = p['bounds']
                tx, ty = p['transform']
                dx, dy = p['delta']
                self.text.insert('end', f"\n  ✗  '{p['name']}'\n", 'err')
                self.text.insert('end',
                    f"      bounds visual:    left={bl:>6}, top={bt:>6}\n",
                    'mono')
                self.text.insert('end',
                    f"      transform interno: tx={tx:>7.1f}, ty={ty:>7.1f}\n",
                    'mono')
                self.text.insert('end',
                    f"      delta:             Δx={dx:>6.0f}px, Δy={dy:>6.0f}px\n",
                    'mono_muted')
                reasons = p.get('reasons', [])
                reason_labels = {
                    'delta-exceeded':
                        f'delta supera el threshold de {p.get("threshold", 500)} px',
                    'out-of-canvas':
                        'transform interno cae fuera del canvas',
                }
                for r in reasons:
                    self.text.insert('end',
                        f"      motivo:            {reason_labels.get(r, r)}\n",
                        'mono_muted')

            self.text.insert('end', "\n", 'muted')
            self.text.insert('end',
                "Solucion manual: en Photoshop, seleccionar el layer y "
                "moverlo ligeramente o editar el texto para resincronizar "
                "el transform interno con la posicion visual.\n",
                'hint_box')
            self.text.insert('end', "\n", 'muted')

        # ---- Smart objects compartidos -----------------------------------
        if shared_so:
            self.text.insert('end',
                "\n  SMART OBJECTS COMPARTIDOS\n", 'h')
            self.text.insert('end',
                "  Estos grupos de layers apuntan al MISMO asset embebido "
                "(mismo UUID interno). Editar uno actualiza todos. La "
                "Photoshop API no puede reemplazar la imagen de uno sin "
                "afectar los demas.\n", 'muted')
            for g in shared_so:
                self.text.insert('end',
                    f"\n  ✗  Grupo de {g['count']} layers comparten el mismo "
                    f"asset:\n", 'err')
                self.text.insert('end',
                    f"      UUID:     {g['unique_id']}\n", 'mono_muted')
                self.text.insert('end',
                    f"      Archivo:  {g.get('filename') or '(sin nombre)'}\n",
                    'mono_muted')
                for L in g['layers']:
                    bl, bt, br, bb = L['bounds']
                    self.text.insert('end',
                        f"      • '{L['name']}'   bounds=({bl}, {bt}) → "
                        f"({br}, {bb})\n", 'mono')

            self.text.insert('end', "\n", 'muted')
            self.text.insert('end',
                "Solucion: en Photoshop, seleccionar uno de los layers y "
                "Layer → Smart Objects → New Smart Object via Copy. Eso crea "
                "una instancia independiente con su propio asset embebido. "
                "Repetir hasta que cada layer tenga su propia copia.\n"
                "Prevencion: nunca usar Ctrl+C / Ctrl+V con smart objects.",
                'hint_box')
            self.text.insert('end', "\n", 'muted')

        # ---- Nombres de capa duplicados ----------------------------------
        if dup_groups:
            self.text.insert('end',
                "\n  NOMBRES DE CAPA DUPLICADOS\n", 'h')
            self.text.insert('end',
                "  Estas capas comparten nombre dentro del mismo artboard. La "
                "automatizacion (y el motor de reparacion) buscan las capas "
                "por nombre y toman la PRIMERA coincidencia, asi que un nombre "
                "repetido hace que se reemplace texto/imagen en la capa "
                "equivocada.\n", 'muted')
            for g in dup_groups:
                self.text.insert('end',
                    f"\n  ✗  '{g['name']}'  ×{g['count']}   "
                    f"(artboard: {g['scope_name']})\n", 'err')
                for L in g['layers']:
                    bl, bt, br, bb = L['bounds']
                    kind = 'texto' if L['kind'] == 'text' else 'smart object'
                    self.text.insert('end',
                        f"      • {kind:<12} bounds=({bl}, {bt}) → "
                        f"({br}, {bb})\n", 'mono')

            self.text.insert('end', "\n", 'muted')
            self.text.insert('end',
                "Solucion: en Photoshop, renombrar cada capa para que su "
                "nombre sea unico dentro del artboard. La automatizacion "
                "necesita nombres distintos para identificar cada capa sin "
                "ambiguedad.\n", 'hint_box')
            self.text.insert('end', "\n", 'muted')

        if not text_p and not shared_so and not dup_groups and (
                result['total'] > 0 or result.get('smart_object_total', 0) > 0):
            self.text.insert('end',
                "\n  ✓ Todo sincronizado. Text layers OK, smart objects "
                "independientes y nombres unicos.\n", 'ok')

        # ---- Listado completo de text layers -----------------------------
        if result['total'] > 0:
            self.text.insert('end', "\n  TODOS LOS TEXT LAYERS\n", 'h')
            for r in result['layers']:
                self._render_layer_line(r)

        # ---- Listado de smart objects (si hay) ---------------------------
        groups = result.get('smart_object_groups', [])
        if groups:
            self.text.insert('end', "\n  SMART OBJECTS POR ASSET\n", 'h')
            for g in groups:
                if g['count'] >= 2:
                    sym, tag = '✗', 'err'
                else:
                    sym, tag = '✓', 'ok'
                self.text.insert('end',
                    f"\n  {sym}  {g.get('filename') or '(sin nombre)'}  "
                    f"({g['count']} layer{'s' if g['count']>1 else ''})\n",
                    tag)
                for L in g['layers']:
                    self.text.insert('end',
                        f"      - {L['name']}\n", 'mono_muted')

    def _render_layer_line(self, r):
        if r['status'] == 'OK':
            sym, tag = '✓', 'ok'
        elif r['status'] == 'DESINCRONIZADO':
            sym, tag = '✗', 'err'
        else:
            sym, tag = '!', 'warn'

        self.text.insert('end', f"\n  {sym}  ", tag)
        self.text.insert('end', f"{r['name']}\n", tag)

        if r['transform']:
            bl, bt = r['bounds']
            tx, ty = r['transform']
            dx, dy = r['delta']
            self.text.insert('end',
                f"      bounds=({bl}, {bt})   transform=({tx:.0f}, {ty:.0f})   "
                f"delta=({dx:.0f}, {dy:.0f})\n",
                'mono_muted')
        elif r['error']:
            self.text.insert('end', f"      error: {r['error']}\n", 'mono_muted')


# ===========================================================================
# App
# ===========================================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x780")
        self.minsize(1100, 620)
        self.configure(bg=BG)

        self._logo_img = None          # ref viva del logo del header
        self._apply_window_icon()
        self._enable_dark_titlebar()

        self._setup_style()

        self.rows = []
        self.selected_row = None
        self.queue = Queue()
        self.executor = None
        self.workers = _default_workers()
        self.work_queue = []
        self.active_count = 0

        # Por defecto ignorar layers dentro de grupos regulares (no artboards).
        # Los grupos suelen contener assets compartidos entre plataformas
        # (logos, legales fijos) que el equipo no piensa modificar via API.
        self.skip_groups_var = tk.BooleanVar(value=True)
        self.ignore_point_var = tk.BooleanVar(value=True)
        # Detecta capas (texto + smart objects) con nombres repetidos dentro
        # del mismo artboard. Activo por defecto: la automatizacion busca las
        # capas por nombre y toma la primera coincidencia, asi que nombres
        # duplicados hacen que se edite la capa equivocada.
        self.check_dupes_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._bind_mousewheel()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(50, self._poll_queue)

    def _apply_window_icon(self):
        """Asigna el icono de la ventana. En Windows usa el .ico (soporta
        multi-size en la barra de tareas); en el resto cae a iconphoto PNG."""
        ico = _asset_path('icon.ico')
        png = _asset_path('icon.png')
        try:
            if platform.system() == 'Windows' and os.path.exists(ico):
                self.iconbitmap(ico)
                return
        except tk.TclError:
            pass
        try:
            if os.path.exists(png):
                self._win_icon = tk.PhotoImage(file=png)
                self.iconphoto(True, self._win_icon)
        except Exception:
            pass

    def _enable_dark_titlebar(self):
        """Barra de título oscura para la ventana principal (ver módulo)."""
        _apply_dark_titlebar(self)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        # Botones secundarios: fondo elevado + borde para que se lean como
        # botones (antes eran texto plano invisible sobre el panel oscuro).
        style.configure('TButton',
                        background=BTN_BG, foreground=TEXT,
                        borderwidth=1, focusthickness=0,
                        padding=(14, 8), relief='flat',
                        font=('Segoe UI', 9))
        style.map('TButton',
                  background=[('active', BTN_HOV), ('pressed', BTN_HOV),
                              ('disabled', SURFACE)],
                  foreground=[('disabled', TEXT_MUTED),
                              ('active', PRIMARY_HOV)],
                  bordercolor=[('active', PRIMARY_DIM), ('!disabled', BORDER)],
                  lightcolor=[('active', PRIMARY_DIM), ('!disabled', BORDER)],
                  darkcolor=[('active', PRIMARY_DIM), ('!disabled', BORDER)])

        style.configure('Primary.TButton',
                        background=PRIMARY, foreground='#ffffff',
                        borderwidth=0, padding=(16, 9),
                        font=('Segoe UI', 9, 'bold'))
        style.map('Primary.TButton',
                  background=[('active', PRIMARY_HOV),
                              ('pressed', PRIMARY_HOV),
                              ('disabled', PRIMARY_DIM)],
                  foreground=[('disabled', '#ffffff')])

        # Progressbar variants para reflejar estado en la fila.
        for name, color in (('Running', PRIMARY),
                            ('Warn', WARN),
                            ('Ok', OK),
                            ('Err', ERR)):
            style.configure(f'{name}.Horizontal.TProgressbar',
                            troughcolor=SURFACE_ALT, background=color,
                            bordercolor=SURFACE_ALT,
                            lightcolor=color, darkcolor=color,
                            thickness=4)

        # Scrollbar: thumb violeta-gris sobre track oscuro, hover mas claro.
        style.configure('Vertical.TScrollbar',
                        background=SCROLL_THUMB,   # thumb
                        troughcolor=SURFACE_ALT,   # track
                        bordercolor=SURFACE_ALT,
                        arrowcolor=TEXT_MUTED,
                        lightcolor=SCROLL_THUMB,
                        darkcolor=SCROLL_THUMB,
                        gripcount=0,
                        relief='flat')
        style.map('Vertical.TScrollbar',
                  background=[('active', SCROLL_THUMB_HOV),
                              ('pressed', SCROLL_THUMB_ACT)])
        style.configure('Horizontal.TScrollbar',
                        background=SCROLL_THUMB, troughcolor=SURFACE_ALT,
                        bordercolor=SURFACE_ALT, arrowcolor=TEXT_MUTED,
                        lightcolor=SCROLL_THUMB, darkcolor=SCROLL_THUMB,
                        gripcount=0, relief='flat')
        style.map('Horizontal.TScrollbar',
                  background=[('active', SCROLL_THUMB_HOV),
                              ('pressed', SCROLL_THUMB_ACT)])

        style.configure('TFrame', background=BG)

    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', padx=20, pady=(16, 8))

        # Marca: logo + (titulo / subtitulo) en columna.
        brand = tk.Frame(header, bg=BG)
        brand.pack(anchor='w', fill='x')

        logo_path = _asset_path('logo_header.png')
        if os.path.exists(logo_path):
            try:
                self._logo_img = tk.PhotoImage(file=logo_path)
                tk.Label(brand, image=self._logo_img, bg=BG).pack(
                    side='left', padx=(0, SPACE_MD))
            except Exception:
                self._logo_img = None

        brand_text = tk.Frame(brand, bg=BG)
        brand_text.pack(side='left', fill='x', expand=True)

        tk.Label(brand_text, text=APP_TITLE, bg=BG, fg=TEXT,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        self.header_subtitle = tk.Label(
            brand_text,
            text=("Detecta text layers desincronizados, smart objects "
                  "compartidos y nombres de capa duplicados en archivos PSD."),
            bg=BG, fg=TEXT_MUTED, font=('Segoe UI', 9),
            wraplength=1200, justify='left'
        )
        self.header_subtitle.pack(anchor='w', pady=(2, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=20, pady=(8, 12))
        # 50/50 forzado: uniform asegura que ambas columnas siempre tengan
        # el mismo ancho aunque el contenido de una sea mayor.
        body.columnconfigure(0, weight=1, uniform='cols', minsize=420)
        body.columnconfigure(1, weight=1, uniform='cols', minsize=420)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=SURFACE, bd=0, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        # Fila 1: acciones principales. La accion primaria (Analizar Todo)
        # se ancla a la derecha y no comparte fila con los filtros para que
        # nunca quede recortada en ventanas estrechas.
        actions_bar = tk.Frame(left, bg=SURFACE)
        actions_bar.pack(fill='x', padx=14, pady=(14, 6))

        self.add_btn = ttk.Button(actions_bar, text="+ Agregar PSDs",
                                  command=self.add_files)
        self.add_btn.pack(side='left')

        self.clear_btn = ttk.Button(actions_bar, text="Limpiar",
                                    command=self.clear_files)
        self.clear_btn.pack(side='left', padx=(6, 0))

        self.analyze_btn = GradientButton(actions_bar, "Analizar Todo",
                                          self.analyze_all, bg=SURFACE)
        self.analyze_btn.pack(side='right')

        self.info_btn = ttk.Button(actions_bar, text="?",
                                    width=3,
                                    command=self._show_info_popup)
        self.info_btn.pack(side='right', padx=(0, 6))

        # Fila 2: filtros de analisis. Visualmente subordinados a las
        # acciones — fondo levemente distinto, label "Filtros:" como ancla.
        filters_bar = tk.Frame(left, bg=SURFACE_ALT)
        filters_bar.pack(fill='x', pady=(0, 0))

        filters_inner = tk.Frame(filters_bar, bg=SURFACE_ALT)
        filters_inner.pack(fill='x', padx=14, pady=8)

        tk.Label(filters_inner, text="Filtros:",
                 bg=SURFACE_ALT, fg=TEXT_MUTED,
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 8))

        # Ignora capas dentro de Groups normales (no Artboards). Los Groups
        # suelen tener assets fijos del equipo (logos, legales) que no
        # entran en automatizaciones.
        self.skip_groups_cb = ToggleCheck(
            filters_inner, "Ignorar carpetas",
            self.skip_groups_var, SURFACE_ALT)
        self.skip_groups_cb.pack(side='left')

        # Ignora text layers de tipo point. La Photoshop API los posiciona
        # bien aun con herencia rota (visual = tx + xx*boundingBox.left),
        # asi que por default no los reportamos. Desactivar para auditar
        # habitos del equipo aun si no impactan la pipeline.
        self.ignore_point_cb = ToggleCheck(
            filters_inner, "Ignorar capas point",
            self.ignore_point_var, SURFACE_ALT)
        self.ignore_point_cb.pack(side='left', padx=(SPACE_XL, 0))

        # Reporta capas con nombres repetidos dentro del mismo artboard. La
        # automatizacion referencia las capas por nombre (primera
        # coincidencia), asi que nombres duplicados provocan que se reemplace
        # texto/imagen en la capa equivocada.
        self.check_dupes_cb = ToggleCheck(
            filters_inner, "Nombres duplicados",
            self.check_dupes_var, SURFACE_ALT)
        self.check_dupes_cb.pack(side='left', padx=(SPACE_XL, 0))

        tk.Frame(left, bg=BORDER, height=1).pack(fill='x')

        list_wrap = tk.Frame(left, bg=SURFACE)
        list_wrap.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(list_wrap, bg=SURFACE, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(list_wrap, orient='vertical',
                                       command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=SURFACE)

        def _refresh_scroll(*_):
            bbox = self.canvas.bbox('all')
            if bbox is None:
                self.canvas.configure(scrollregion=(0, 0, 0, 0))
                self.scrollbar.pack_forget()
                return
            canvas_h = self.canvas.winfo_height()
            content_h = bbox[3] - bbox[1]
            if content_h <= canvas_h:
                # No hace falta scroll: scrollregion = tamaño canvas, oculta bar
                self.canvas.configure(scrollregion=(0, 0, bbox[2], canvas_h))
                self.scrollbar.pack_forget()
            else:
                self.canvas.configure(scrollregion=bbox)
                if not self.scrollbar.winfo_ismapped():
                    self.scrollbar.pack(side='right', fill='y')

        self.list_frame.bind('<Configure>', _refresh_scroll)
        self.canvas_win = self.canvas.create_window((0, 0), window=self.list_frame,
                                                    anchor='nw')

        def _on_canvas_configure(e):
            self.canvas.itemconfig(self.canvas_win, width=e.width)
            _refresh_scroll()
        self.canvas.bind('<Configure>', _on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        self.empty_state = tk.Frame(self.list_frame, bg=SURFACE)
        _es_inner = tk.Frame(self.empty_state, bg=SURFACE)
        _es_inner.pack(expand=True, pady=(64, 40))

        _hero_sm = load_asset_image('hero.png', (132, 132))
        if _hero_sm is not None:
            tk.Label(_es_inner, image=_hero_sm, bg=SURFACE).pack()
        tk.Label(_es_inner, text="Arrastra o agrega tus PSD",
                 bg=SURFACE, fg=TEXT, font=('Segoe UI', 14, 'bold')
                 ).pack(pady=(SPACE_MD, SPACE_XS))
        tk.Label(_es_inner,
                 text="Carga uno o varios archivos .psd / .psb para auditar\n"
                      "text layers, smart objects y nombres de capa.",
                 bg=SURFACE, fg=TEXT_MUTED, font=FONT_BODY,
                 justify='center').pack()
        GradientButton(_es_inner, "+  Agregar PSDs", self.add_files,
                       bg=SURFACE).pack(pady=(SPACE_XL, 0))
        self.empty_state.pack(fill='both', expand=True)

        tk.Frame(left, bg=BORDER, height=1).pack(fill='x')
        footer = tk.Frame(left, bg=SURFACE_ALT)
        footer.pack(fill='x')
        self.summary_lbl = tk.Label(
            footer, text="Carga uno o mas PSD para empezar.",
            bg=SURFACE_ALT, fg=TEXT_MUTED, font=FONT_CAPTION,
            anchor='w', padx=SPACE_LG, pady=SPACE_MD - 2
        )
        self.summary_lbl.pack(side='left', fill='x', expand=True)
        tk.Label(footer,
                 text=f"v{APP_VERSION}",
                 bg=SURFACE_ALT, fg=TEXT_MUTED, font=FONT_MICRO,
                 padx=SPACE_LG).pack(side='right')

        self.details = DetailsPanel(
            body,
            on_reveal=self._reveal_row,
            on_fix=self._start_fix,
        )
        self.details.grid(row=0, column=1, sticky='nsew')

    def _show_info_popup(self):
        """Popup pequeño que explica el programa y los terminos clave."""
        # Toggle: si ya esta abierto, cerrarlo
        existing = getattr(self, '_info_popup', None)
        if existing is not None and existing.winfo_exists():
            try:
                existing.destroy()
            except tk.TclError:
                pass
            self._info_popup = None
            return

        popup = tk.Toplevel(self)
        self._info_popup = popup
        popup.title("Ayuda")
        popup.transient(self)
        popup.resizable(False, False)
        popup.configure(bg=SURFACE)

        # Posicion: justo debajo del boton info
        try:
            self.info_btn.update_idletasks()
            bx = self.info_btn.winfo_rootx()
            by = self.info_btn.winfo_rooty() + self.info_btn.winfo_height() + 6
            popup.geometry(f"+{bx}+{by}")
        except tk.TclError:
            pass

        # Header con titulo + boton X
        header = tk.Frame(popup, bg=SURFACE, padx=14, pady=10)
        header.pack(fill='x')
        tk.Label(header, text="¿Que hace este programa?",
                 bg=SURFACE, fg=TEXT, font=('Segoe UI', 10, 'bold'),
                 anchor='w').pack(side='left', fill='x', expand=True)

        tk.Frame(popup, bg=BORDER, height=1).pack(fill='x')

        # Contenido
        inner = tk.Frame(popup, bg=SURFACE, padx=14, pady=12)
        inner.pack(fill='both', expand=True)

        tk.Label(inner,
                 text=("Detecta y repara PSDs con problemas heredados al "
                       "copiar/pegar capas entre artboards."),
                 bg=SURFACE, fg=TEXT_MUTED, font=('Segoe UI', 9),
                 wraplength=380, justify='left', anchor='w'
                 ).pack(anchor='w', pady=(0, 10))

        items = [
            ("bounds visual",
             "Posicion donde se ve la capa en el canvas (left, top)."),
            ("transform interno (tx, ty)",
             "Coordenadas que la Photoshop API usa al reemplazar texto."),
            ("delta",
             "Diferencia entre los dos. Si supera 500px, la capa se "
             "renderea fuera del artboard al reemplazar."),
            ("smart object compartido",
             "Dos o mas capas que apuntan al mismo asset embebido. "
             "Editar una afecta todas."),
            ("nombres duplicados",
             "Dos o mas capas con el mismo nombre dentro de un artboard. "
             "La automatizacion busca por nombre y toma la primera, asi "
             "que edita la capa equivocada."),
        ]
        for term, desc in items:
            tk.Label(inner, text=term,
                     bg=SURFACE, fg=PRIMARY,
                     font=('Segoe UI', 9, 'bold'),
                     anchor='w').pack(anchor='w', pady=(2, 0))
            tk.Label(inner, text=desc,
                     bg=SURFACE, fg=TEXT, font=('Segoe UI', 9),
                     wraplength=380, justify='left', anchor='w'
                     ).pack(anchor='w', pady=(0, 4))

        tk.Frame(inner, bg=BORDER, height=1).pack(fill='x', pady=(8, 8))

        tk.Label(inner,
                 text=("La aplicacion solo detecta problemas. La correccion "
                       "debe hacerse manualmente en Photoshop."),
                 bg=SURFACE, fg=TEXT_MUTED, font=('Segoe UI', 9),
                 wraplength=380, justify='left', anchor='w'
                 ).pack(anchor='w', pady=(0, 6))

        tk.Label(inner,
                 text=("Ignorar carpetas (default ON): no analiza layers "
                       "dentro de Groups regulares. Util cuando los grupos "
                       "contienen logos, legales o assets compartidos entre "
                       "platforms que no se modifican via API. Los Artboards "
                       "siempre se recorren."),
                 bg=SURFACE, fg=TEXT_MUTED, font=('Segoe UI', 8),
                 wraplength=380, justify='left', anchor='w'
                 ).pack(anchor='w', pady=(0, 6))

        tk.Label(inner,
                 text=(f"Procesa hasta {self.workers} archivos en paralelo "
                       "(uno por core de CPU)."),
                 bg=SURFACE, fg=TEXT_MUTED, font=('Segoe UI', 8),
                 wraplength=380, justify='left', anchor='w'
                 ).pack(anchor='w')

        # Cerrar con Escape o cuando se cierre la ventana
        popup.bind('<Escape>', lambda e: self._close_info_popup())
        popup.protocol('WM_DELETE_WINDOW', self._close_info_popup)

    def _close_info_popup(self):
        existing = getattr(self, '_info_popup', None)
        if existing is not None:
            try:
                existing.destroy()
            except tk.TclError:
                pass
        self._info_popup = None

    def _bind_mousewheel(self):
        sysname = platform.system()

        def _scroll_canvas(units):
            try:
                self.canvas.yview_scroll(units, 'units')
            except tk.TclError:
                pass

        def _route(event):
            target = self.winfo_containing(event.x_root, event.y_root)
            if target is None:
                return
            if self._is_descendant(target, self.canvas):
                if sysname == 'Darwin':
                    _scroll_canvas(int(-1 * event.delta))
                else:
                    _scroll_canvas(int(-1 * (event.delta / 120)))

        if sysname == 'Linux':
            def _l_up(e):
                t = self.winfo_containing(e.x_root, e.y_root)
                if t and self._is_descendant(t, self.canvas):
                    _scroll_canvas(-1)
            def _l_dn(e):
                t = self.winfo_containing(e.x_root, e.y_root)
                if t and self._is_descendant(t, self.canvas):
                    _scroll_canvas(1)
            self.bind_all('<Button-4>', _l_up, add='+')
            self.bind_all('<Button-5>', _l_dn, add='+')
        else:
            self.bind_all('<MouseWheel>', _route, add='+')

    def _is_descendant(self, widget, ancestor):
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            try:
                w = w.master
            except Exception:
                return False
        return False

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Selecciona uno o mas archivos PSD",
            filetypes=[("Photoshop PSD/PSB", "*.psd *.psb"), ("Todos", "*.*")],
        )
        if not files:
            return

        existing = {r.filepath for r in self.rows}
        new_files = [f for f in files if f not in existing]
        self._add_files_progressive(new_files, 0)

    def _add_files_progressive(self, files, i):
        CHUNK = 25
        end = min(i + CHUNK, len(files))
        for j in range(i, end):
            self._add_row(files[j])
        self._refresh_empty_state()
        self._update_summary()
        if end < len(files):
            self.after(1, lambda: self._add_files_progressive(files, end))

    def _add_row(self, filepath):
        row = FileRow(self.list_frame, filepath,
                      on_select=self._select_row,
                      on_remove=self._remove_row,
                      on_run=self._run_row,
                      on_reveal=self._reveal_row)
        row.pack(fill='x', pady=(0, 1))
        sep = tk.Frame(self.list_frame, bg=BORDER, height=1)
        sep.pack(fill='x')
        self.rows.append(row)

    def _remove_row(self, row):
        if row.state in (ST_RUNNING, ST_QUEUED):
            return
        if self.selected_row is row:
            self.selected_row = None
            self.details.show_empty()
        row.destroy()
        self.rows.remove(row)
        self._refresh_empty_state()
        self._update_summary()

    def clear_files(self):
        busy = (ST_RUNNING, ST_QUEUED)
        keep = [r for r in self.rows if r.state in busy]
        remove = [r for r in self.rows if r.state not in busy]
        for r in remove:
            r.destroy()
        self.rows = keep
        if self.selected_row not in self.rows:
            self.selected_row = None
            self.details.show_empty()
        self._refresh_empty_state()
        self._update_summary()

    def _select_row(self, row):
        if self.selected_row is row:
            return
        if self.selected_row is not None:
            try:
                self.selected_row.set_selected(False)
            except tk.TclError:
                pass
        self.selected_row = row
        row.set_selected(True)

        if row.state == ST_RUNNING:
            self.details.show_running(row)
        elif row.state == ST_QUEUED:
            self.details.show_pending(row)
        elif row.result is not None:
            self.details.show_result(row)
        else:
            self.details.show_pending(row)

    def _refresh_empty_state(self):
        if self.rows:
            self.empty_state.pack_forget()
        else:
            self.empty_state.pack(fill='both', expand=True)

    def _reveal_row(self, row):
        reveal_in_file_manager(row.filepath)

    def _start_fix(self, row, layer_data):
        """Lanza la reparacion en un thread y encola el resultado al
        terminar. La UI se actualiza desde _poll_queue (main thread)."""
        psd_path = row.filepath
        q = self.queue

        def _run_fix():
            try:
                ok = fix_layers_in_psd(psd_path, layer_data)
                err = None if ok else (
                    'La reparacion fallo. Revisa psd_fix_log.txt en '
                    'la carpeta temp del sistema.'
                )
            except Exception as e:
                ok, err = False, str(e)
            q.put(('fix_done', row, ok, err))

        threading.Thread(target=_run_fix, daemon=True).start()

    def _ensure_executor(self):
        if self.executor is None:
            ctx = multiprocessing.get_context('spawn')
            self.executor = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=ctx
            )
        return self.executor

    def _run_row(self, row):
        if row.state in (ST_RUNNING, ST_QUEUED):
            return
        row.set_state(ST_QUEUED)
        if self.selected_row is row:
            self.details.show_pending(row)
        self.work_queue.append(row)
        self._dispatch()

    def analyze_all(self):
        if not self.rows:
            return
        targets = [r for r in self.rows
                   if r.state not in (ST_RUNNING, ST_QUEUED)]
        if not targets:
            return
        for r in targets:
            self._run_row(r)

    def _dispatch(self):
        if not self.work_queue:
            return
        executor = self._ensure_executor()
        while self.work_queue and self.active_count < self.workers:
            row = self.work_queue.pop(0)
            if not row.winfo_exists() or row.state != ST_QUEUED:
                continue
            self.active_count += 1
            row.set_state(ST_RUNNING)
            if self.selected_row is row:
                self.details.show_running(row)

            # Snapshot del flag al momento de submit, asi cambios posteriores
            # del checkbox no afectan analisis ya en cola.
            skip_groups = bool(self.skip_groups_var.get())
            ignore_point = bool(self.ignore_point_var.get())
            check_dupes = bool(self.check_dupes_var.get())
            future = executor.submit(
                analyze_psd, row.filepath,
                skip_groups=skip_groups,
                ignore_point_text=ignore_point,
                check_duplicate_names=check_dupes,
            )
            future.add_done_callback(
                lambda f, r=row: self._on_future_done(r, f)
            )

    def _on_future_done(self, row, future):
        try:
            result = future.result()
        except Exception as e:
            result = {
                'path': row.filepath, 'width': 0, 'height': 0,
                'layers': [], 'problems': [], 'total': 0,
                'error': f"Excepcion no controlada: {e}",
            }
        self.queue.put(('done', row, result))

    def _poll_queue(self):
        # Procesa los mensajes encolados por los workers (analisis y fix).
        any_done = False
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == 'done':
                    _, row, result = msg
                    self.active_count = max(0, self.active_count - 1)
                    any_done = True
                    if row.winfo_exists():
                        row.set_state(ST_DONE, result=result)
                        if self.selected_row is row:
                            self.details.show_result(row)
                elif kind == 'fix_done':
                    _, row, ok, err = msg
                    if not row.winfo_exists():
                        continue
                    if ok:
                        row.set_state(ST_FIXED, result=row.result)
                    else:
                        row.set_state(ST_DONE, result=row.result)
                        messagebox.showerror(
                            "Error al reparar",
                            err or "No se pudo reparar el archivo."
                        )
                    if self.selected_row is row:
                        self.details.show_result(row)
        except Empty:
            pass

        if any_done:
            self._dispatch()

        self._update_summary()
        self.after(100, self._poll_queue)

    def _update_summary(self):
        if not self.rows:
            self.summary_lbl.config(text="Carga uno o mas PSD para empezar.",
                                    fg=TEXT_MUTED)
            self.analyze_btn.set_enabled(True)
            return

        running = [r for r in self.rows if r.state == ST_RUNNING]
        queued  = [r for r in self.rows if r.state == ST_QUEUED]
        done    = [r for r in self.rows if r.state == ST_DONE]
        idle    = [r for r in self.rows if r.state == ST_IDLE]

        if idle or done:
            self.analyze_btn.set_enabled(True)
        elif running or queued:
            self.analyze_btn.set_enabled(False)
        else:
            self.analyze_btn.set_enabled(True)

        if running or queued:
            parts = []
            if running:
                parts.append(f"Analizando: {len(running)}")
            if queued:
                parts.append(f"En cola: {len(queued)}")
            parts.append(f"Listos: {len(done)}/{len(self.rows)}")
            self.summary_lbl.config(text="    •    ".join(parts), fg=PRIMARY)
            return

        if not done:
            self.summary_lbl.config(
                text=f"{len(self.rows)} archivo(s) sin analizar.",
                fg=TEXT_MUTED
            )
            return

        def _has_problems(res):
            return bool(res.get('problems')
                        or res.get('shared_smart_objects')
                        or res.get('duplicate_name_groups'))

        with_problems = [r for r in done
                         if not r.result.get('error') and _has_problems(r.result)]
        with_errors = [r for r in done if r.result.get('error')]
        ok = [r for r in done
              if not r.result.get('error') and not _has_problems(r.result)]

        parts = [
            f"Analizados: {len(done)}/{len(self.rows)}",
            f"OK: {len(ok)}",
            f"Con problemas: {len(with_problems)}",
        ]
        if with_errors:
            parts.append(f"Errores: {len(with_errors)}")
        if idle:
            parts.append(f"Pendientes: {len(idle)}")

        color = ERR if with_problems else (WARN if with_errors else OK)
        self.summary_lbl.config(text="    •    ".join(parts), fg=color)

    def _on_close(self):
        if self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=False)
            self.executor = None
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
