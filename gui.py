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

import multiprocessing
import os
import platform
import threading
import tkinter as tk
from tkinter import messagebox
from concurrent.futures import ProcessPoolExecutor
from queue import Empty, Queue
from tkinter import filedialog, ttk

from detector import analyze_psd
from fixer import fix_layers_in_psd
from utils import reveal_in_file_manager, check_node_available

APP_TITLE = "Layer Audit PSD"
APP_VERSION = "1.6.0"

# Paleta unificada (clam permite colores custom en Win/Mac/Linux)
BG          = "#f1f3f9"
SURFACE     = "#ffffff"
SURFACE_ALT = "#f8fafc"
BORDER      = "#e2e8f0"
TEXT        = "#0f172a"
TEXT_MUTED  = "#64748b"
PRIMARY     = "#4f46e5"
PRIMARY_HOV = "#4338ca"
PRIMARY_DIM = "#a5b4fc"
OK          = "#16a34a"
OK_BG       = "#dcfce7"
ERR         = "#dc2626"
ERR_BG      = "#fee2e2"
WARN        = "#d97706"
WARN_BG     = "#fef3c7"
SELECTED_BG = "#eef2ff"
HOVER_BG    = "#f8fafc"

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
        total_layers = result.get('total', 0)
        total_so = result.get('smart_object_total', 0)

        if text_problems == 0 and shared_so == 0:
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

        self.fix_action_btn = ttk.Button(
            title_row, text="Corregir capas",
            style='Primary.TButton',
            command=self._handle_fix_click
        )

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

        body = tk.Frame(self, bg=SURFACE)
        body.pack(fill='both', expand=True, padx=SPACE_XS, pady=SPACE_XS)

        self.text = tk.Text(
            body, wrap='word', bg=SURFACE, fg=TEXT, bd=0,
            highlightthickness=0, padx=SPACE_LG + 2, pady=SPACE_MD,
            font=FONT_MONO, spacing1=2, spacing3=2, cursor='arrow'
        )
        sb = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

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
            self.fix_action_btn.pack_forget()
            return

        # Boton Mostrar en carpeta siempre
        self.reveal_action_btn.config(text="Mostrar en carpeta")
        self.reveal_action_btn.pack(side='right')

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
            self.fix_action_btn.pack(side='right', padx=(0, 6))
        else:
            self.fix_action_btn.pack_forget()

    def _show_reveal_btn(self, show):
        if show:
            if not self.reveal_action_btn.winfo_ismapped():
                self.reveal_action_btn.pack(side='right')
        else:
            self.reveal_action_btn.pack_forget()

    def show_empty(self):
        self.current_row = None
        self.title_lbl.config(text="Detalles")
        self.subtitle_lbl.config(
            text="Selecciona un archivo a la izquierda para ver el desglose."
        )
        self._set_badge("", TEXT_MUTED, SURFACE)
        self._show_reveal_btn(False)
        self._update_action_bar(None)

        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        # Hero centrado: glyph + titulo + caption + checklist preview.
        self.text.insert('end', "\n", 'muted')
        self.text.insert('end', "□\n", 'hero_glyph')
        self.text.insert('end', "Nada seleccionado\n", 'hero_title')
        self.text.insert('end',
            "Carga uno o mas PSD a la izquierda y pulsa Analizar Todo.\n\n",
            'hero_caption')
        self.text.insert('end',
            "Despues del analisis veras aqui:\n", 'bullet_label')
        for line in (
            "  text layers con transform desincronizado",
            "  delta exacta entre bounds visuales y transform interno",
            "  shape type (point vs paragraph) y orientacion",
            "  smart objects compartidos que requieren accion manual",
        ):
            self.text.insert('end', f"• {line.strip()}\n", 'bullet_muted')
        self.text.config(state='disabled')

    def show_pending(self, row):
        self.current_row = row
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._set_badge("Pendiente", TEXT_MUTED, SURFACE_ALT)
        self._show_reveal_btn(True)
        self._update_action_bar(row)
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', "\n", 'muted')
        self.text.insert('end', "○\n", 'hero_glyph')
        self.text.insert('end', "Aun sin analizar\n", 'hero_title')
        self.text.insert('end',
            "Pulsa ▶ en la fila o Analizar Todo para procesar este archivo.",
            'hero_caption')
        self.text.config(state='disabled')

    def show_running(self, row):
        self.current_row = row
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._set_badge("Analizando", PRIMARY, SELECTED_BG)
        self._show_reveal_btn(True)
        self._update_action_bar(row)
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', "\n", 'muted')
        self.text.insert('end', "◎\n", 'hero_glyph')
        self.text.insert('end', "Procesando\n", 'hero_title')
        self.text.insert('end',
            "Para PSDs grandes esto puede tardar varios segundos.",
            'hero_caption')
        self.text.config(state='disabled')

    def show_result(self, row):
        self.current_row = row
        result = row.result
        self.title_lbl.config(text=row.filename)
        self.subtitle_lbl.config(text=_truncate_path(row.filepath, 90))
        self._show_reveal_btn(True)

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
            total_layers = result.get('total', 0)
            total_so = result.get('smart_object_total', 0)

            if text_p == 0 and shared_so == 0:
                if total_layers == 0 and total_so == 0:
                    self._set_badge("Sin layers analizables",
                                    TEXT_MUTED, SURFACE_ALT)
                else:
                    self._set_badge("Todo sincronizado", OK, OK_BG)
            else:
                total_problems = text_p + shared_so
                label = ("1 problema" if total_problems == 1
                         else f"{total_problems} problemas")
                self._set_badge(label, ERR, ERR_BG)

        self._update_action_bar(row)

        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self._render(result)
        self.text.config(state='disabled')

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

        self.text.insert('end',
            f"\n  Documento: {result['width']}x{result['height']}px"
            f"   |   Text layers: {result['total']} ({len(text_p)} con problemas)"
            f"   |   Smart objects: {result.get('smart_object_total', 0)} "
            f"({len(shared_so)} compartidos)\n",
            'muted')

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

        if not text_p and not shared_so and (
                result['total'] > 0 or result.get('smart_object_total', 0) > 0):
            self.text.insert('end',
                "\n  ✓ Todo sincronizado. Text layers OK y smart objects "
                "todos independientes.\n", 'ok')

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

        self._build_ui()
        self._bind_mousewheel()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(50, self._poll_queue)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('TButton',
                        background=SURFACE, foreground=TEXT,
                        borderwidth=1, focusthickness=0,
                        padding=(14, 8), relief='flat',
                        font=('Segoe UI', 9))
        style.map('TButton',
                  background=[('active', HOVER_BG), ('pressed', BORDER),
                              ('disabled', SURFACE_ALT)],
                  foreground=[('disabled', TEXT_MUTED)],
                  bordercolor=[('!disabled', BORDER)],
                  lightcolor=[('!disabled', BORDER)],
                  darkcolor=[('!disabled', BORDER)])

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

        # Scrollbar visible: thumb gris medio sobre track claro, hover mas oscuro.
        style.configure('Vertical.TScrollbar',
                        background='#cbd5e1',     # thumb (gris medio)
                        troughcolor=SURFACE_ALT,  # track claro
                        bordercolor=BORDER,
                        arrowcolor=TEXT_MUTED,
                        lightcolor='#cbd5e1',
                        darkcolor='#cbd5e1',
                        gripcount=0,
                        relief='flat')
        style.map('Vertical.TScrollbar',
                  background=[('active', '#94a3b8'),
                              ('pressed', '#64748b')])
        style.configure('Horizontal.TScrollbar',
                        background='#cbd5e1', troughcolor=SURFACE_ALT,
                        bordercolor=BORDER, arrowcolor=TEXT_MUTED,
                        lightcolor='#cbd5e1', darkcolor='#cbd5e1',
                        gripcount=0, relief='flat')
        style.map('Horizontal.TScrollbar',
                  background=[('active', '#94a3b8'),
                              ('pressed', '#64748b')])

        style.configure('TFrame', background=BG)

    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', padx=20, pady=(16, 8))

        tk.Label(header, text=APP_TITLE, bg=BG, fg=TEXT,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        self.header_subtitle = tk.Label(
            header,
            text=("Detecta text layers desincronizados y smart objects "
                  "compartidos en archivos PSD."),
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

        self.analyze_btn = ttk.Button(actions_bar, text="Analizar Todo",
                                      command=self.analyze_all,
                                      style='Primary.TButton')
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

        # Para usar el fondo SURFACE_ALT necesitamos un style propio: ttk
        # Checkbutton no respeta `bg` en tk.Frame padres con fondo custom.
        cb_style = ttk.Style()
        cb_style.configure('Filter.TCheckbutton',
                           background=SURFACE_ALT,
                           foreground=TEXT)
        cb_style.map('Filter.TCheckbutton',
                     background=[('active', SURFACE_ALT)])

        # Ignora capas dentro de Groups normales (no Artboards). Los Groups
        # suelen tener assets fijos del equipo (logos, legales) que no
        # entran en automatizaciones.
        self.skip_groups_cb = ttk.Checkbutton(
            filters_inner, text="Ignorar carpetas",
            variable=self.skip_groups_var,
            style='Filter.TCheckbutton',
        )
        self.skip_groups_cb.pack(side='left')

        # Ignora text layers de tipo point. La Photoshop API los posiciona
        # bien aun con herencia rota (visual = tx + xx*boundingBox.left),
        # asi que por default no los reportamos. Desactivar para auditar
        # habitos del equipo aun si no impactan la pipeline.
        self.ignore_point_cb = ttk.Checkbutton(
            filters_inner, text="Ignorar capas point",
            variable=self.ignore_point_var,
            style='Filter.TCheckbutton',
        )
        self.ignore_point_cb.pack(side='left', padx=(16, 0))

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

        self.empty_lbl = tk.Label(
            self.list_frame,
            text="No hay archivos cargados.\n\nUsa  + Agregar PSDs  para empezar.",
            bg=SURFACE, fg=TEXT_MUTED, font=('Segoe UI', 10),
            justify='center', pady=80
        )
        self.empty_lbl.pack(fill='both', expand=True)

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
            self.empty_lbl.pack_forget()
        else:
            self.empty_lbl.pack(fill='both', expand=True)

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
            future = executor.submit(
                analyze_psd, row.filepath,
                skip_groups=skip_groups,
                ignore_point_text=ignore_point,
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
            self.analyze_btn.state(['!disabled'])
            return

        running = [r for r in self.rows if r.state == ST_RUNNING]
        queued  = [r for r in self.rows if r.state == ST_QUEUED]
        done    = [r for r in self.rows if r.state == ST_DONE]
        idle    = [r for r in self.rows if r.state == ST_IDLE]

        if idle or done:
            self.analyze_btn.state(['!disabled'])
        elif running or queued:
            self.analyze_btn.state(['disabled'])
        else:
            self.analyze_btn.state(['!disabled'])

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

        with_problems = [r for r in done
                         if not r.result.get('error') and r.result['problems']]
        with_errors = [r for r in done if r.result.get('error')]
        ok = [r for r in done
              if not r.result.get('error') and not r.result['problems']]

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
