"""AroundWorldNG Map Studio: Modern location generator for BeamNG.drive.

Select real-world regions, define bounding boxes, configure architecture styles,
and build procedural maps with roads, terrain, buildings, vegetation, and props.

Launch via:
    AroundWorldNG.bat
    python aroundworldng/launch_builder.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

import country_fetch
import looks
import places
import builder_estimate as timing
from builder_map import MapData, RegionMap, project

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SETTINGS = ROOT / 'country_setup.json'
HISTORY = ROOT / 'out' / 'country-setup' / 'build-times.json'
READY_MAPS_URL = 'https://drive.google.com/drive/folders/1n3A-msXrJtuQ2qJKn7YqzCooLZyliKMy?usp=drive_link'

STAGE_NAMES_RU = {
    'Sources': 'Загрузка исходных данных',
    'Cut tiles': 'Нарезка тайлов карты',
    'Elevation': 'Загрузка высот (DEM)',
    'Region index': 'Индексация регионов',
    'Map detail': 'Детализация карты',
    'Export': 'Экспорт геометрии и сборка',
    'Install': 'Установка мода'
}

# Studio Workstation Palette - utilitarian, dark matte graphite ("дешево и серо, но человечно")
PALETTE = {
    'bg_app': '#131316',           # Root window background
    'bg_panel': '#1b1b1f',         # Main column panels
    'bg_card': '#212126',          # Section containers / cards
    'bg_input': '#161619',         # Text entries, listbox, canvas bg
    'border': '#2c2c34',           # Subtle structural borders
    'border_highlight': '#3d3f4a',  # Slightly elevated borders
    'text_primary': '#e2e2e6',      # High-contrast soft white
    'text_secondary': '#8a8d98',    # Muted secondary text
    'text_dim': '#606370',          # Small hints, section headers
    'btn_default': '#292b33',      # Standard button
    'btn_default_hover': '#353842',  # Standard button hover
    'btn_primary': '#3b4354',      # Primary "Собрать карту" button (solid steel graphite)
    'btn_primary_hover': '#495368',  # Primary hover
    'btn_danger': '#3e2424',       # Stop button (muted dark wine red)
    'btn_danger_hover': '#4e2d2d',  # Stop button hover
    'btn_danger_text': '#f28b82',   # Stop button text
    'progress_track': '#202026',   # Progress bar track
    'progress_bar': '#5e6982',     # Progress bar fill
    'selection_badge': '#8da0b8',  # Muted slate for coordinates/area
}

# Popular quick presets: (Title, lon_w, lat_s, lon_e, lat_n, place_slug)
PRESETS = [
    ('Кудрово (СПб)', 30.485, 59.895, 30.525, 59.925, 'russia/northwestern-fed-district'),
    ('Мурино (СПб)', 30.420, 60.035, 30.465, 60.065, 'russia/northwestern-fed-district'),
    ('Центр Санкт-Петербурга', 30.300, 59.920, 30.360, 59.945, 'russia/northwestern-fed-district'),
    ('Васильевский остров', 30.220, 59.925, 30.280, 59.955, 'russia/northwestern-fed-district'),
    ('Москва-Сити', 37.525, 55.740, 37.555, 55.760, 'russia/central-fed-district'),
]


def load_settings():
    mods = str(country_fetch.default_mods())
    settings = {'mods': mods, 'query': ''}
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict) and isinstance(saved.get('mods'), str):
            settings['mods'] = saved['mods']
    return settings


def save_settings(mods):
    SETTINGS.write_text(json.dumps({'mods': mods}, ensure_ascii=False, indent=1), encoding='utf-8')


def create_root():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk(fg_color=PALETTE['bg_app'])
    return root


class Setup:
    def __init__(self, root, start_workers=True):
        self.root = root
        self.settings = load_settings()
        self.places = []
        self.by_id = {}
        self.shown = []
        self.place = None
        self.lines = queue.Queue()
        self.cancel = None
        self.worker = None
        self.running = False
        self.boundaries = {}
        self.sizes = {}
        self.size_future = None
        self.preview_future = None
        self.preview_version = 0
        self.preview_after = None
        self.map_after = None
        self.map_version = 0
        self.map_future = None
        self.map_results = {}
        self.map_result_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(3, thread_name_prefix='aroundworldng')
        self.history = timing.load_history(HISTORY)
        self.stage_times = {}
        self.active_stage = None
        self.started = None
        self.closing = False
        self.freeze = False
        self.start_workers = start_workers

        root.title('AroundWorldNG — Map Studio')
        root.geometry('1360x890')
        root.minsize(1120, 780)
        root.protocol('WM_DELETE_WINDOW', self.close)

        # Style standard ttk widgets for a unified utilitarian engineering look
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TFrame', background=PALETTE['bg_panel'])
        style.configure('TLabel', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=('Segoe UI', 9))
        style.configure('TRadiobutton', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=('Segoe UI', 9), indicatorcolor=PALETTE['bg_input'])
        style.map('TRadiobutton', background=[('active', PALETTE['bg_card'])], foreground=[('active', '#ffffff')])
        style.configure('TCheckbutton', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=('Segoe UI', 9), indicatorcolor=PALETTE['bg_input'])
        style.map('TCheckbutton', background=[('active', PALETTE['bg_card'])], foreground=[('active', '#ffffff')])
        style.configure('TButton', background=PALETTE['btn_default'], foreground=PALETTE['text_primary'], borderwidth=1, bordercolor=PALETTE['border'], focusthickness=0, font=('Segoe UI', 9))
        style.map('TButton', background=[('active', PALETTE['btn_default_hover'])], foreground=[('active', '#ffffff')])
        style.configure('TCombobox', fieldbackground=PALETTE['bg_input'], background=PALETTE['btn_default'], foreground=PALETTE['text_primary'], bordercolor=PALETTE['border'])

        self.mods = tk.StringVar(value=self.settings['mods'])
        self.query = tk.StringVar(value='')
        self.status = tk.StringVar(value='Загрузка списка регионов…')
        self.size = tk.StringVar(value='')
        self.ready = tk.StringVar(value='')
        self.estimate_text = tk.StringVar(value='Выберите регион или выделите область на карте для расчета времени.')
        self.progress_text = tk.StringVar(value='Готов к работе')
        self.selection_text = tk.StringVar(value='Весь исходный регион')
        self.preview_text = tk.StringVar(value='Загрузка превью материалов…')
        self.block = tk.StringVar()
        self.slots = {slot: tk.StringVar() for slot in looks.SLOTS}
        self.layers = {key: tk.BooleanVar(value=default) for key, _label, default in looks.LAYERS}
        self.use_box = tk.BooleanVar(value=False)
        self.box = {name: tk.StringVar() for name in ('w', 's', 'e', 'n')}

        self._build()
        self.show_look(looks.canonical({'block': 'general'}))
        for variable in [*self.slots.values(), *self.layers.values(), self.use_box, *self.box.values()]:
            variable.trace_add('write', self.options_changed)
        self.mods.trace_add('write', self.mods_changed)

        root.after(200, self.pump)
        if start_workers:
            self.reload(False)
            self.reload_map()
            self.pool.submit(self.load_boundaries)

    def _build(self):
        # Main horizontal container across the entire window
        main_layout = ctk.CTkFrame(self.root, fg_color="transparent")
        main_layout.pack(fill='both', expand=True, padx=8, pady=8)

        # =========================================================================
        # 1. LEFT PANEL (Width: 260px fixed) — Library, Explorer & System Settings
        # =========================================================================
        self.left_panel = ctk.CTkFrame(main_layout, width=260, corner_radius=6,
                                      fg_color=PALETTE['bg_panel'],
                                      border_width=1, border_color=PALETTE['border'])
        self.left_panel.pack(side='left', fill='y', padx=(0, 6))
        self.left_panel.pack_propagate(False)

        # --- Brand Header ---
        brand_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        brand_box.pack(fill='x', padx=12, pady=(12, 8))

        ctk.CTkLabel(brand_box, text='AroundWorldNG',
                     font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w')
        ctk.CTkLabel(brand_box, text='STUDIO WORKSTATION',
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(1, 0))

        # Divider
        ctk.CTkFrame(self.left_panel, height=1, fg_color=PALETTE['border']).pack(fill='x', padx=10, pady=(4, 8))

        # --- Section: Quick Presets ("Быстрый выбор") ---
        presets_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        presets_header.pack(fill='x', padx=12, pady=(0, 4))
        ctk.CTkLabel(presets_header, text='БЫСТРЫЙ ВЫБОР',
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        presets_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        presets_box.pack(fill='x', padx=10, pady=(0, 8))

        for title, w, s, e, n, place_id in PRESETS:
            btn = ctk.CTkButton(presets_box, text=title, height=24, anchor='w',
                                font=ctk.CTkFont(family="Segoe UI", size=10),
                                fg_color=PALETTE['bg_card'], text_color=PALETTE['text_primary'],
                                hover_color=PALETTE['btn_default_hover'], corner_radius=3,
                                command=lambda _w=w, _s=s, _e=e, _n=n, _p=place_id: self.apply_preset(_w, _s, _e, _n, _p))
            btn.pack(fill='x', pady=1)

        # Divider
        ctk.CTkFrame(self.left_panel, height=1, fg_color=PALETTE['border']).pack(fill='x', padx=10, pady=(2, 8))

        # --- Section: Region Catalog ("Каталог регионов") ---
        catalog_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        catalog_header.pack(fill='x', padx=12, pady=(0, 4))
        ctk.CTkLabel(catalog_header, text='КАТАЛОГ РЕГИОНОВ',
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        search_row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        search_row.pack(fill='x', padx=10, pady=(0, 6))

        self.entry_search = ctk.CTkEntry(search_row, textvariable=self.query, height=26,
                                         placeholder_text="Поиск региона...",
                                         font=ctk.CTkFont(family="Segoe UI", size=10),
                                         fg_color=PALETTE['bg_input'],
                                         border_color=PALETTE['border'])
        self.entry_search.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.entry_search.bind('<KeyRelease>', lambda _event: self.refill())

        self.btn_reload = ctk.CTkButton(search_row, text='Обновить', width=65, height=26,
                                        fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                                        corner_radius=3,
                                        command=lambda: self.reload(True))
        self.btn_reload.pack(side='left')

        # Listbox Container with Scrollbar (fills remaining middle vertical height of left panel)
        list_container = ctk.CTkFrame(self.left_panel, corner_radius=4,
                                      fg_color=PALETTE['bg_input'],
                                      border_width=1, border_color=PALETTE['border'])
        list_container.pack(fill='both', expand=True, padx=10, pady=(0, 8))

        self.list = tk.Listbox(list_container, exportselection=False,
                               bg=PALETTE['bg_input'], fg=PALETTE['text_primary'],
                               selectbackground=PALETTE['btn_primary'], selectforeground='#ffffff',
                               highlightthickness=0, bd=0, font=('Segoe UI', 9), activestyle='none')
        self.list.pack(side='left', fill='both', expand=True, padx=4, pady=4)

        list_scroll = ctk.CTkScrollbar(list_container, width=12, command=self.list.yview)
        list_scroll.pack(side='right', fill='y', padx=(0, 2), pady=4)
        self.list.configure(yscrollcommand=list_scroll.set)
        self.list.bind('<<ListboxSelect>>', lambda _event: self.on_select())

        # --- Section: System & BeamNG Configuration (Pinned at bottom) ---
        sys_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        sys_box.pack(fill='x', side='bottom', padx=10, pady=(0, 10))

        ctk.CTkFrame(sys_box, height=1, fg_color=PALETTE['border']).pack(fill='x', pady=(0, 8))

        ctk.CTkLabel(sys_box, text='СИСТЕМА И BeamNG',
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        ctk.CTkLabel(sys_box, text='Папка модов BeamNG.drive:',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(3, 1))

        mods_row = ctk.CTkFrame(sys_box, fg_color="transparent")
        mods_row.pack(fill='x', pady=(0, 6))

        self.entry_mods = ctk.CTkEntry(mods_row, textvariable=self.mods, height=26,
                                       font=ctk.CTkFont(family="Segoe UI", size=9),
                                       fg_color=PALETTE['bg_input'],
                                       border_color=PALETTE['border'])
        self.entry_mods.pack(side='left', fill='x', expand=True, padx=(0, 4))

        self.btn_browse = ctk.CTkButton(mods_row, text='Обзор…', width=55, height=26,
                                        fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                                        corner_radius=3,
                                        command=self.browse_mods)
        self.btn_browse.pack(side='left')

        self.btn_sync = ctk.CTkButton(sys_box, text='Синхронизировать ядро', height=28,
                                      fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                      text_color=PALETTE['text_primary'],
                                      font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                                      corner_radius=3,
                                      command=self.refresh_planet)
        self.btn_sync.pack(fill='x')

        # =========================================================================
        # 2. CENTER PANEL (Flexible / Expands) — Viewport & Telemetry Console
        # =========================================================================
        self.center_panel = ctk.CTkFrame(main_layout, corner_radius=6,
                                        fg_color=PALETTE['bg_panel'],
                                        border_width=1, border_color=PALETTE['border'])
        self.center_panel.pack(side='left', fill='both', expand=True, padx=(0, 6))

        # --- Interactive Map Viewport ---
        map_wrapper = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        map_wrapper.pack(fill='both', expand=True, padx=8, pady=(8, 4))

        self.map = RegionMap(map_wrapper, self.select_box)
        self.map.pack(fill='both', expand=True)
        self.map.canvas.configure(background=PALETTE['bg_input'], highlightbackground=PALETTE['border'])

        # --- Selection Details Sub-bar ---
        subbar = ctk.CTkFrame(self.center_panel, height=36, corner_radius=4,
                              fg_color=PALETTE['bg_card'],
                              border_width=1, border_color=PALETTE['border'])
        subbar.pack(fill='x', padx=8, pady=(0, 6))

        subbar_inner = ctk.CTkFrame(subbar, fg_color="transparent")
        subbar_inner.pack(fill='x', padx=8, pady=4)

        self.lbl_selection = ctk.CTkLabel(subbar_inner, textvariable=self.selection_text,
                                          font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                                          text_color=PALETTE['selection_badge'])
        self.lbl_selection.pack(side='left', padx=(0, 8))

        self.btn_whole = ctk.CTkButton(subbar_inner, text='Весь регион', width=90, height=24,
                                       fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                       text_color=PALETTE['text_primary'],
                                       font=ctk.CTkFont(family="Segoe UI", size=10),
                                       corner_radius=3,
                                       command=self.clear_box)
        self.btn_whole.pack(side='left', padx=(0, 4))

        self.btn_optimize = ctk.CTkButton(subbar_inner, text='Оптимальный источник', width=150, height=24,
                                          fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                          text_color=PALETTE['text_primary'],
                                          font=ctk.CTkFont(family="Segoe UI", size=10),
                                          corner_radius=3,
                                          command=self.optimize_source)
        self.btn_optimize.pack(side='left')

        # --- Telemetry & Terminal Console (Bottom of Center Panel) ---
        console_frame = ctk.CTkFrame(self.center_panel, corner_radius=4,
                                     fg_color=PALETTE['bg_card'],
                                     border_width=1, border_color=PALETTE['border'])
        console_frame.pack(fill='x', padx=8, pady=(0, 8))

        console_header = ctk.CTkFrame(console_frame, fg_color="transparent")
        console_header.pack(fill='x', padx=8, pady=(6, 2))

        self.lbl_progress = ctk.CTkLabel(console_header, textvariable=self.progress_text,
                                         font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                                         text_color=PALETTE['text_primary'])
        self.lbl_progress.pack(side='left')

        self.lbl_status = ctk.CTkLabel(console_header, textvariable=self.status,
                                       font=ctk.CTkFont(family="Segoe UI", size=9),
                                       text_color=PALETTE['text_secondary'])
        self.lbl_status.pack(side='right', padx=(10, 0))

        self.progressbar = ctk.CTkProgressBar(console_frame, height=4,
                                              fg_color=PALETTE['progress_track'],
                                              progress_color=PALETTE['progress_bar'])
        self.progressbar.pack(fill='x', padx=8, pady=(2, 6))
        self.progressbar.set(0)

        self.log = ctk.CTkTextbox(console_frame, height=92,
                                  font=ctk.CTkFont(family="Consolas", size=9),
                                  fg_color=PALETTE['bg_input'],
                                  text_color=PALETTE['text_primary'],
                                  border_width=1, border_color=PALETTE['border'],
                                  corner_radius=3)
        self.log.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.log.configure(state='disabled')

        # =========================================================================
        # 3. RIGHT PANEL (Width: 340px fixed) — Production Launch & Inspector
        # =========================================================================
        self.right_panel = ctk.CTkFrame(main_layout, width=340, corner_radius=6,
                                       fg_color=PALETTE['bg_panel'],
                                       border_width=1, border_color=PALETTE['border'])
        self.right_panel.pack(side='left', fill='y', padx=0)
        self.right_panel.pack_propagate(False)

        # --- Section: Production & Build Card ---
        prod_card = ctk.CTkFrame(self.right_panel, corner_radius=4,
                                 fg_color=PALETTE['bg_card'],
                                 border_width=1, border_color=PALETTE['border'])
        prod_card.pack(fill='x', padx=8, pady=(8, 6))

        ctk.CTkLabel(prod_card, text='ПРОИЗВОДСТВО КАРТЫ',
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w', padx=10, pady=(8, 4))

        self.build_btn = ctk.CTkButton(prod_card, text='Собрать карту для BeamNG',
                                       height=38,
                                       fg_color=PALETTE['btn_primary'],
                                       hover_color=PALETTE['btn_primary_hover'],
                                       text_color=PALETTE['text_primary'],
                                       font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                                       corner_radius=4,
                                       command=self.build)
        self.build_btn.pack(fill='x', padx=10, pady=(2, 6))

        btn_subrow = ctk.CTkFrame(prod_card, fg_color="transparent")
        btn_subrow.pack(fill='x', padx=10, pady=(0, 8))

        self.stop_btn = ctk.CTkButton(btn_subrow, text='Прервать', width=75, height=26,
                                      fg_color=PALETTE['btn_danger'],
                                      hover_color=PALETTE['btn_danger_hover'],
                                      text_color=PALETTE['btn_danger_text'],
                                      font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                                      corner_radius=3,
                                      state='disabled', command=self.stop)
        self.stop_btn.pack(side='left', padx=(0, 4))

        self.download_btn = ctk.CTkButton(btn_subrow, text='Готовый пак', width=95, height=26,
                                          fg_color=PALETTE['btn_default'],
                                          hover_color=PALETTE['btn_default_hover'],
                                          text_color=PALETTE['text_primary'],
                                          font=ctk.CTkFont(family="Segoe UI", size=10),
                                          corner_radius=3,
                                          command=self.download_ready)
        self.download_btn.pack(side='left', padx=(0, 4))

        self.gdrive_btn = ctk.CTkButton(btn_subrow, text='Google Drive', width=95, height=26,
                                        fg_color=PALETTE['btn_default'],
                                        hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family="Segoe UI", size=10),
                                        corner_radius=3,
                                        command=lambda: webbrowser.open(READY_MAPS_URL))
        self.gdrive_btn.pack(side='left')

        # Status & Estimates in Production Card
        est_box = ctk.CTkFrame(prod_card, fg_color="transparent")
        est_box.pack(fill='x', padx=10, pady=(0, 8))

        ctk.CTkLabel(est_box, textvariable=self.estimate_text, wraplength=300, justify='left',
                     font=ctk.CTkFont(family="Segoe UI", size=10),
                     text_color=PALETTE['text_secondary']).pack(anchor='w')

        ctk.CTkLabel(est_box, textvariable=self.ready, wraplength=300, justify='left',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(2, 0))

        ctk.CTkLabel(est_box, textvariable=self.size, justify='left',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(1, 0))

        # --- Section: Parameter Tabs / Inspector ---
        self.tabs = ctk.CTkTabview(self.right_panel, corner_radius=4,
                                   fg_color=PALETTE['bg_card'],
                                   segmented_button_fg_color=PALETTE['bg_input'],
                                   segmented_button_selected_color=PALETTE['btn_primary'],
                                   segmented_button_selected_hover_color=PALETTE['btn_primary_hover'],
                                   text_color=PALETTE['text_primary'])
        self.tabs.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        tab_style = self.tabs.add('Архитектура')
        tab_layers = self.tabs.add('Слои карты')
        tab_coords = self.tabs.add('Границы (BBox)')

        # TAB 1: ARCHITECTURE
        tab_style_scroll = ctk.CTkScrollableFrame(tab_style, fg_color="transparent")
        tab_style_scroll.pack(fill='both', expand=True)

        ctk.CTkLabel(tab_style_scroll, text='Стиль застройки (Asset Block):',
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(2, 2))

        titles = [block['title'] for block in looks.BLOCKS]
        self.block_menu = ctk.CTkOptionMenu(tab_style_scroll, variable=self.block, values=titles,
                                            height=26,
                                            fg_color=PALETTE['bg_input'],
                                            button_color=PALETTE['btn_default'],
                                            button_hover_color=PALETTE['btn_default_hover'],
                                            dropdown_fg_color=PALETTE['bg_card'],
                                            font=ctk.CTkFont(family="Segoe UI", size=10),
                                            command=lambda _val: self.apply_block())
        self.block_menu.pack(fill='x', pady=(0, 8))

        ctk.CTkLabel(tab_style_scroll, text='Индивидуальные слоты материалов:',
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(2, 2))

        self.slot_menus = {}
        for slot, label in looks.SLOT_LABELS.items():
            row = ctk.CTkFrame(tab_style_scroll, fg_color="transparent")
            row.pack(fill='x', pady=2)
            ctk.CTkLabel(row, text=label, width=105, anchor='w',
                         font=ctk.CTkFont(family="Segoe UI", size=9),
                         text_color=PALETTE['text_secondary']).pack(side='left')
            values = list(looks.SLOTS[slot].values())
            menu = ctk.CTkOptionMenu(row, variable=self.slots[slot], values=values,
                                     height=24,
                                     fg_color=PALETTE['bg_input'],
                                     button_color=PALETTE['btn_default'],
                                     button_hover_color=PALETTE['btn_default_hover'],
                                     dropdown_fg_color=PALETTE['bg_card'],
                                     font=ctk.CTkFont(family="Segoe UI", size=9))
            menu.pack(side='left', fill='x', expand=True)
            self.slot_menus[slot] = menu

        # 2D Facade Material Preview
        preview_box = ctk.CTkFrame(tab_style_scroll, corner_radius=4,
                                   fg_color=PALETTE['bg_input'],
                                   border_width=1, border_color=PALETTE['border'])
        preview_box.pack(fill='x', pady=(8, 4))

        self.preview_label = ctk.CTkLabel(preview_box, text='')
        self.preview_label.pack(padx=4, pady=4)

        ctk.CTkLabel(tab_style_scroll, textvariable=self.preview_text, wraplength=290, justify='left',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        # TAB 2: LAYERS
        ctk.CTkLabel(tab_layers, text='Активные слои данных OSM:',
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(4, 2))
        ctk.CTkLabel(tab_layers, text='(Дорожная сеть и высотный рельеф включены всегда)',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(0, 6))

        self.layer_switches = {}
        for key, label, _default in looks.LAYERS:
            sw = ctk.CTkSwitch(tab_layers, text=label, variable=self.layers[key],
                               progress_color=PALETTE['btn_primary'],
                               font=ctk.CTkFont(family="Segoe UI", size=10))
            sw.pack(anchor='w', pady=3)
            self.layer_switches[key] = sw

        # TAB 3: COORDINATES (BBOX)
        ctk.CTkLabel(tab_coords, text='Ограничение области карты:',
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(4, 2))

        self.sw_box = ctk.CTkSwitch(tab_coords, text='Ограничить выбранным прямоугольником',
                                    variable=self.use_box,
                                    progress_color=PALETTE['btn_primary'],
                                    font=ctk.CTkFont(family="Segoe UI", size=10))
        self.sw_box.pack(anchor='w', pady=(4, 6))

        coords_grid = ctk.CTkFrame(tab_coords, fg_color="transparent")
        coords_grid.pack(fill='x', pady=2)

        labels_ru = {'w': 'Запад (W lon)', 's': 'Юг (S lat)', 'e': 'Восток (E lon)', 'n': 'Север (N lat)'}
        for name, _hint in (('w', 'W'), ('s', 'S'), ('e', 'E'), ('n', 'N')):
            row = ctk.CTkFrame(coords_grid, fg_color="transparent")
            row.pack(fill='x', pady=2)
            ctk.CTkLabel(row, text=labels_ru[name], width=110, anchor='w',
                         font=ctk.CTkFont(family="Segoe UI", size=9),
                         text_color=PALETTE['text_secondary']).pack(side='left')
            entry = ctk.CTkEntry(row, textvariable=self.box[name], height=24,
                                 fg_color=PALETTE['bg_input'], border_color=PALETTE['border'],
                                 font=ctk.CTkFont(family="Segoe UI", size=9))
            entry.pack(side='left', fill='x', expand=True)

        ctk.CTkLabel(tab_coords,
                     text='Совет: вы можете растянуть область мышкой на интерактивной карте в центре, удерживая ЛКМ в режиме «Выделение рамкой».',
                     wraplength=290, justify='left',
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(10, 0))

        # Controls list for busy state toggling
        self.controls = [self.left_panel, subbar, prod_card, self.tabs]

    def apply_preset(self, lon_w, lat_s, lon_e, lat_n, place_id):
        if self.running:
            return
        self.freeze = True
        self.box['w'].set(f'{lon_w:.6f}')
        self.box['s'].set(f'{lat_s:.6f}')
        self.box['e'].set(f'{lon_e:.6f}')
        self.box['n'].set(f'{lat_n:.6f}')
        self.use_box.set(True)
        self.freeze = False

        # Select corresponding place if known
        target_place = self.by_id.get(place_id)
        if not target_place:
            target_place = next((p for p in self.places if place_id in p['id']), None)
        if target_place:
            self.select_place(target_place, fit=False, preserve_look=False)

        # Center map
        c_lon = (lon_w + lon_e) / 2
        c_lat = (lat_s + lat_n) / 2
        self.map.center = project(c_lon, c_lat)
        self.map.zoom = 13
        self.map.selection = (lon_w, lat_s, lon_e, lat_n)
        self.map.schedule()
        self.options_changed()

    def say(self, text):
        msg = str(text)
        self.lines.put(msg)
        try:
            log_dir = ROOT / 'out' / 'aroundworldng'
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / 'build.log', 'a', encoding='utf-8') as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except OSError:
            pass

    def pump(self):
        messages = []
        for _ in range(150):
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            if callable(line):
                try:
                    line()
                except Exception as exc:
                    self.root.report_callback_exception(*sys.exc_info())
                    messages.append(f'Could not apply background result: {exc}')
                continue
            messages.append(line)

        if messages:
            self.log.configure(state='normal')
            self.log.insert('end', '\n'.join(messages) + '\n')
            count = int(self.log.index('end-1c').split('.')[0])
            if count > 50000:
                self.log.delete('1.0', f'{count-50000}.0')
            self.log.see('end')
            self.log.configure(state='disabled')
            self.status.set(messages[-1])

        if self.running and self.started is not None:
            elapsed = time.monotonic() - self.started
            label = f'Прошло времени: {timing.duration(elapsed)}'
            if self.active_stage:
                ru_stage = STAGE_NAMES_RU.get(self.active_stage, self.active_stage)
                index = timing.STAGES.index(self.active_stage) if self.active_stage in timing.STAGES else None
                if index is not None:
                    label = f'Этап {index+1}/{len(timing.STAGES)}: {ru_stage} · {label}'
                else:
                    label = f'{ru_stage} · {label}'
                if index is not None and getattr(self, 'run_estimate', None):
                    remaining = sum(self.run_estimate[index:]) - (time.monotonic() - self.stage_started)
                    label += (f' · осталось ~{timing.duration(remaining*0.5)}–{timing.duration(remaining*2.5)}'
                              if remaining > 5 else ' · завершение этапа…')
            self.progress_text.set(label)

        if self.closing and not self.running:
            self.pool.shutdown(wait=False, cancel_futures=True)
            if self.map.data:
                self.map.data.close()
            self.root.destroy()
            return
        self.root.after(200, self.pump)

    def close(self):
        with self.map_result_lock:
            self.closing = True
            for data in self.map_results.values():
                data.close()
            self.map_results.clear()
        self.stop()
        if self.running:
            self.status.set('Остановка фоновых процессов перед закрытием…')

    def reload_map(self):
        self.map_after = None
        if self.closing:
            return
        self.map_version += 1
        version, mods = self.map_version, self.mods.get()
        if self.map_future:
            self.map_future.cancel()
        self.map_future = self.pool.submit(self.load_map, version, mods)

    def load_map(self, version, mods):
        try:
            data = MapData(ROOT, mods)
            with self.map_result_lock:
                if self.closing or version != self.map_version:
                    data.close()
                else:
                    self.map_results[version] = data
                    self.lines.put(lambda: self.set_map_data(data, version))
        except Exception as exc:
            self.say(f'Оффлайн карта недоступна: {exc}')

    def load_boundaries(self):
        try:
            boundaries = places.load_boundaries(ROOT)
            self.lines.put(lambda: self.set_boundaries(boundaries))
        except Exception as exc:
            self.say(f'Границы регионов недоступны: {exc}')

    def set_map_data(self, data, version):
        with self.map_result_lock:
            self.map_results.pop(version, None)
        if version != self.map_version or self.closing:
            data.close()
            return
        if self.map.data:
            self.map.data.close()
        self.map.data = data
        self.map.schedule()

    def set_boundaries(self, boundaries):
        self.boundaries = boundaries
        if self.place:
            self.map.boundary = boundaries.get(self.place['id'])
            self.map.fit_source()
        self.map.schedule()
        self.update_estimate()

    def select_box(self, box):
        if self.running:
            return
        try:
            box = timing.validate_box(box)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.freeze = True
        for name, value in zip(('w', 's', 'e', 'n'), box):
            self.box[name].set(f'{value:.6f}')
        self.use_box.set(True)
        self.freeze = False
        self.optimize_source()
        self.options_changed()

    def clear_box(self):
        if not self.running:
            self.use_box.set(False)

    def optimize_source(self):
        if self.running:
            return
        try:
            box = self.chosen_box()
        except ValueError:
            return
        if box is None:
            return
        key = places.smallest_covering(self.boundaries, box, self.by_id)
        if key:
            self.select_place(self.by_id[key], fit=False, preserve_look=self.place is not None)
            self.status.set(f'Оптимальный источник: {self.place["name"]}')
        elif self.boundaries:
            self.status.set('Ни один единичный регион не покрывает эту область целиком. Выделите меньшую область.')
        else:
            self.status.set('Границы регионов еще не загружены. Выберите регион из списка.')

    def options_changed(self, *_args):
        if self.freeze:
            return
        try:
            box = self.chosen_box()
            self.map.selection = box
            self.selection_text.set(f'Выделенная область: {timing.area_km2(box):,.1f} км²' if box else 'Весь исходный регион')
        except ValueError as exc:
            self.map.selection = None
            self.selection_text.set(str(exc))
        self.map.schedule()
        self.update_estimate()
        if self.start_workers:
            if self.preview_after:
                self.root.after_cancel(self.preview_after)
            self.preview_after = self.root.after(160, self.update_preview)

    def mods_changed(self, *_args):
        self.refresh_ready()
        self.options_changed()
        if self.start_workers:
            if self.map_after:
                self.root.after_cancel(self.map_after)
            self.map_after = self.root.after(600, self.reload_map)

    def update_preview(self):
        self.preview_after = None
        if self.closing:
            return
        self.preview_version += 1
        version = self.preview_version
        look, include, mods = self.chosen_look(), self.chosen_include(), self.mods.get()
        box = self.map.selection
        latitude = (box[1] + box[3]) / 2 if box else 50
        if self.preview_future:
            self.preview_future.cancel()

        def work():
            try:
                import builder_preview
                image, sources = builder_preview.render(look, include, mods, latitude)
                self.lines.put(lambda: self.show_preview(version, image, sources))
            except Exception as exc:
                self.say(f'Превью материалов недоступно: {exc}')
        self.preview_future = self.pool.submit(work)

    def show_preview(self, version, image, sources):
        if version != self.preview_version:
            return
        disp_w = 290
        disp_h = round(image.height * (disp_w / image.width))
        try:
            self.preview_photo = ctk.CTkImage(light_image=image, dark_image=image, size=(disp_w, disp_h))
            self.preview_label.configure(image=self.preview_photo, text='')
        except Exception:
            resized = image.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(resized)
            self.preview_label.configure(image=self.preview_photo, text='')
        fallback = sum(v == 'colour fallback' for v in sources.values())
        self.preview_text.set('Превью генерации • фасады выбранного стиля, окна, балконы, дворовые площадки, автомобили и разметка. '
                              + (f'{fallback} текстур заменены цветными заглушками.' if fallback else ''))

    def estimate_inputs(self):
        if self.place is None:
            return None
        box = self.chosen_box()
        boundary = self.boundaries.get(self.place['id'])
        area = box or (list(boundary.bounds) if boundary is not None else None)
        slug = places.slug(self.place['id'])
        cached_pbf = country_fetch.pbf_path(ROOT, slug).is_file()
        cached_tiles = country_fetch.tiles_current(country_fetch.tiles_dir(ROOT, slug, box))
        include = self.chosen_include()
        key = timing.signature(self.place['id'], box, include, cached_pbf, cached_tiles)
        estimate, reason = timing.estimate(self.sizes.get(self.place['id']), area, include,
                                           cached_pbf, cached_tiles, self.history.get(key))
        return key, estimate, reason, cached_tiles

    def update_estimate(self):
        try:
            inputs = self.estimate_inputs()
        except ValueError:
            self.estimate_text.set('Завершите выделение области для расчета времени сборки.')
            return
        if not inputs:
            return
        _key, estimate, reason, cached = inputs
        if estimate:
            total = sum(estimate)
            self.estimate_text.set(f'Расчетное время сборки: ~{timing.duration(total*0.5)}–{timing.duration(total*2.5)}\n'
                                   f'{reason}' + ('\nКэшированные тайлы будут использованы повторно.' if cached else ''))
        else:
            self.estimate_text.set('Время сборки: размер PBF еще определяется. Сборка возможна.')

    def browse_mods(self):
        chosen = filedialog.askdirectory(initialdir=self.mods.get() or os.getcwd())
        if chosen:
            self.mods.set(chosen)

    def load_places(self, refresh=False):
        try:
            loaded = places.load_index(ROOT, refresh, self.say)
            self.lines.put(lambda: self.set_places(loaded))
            self.say(f'Загружено регионов: {len(loaded)}. Выберите страну или область.')
        except Exception as exc:
            self.say(f'Не удалось прочитать список регионов: {exc}')

    def reload(self, refresh):
        if getattr(self, 'list_future', None) and not self.list_future.done():
            return
        self.list_future = self.pool.submit(self.load_places, refresh)

    def set_places(self, loaded):
        self.places = sorted(loaded, key=lambda p: (p['name'].casefold(), p['id']))
        self.by_id = places.by_id(self.places)
        self.refill()

    def refill(self):
        needle = self.query.get().strip().casefold()
        self.shown = [place for place in self.places if not needle or needle in place['name'].casefold() or needle in place['id'].casefold()]
        self.list.delete(0, 'end')
        for place in self.shown:
            parent = places.parent_name(place, self.by_id)
            suffix = f'  —  {parent}' if parent else ''
            self.list.insert('end', f"{place['name']}{suffix}")
            if self.place and place['id'] == self.place['id']:
                self.list.selection_set('end')

    def on_select(self):
        if self.running:
            return
        selection = self.list.curselection()
        if not selection:
            return
        self.freeze = True
        self.use_box.set(False)
        self.freeze = False
        self.select_place(self.shown[selection[0]])

    def select_place(self, place, fit=True, preserve_look=False):
        self.place = place
        if not preserve_look:
            self.show_look(looks.recommended(place['id'], self.by_id))
        self.map.boundary = self.boundaries.get(place['id'])
        if fit:
            self.map.fit_source()
        self.map.schedule()
        self.refresh_ready()
        self.refill()
        if place in self.shown:
            self.list.see(self.shown.index(place))
        self.size.set(f'Источник: {place["name"]} · определение размера PBF…')
        if place['id'] in self.sizes:
            self.show_size(self.sizes[place['id']], place['id'])
        elif self.start_workers:
            if self.size_future:
                self.size_future.cancel()
            self.size_future = self.pool.submit(self.fetch_size, place['pbf'], place['id'])
        self.options_changed()

    def show_look(self, look):
        self.freeze = True
        block = looks.BLOCK_BY_ID.get(look['block'], looks.BLOCK_BY_ID['general'])
        self.block.set(block['title'])
        for slot, choices in looks.SLOTS.items():
            self.slots[slot].set(choices[look[slot]])
        self.freeze = False
        if hasattr(self, 'map'):
            self.options_changed()

    def apply_block(self):
        title = self.block.get()
        block = next((item for item in looks.BLOCKS if item['title'] == title), None)
        if block is None:
            return
        self.show_look({'block': block['id'], **block['look']})

    def chosen_look(self):
        title = self.block.get()
        block = next((item for item in looks.BLOCKS if item['title'] == title), looks.BLOCK_BY_ID['general'])
        look = {'block': block['id']}
        for slot, choices in looks.SLOTS.items():
            label = self.slots[slot].get()
            found = next((key for key, text in choices.items() if text == label), None)
            look[slot] = found or block['look'][slot]
        return looks.canonical(look)

    def chosen_include(self):
        return looks.canonical_include({key: bool(self.layers[key].get()) for key, _label, _default in looks.LAYERS})

    def chosen_box(self):
        if not self.use_box.get():
            return None
        try:
            values = [float(self.box[name].get().replace(',', '.')) for name in ('w', 's', 'e', 'n')]
        except ValueError as exc:
            raise ValueError('Координаты прямоугольника должны содержать 4 числа в градусах') from exc
        return timing.validate_box(values)

    def refresh_ready(self):
        if self.place is None:
            return
        slug_id = places.slug(self.place['id'])
        info = country_fetch.availability(slug_id, self.mods.get())
        text = {
            'installed': 'Готовый пак уже установлен в mods.',
            'local': 'Готовый пак найден на диске. Можно скопировать без сборки.',
            'url': 'Доступна прямая ссылка на готовый пак.',
            'none': 'Нет готового пака в 1 клик. Проверьте Google Drive или сгенерируйте карту.',
        }[info['state']]
        self.ready.set(f'{self.place["name"]}: {text}')
        self.download_btn.configure(state=('normal' if not self.running and info['state'] in ('local', 'url') else 'disabled'))
        self._ready = info

    def fetch_size(self, url, place_id):
        try:
            size = country_fetch.content_length(url, timeout=8)
        except Exception as exc:
            self.say(f'Не удалось узнать размер PBF: {exc}')
            size = None
        self.lines.put(lambda: self.show_size(size, place_id))

    def show_size(self, size, place_id):
        if size:
            self.sizes[place_id] = size
        if self.place and self.place['id'] == place_id:
            label = (f'{size / 2**30:.2f} GB' if size >= 2**30 else f'{size / 2**20:.0f} MB') if size else 'неизвестно'
            self.size.set(f'Источник: {self.place["name"]} · PBF: {label}')
            self.update_estimate()

    def busy(self, running):
        self.running = running
        self.map.enabled = not running
        if hasattr(self.map, 'city') and hasattr(self.map.city, 'configure'):
            self.map.city.configure(state='disabled' if running else 'normal')

        def set_state(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox,
                                      ctk.CTkButton, ctk.CTkSwitch, ctk.CTkEntry, ctk.CTkOptionMenu)):
                    if running:
                        child._before_busy = child.cget('state')
                        child.configure(state='disabled')
                    else:
                        child.configure(state=getattr(child, '_before_busy', 'normal'))
                set_state(child)

        for widget in self.controls:
            set_state(widget)

        self.list.configure(state='disabled' if running else 'normal')
        state = 'disabled' if running else 'normal'
        self.build_btn.configure(state=state)
        self.download_btn.configure(state='disabled')
        self.stop_btn.configure(state=('normal' if running else 'disabled'))

        if not running:
            self.progressbar.stop()
            self.progressbar.set(0)
            self.refresh_ready()
            self.update_estimate()
        else:
            self.progressbar.start()

    def run(self, target, estimate=None, history_key=None):
        if self.running or self.closing:
            return
        try:
            save_settings(self.mods.get())
        except OSError as exc:
            self.say(f'Не удалось сохранить настройки: {exc}')
        self.cancel = threading.Event()
        self.started = time.monotonic()
        self.active_stage = None
        self.run_estimate = estimate
        self.stage_times = {}
        self.busy(True)

        def wrap():
            result = 'Завершено'
            try:
                target()
            except InterruptedError:
                result = 'Остановлено'
                self.say('Процесс остановлен. Загруженные исходные данные сохранены для последующей сборки.')
            except Exception as exc:
                result = 'Ошибка'
                self.say(f'Ошибка сборки: {exc}')
            finally:
                self.lines.put(lambda result=result: self.finished(result, history_key))

        self.worker = threading.Thread(target=wrap, daemon=True)
        self.worker.start()

    def stage_progress(self, name, seconds):
        def update():
            if seconds is None:
                self.active_stage = name
                self.stage_started = time.monotonic()
            else:
                self.stage_times[name] = seconds
        self.lines.put(update)

    def finished(self, result, history_key):
        elapsed = time.monotonic() - self.started
        if result == 'Завершено' and history_key and len(self.stage_times) == len(timing.STAGES):
            self.history[history_key] = [self.stage_times[stage] for stage in timing.STAGES]
            try:
                timing.save_history(HISTORY, self.history)
            except OSError as exc:
                self.say(f'Не удалось сохранить тайминги: {exc}')
        self.busy(False)
        self.progress_text.set(f'{result} · прошло времени: {timing.duration(elapsed)}')

    def download_ready(self):
        if self.place is None:
            return
        info = getattr(self, '_ready', None) or {}
        slug_id = places.slug(self.place['id'])
        mods = self.mods.get()

        def target():
            if self.cancel.is_set():
                raise InterruptedError('install stopped')
            self.say(f"Установка готового пака «{self.place['name']}»...")
            country_fetch.delete_previous_mods(mods, emit=self.say)
            if info.get('state') == 'local':
                path = country_fetch.install_zip(info['path'], mods, slug_id, cancel=self.cancel)
            elif info.get('state') == 'url':
                dest = ROOT / 'out' / 'country-setup' / f'aroundworldng_{slug_id}.zip'
                country_fetch.download(info['url'], dest, self.say, self.cancel)
                path = country_fetch.install_zip(dest, mods, slug_id, cancel=self.cancel)
            else:
                self.say('Готовый пак не найден')
                return
            self.say(f'Пак успешно установлен в: {path}')
        self.run(target)

    def build(self):
        if self.running:
            return
        if self.place is None:
            messagebox.showinfo('AroundWorldNG', 'Сначала выберите регион из списка.')
            return
        try:
            box = self.chosen_box()
            look = self.chosen_look()
            include = self.chosen_include()
            boundary = self.boundaries.get(self.place['id'])
            if box and boundary is not None:
                from shapely.geometry import box as rectangle
                if not boundary.covers(rectangle(*box)):
                    raise ValueError('Выделенная область выходит за границы выбранного источника. '
                                     'Используйте кнопку «Оптимальный источник» или выделите область внутри региона.')
        except ValueError as exc:
            messagebox.showerror('AroundWorldNG', str(exc))
            return

        place, mods = self.place, self.mods.get()
        if box and boundary is None:
            self.say('Границы региона неизвестны: проверка охвата пропущена. Будут экспортированы данные внутри рамки.')
        key, estimate, _reason, _cached = self.estimate_inputs()
        block = looks.BLOCK_BY_ID.get(look['block'], looks.BLOCK_BY_ID['general'])['title']

        def target():
            log_dir = ROOT / 'out' / 'aroundworldng'
            log_dir.mkdir(parents=True, exist_ok=True)
            try:
                with open(log_dir / 'build.log', 'w', encoding='utf-8') as f:
                    f.write(f"=== AroundWorldNG Map Studio Build Log ===\n")
                    f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Region: {place['name']} (ID: {place['id']})\n")
                    f.write(f"Style: {block}\n")
                    f.write(f"Box: {box}\n")
                    f.write(f"BeamNG mods: {country_fetch.get_mods_dir(mods)}\n")
                    f.write(f"==========================================\n\n")
            except OSError:
                pass
            self.say(f"Генерация: «{place['name']}», стиль «{block}». Дороги и высоты генерируются автоматически.")
            self.say("Конфигурация считывается из aroundworldng_planet.zip. Если обновляли исходники, нажмите «Синхронизировать ядро».")
            country_fetch.build_place(place, mods, look=look, include=include, box=box,
                                      by_id=self.by_id, emit=self.say, cancel=self.cancel, progress=self.stage_progress)
            self.say(f"Полный лог сборки записан в {log_dir / 'build.log'}")

        self.run(target, estimate=estimate, history_key=key)

    def stop(self):
        if self.running and self.cancel is not None:
            self.cancel.set()
            self.say('Остановка после завершения текущего шага…')

    def refresh_planet(self):
        if self.running:
            return
        mods = self.mods.get()
        self.map_version += 1
        if self.map_after:
            self.root.after_cancel(self.map_after)
            self.map_after = None

        if self.map.data and self.map.data.archive:
            self.map.data.close()
            self.map.data.archive = None
            self.map.data.index = {}
            self.map.schedule()

        def target():
            try:
                country_fetch.refresh_planet(mods, self.say, cancel=self.cancel)
            finally:
                self.lines.put(self.reload_map)

        self.run(target)


def main():
    root = create_root()
    Setup(root)
    root.mainloop()


if __name__ == '__main__':
    main()
