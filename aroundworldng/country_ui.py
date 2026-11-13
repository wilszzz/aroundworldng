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
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

import country_fetch
import looks
import places
import builder_estimate as timing
from builder_map import MapData, RegionMap, project, unproject, FALLBACK_CITIES

if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).resolve().parent
    HERE = Path(__file__).resolve().parent
else:
    HERE = Path(__file__).resolve().parent
    ROOT = HERE.parent
SETTINGS = ROOT / 'country_setup.json'
HISTORY = ROOT / 'out' / 'country-setup' / 'build-times.json'
READY_MAPS_URL = 'https://drive.google.com/drive/folders/1n3A-msXrJtuQ2qJKn7YqzCooLZyliKMy?usp=drive_link'

from collections import OrderedDict
import zipfile

# Studio Workstation Palette - dark matte graphite (#292929) with dusty rose accent (#C88E9b)
PALETTE = {
    'bg_app': '#1c1c1f',           # Root window background
    'bg_panel': '#232326',         # Main column panels
    'bg_card': '#292929',          # Section containers / cards (#292929)
    'bg_card_selected': '#382f34', # Selected card background with rose tint
    'card_selected': '#382f34',    # Selected card alias
    'bg_input': '#1a1a1d',         # Text entries, listbox, canvas bg
    'border': '#3d3a3d',           # Subtle structural borders
    'border_highlight': '#C88E9b', # Accent border (#C88E9b)
    'accent': '#C88E9b',           # Primary accent (#C88E9b)
    'accent_hover': '#dca0ae',     # Accent hover
    'accent_dim': '#63474f',       # Muted accent for borders
    'text_primary': '#f7f2f4',      # High-contrast soft white-rose
    'text_secondary': '#c7bec2',    # Muted secondary text
    'text_dim': '#8f8588',          # Small hints, metadata
    'btn_default': '#36363a',      # Standard button
    'btn_default_hover': '#45454b',# Standard button hover
    'btn_primary': '#C88E9b',      # Primary button (#C88E9b)
    'btn_primary_hover': '#dca0ae',# Primary button hover
    'btn_primary_text': '#19191c', # High contrast text on rose button
    'btn_danger': '#452226',       # Stop/delete button
    'btn_danger_hover': '#5c2d33', # Stop/delete button hover
    'btn_danger_text': '#ffa8b0',  # Danger text
    'progress_track': '#26262a',   # Progress bar track
    'progress_bar': '#C88E9b',     # Progress bar fill (#C88E9b)
    'selection_badge': '#C88E9b',  # Accent selection badge
}

CONTINENT_MAP = OrderedDict([
    ('Все континенты', None),
    ('Россия', 'russia'),
    ('Европа', 'europe'),
    ('Северная Америка', 'north-america'),
    ('Азия', 'asia'),
    ('Южная Америка', 'south-america'),
    ('Африка', 'africa'),
    ('Австралия и Океания', 'australia-oceania'),
    ('Центральная Америка', 'central-america'),
    ('Антарктида', 'antarctica'),
])

CONTINENT_ROOTS = {'russia', 'europe', 'asia', 'north-america', 'south-america', 'africa', 'australia-oceania', 'central-america', 'antarctica'}

# Soft, rounded modern typography
def get_rounded_font():
    import tkinter.font as tkfont
    try:
        available = set(tkfont.families())
        for candidate in ('Rubik', 'Comfortaa', 'Nunito', 'Segoe UI Variable Text', 'Century Gothic', 'Segoe UI'):
            if candidate in available:
                return candidate
    except Exception:
        pass
    return 'Rubik'


FONT_FAMILY = get_rounded_font()

COUNTRY_TRANSLATIONS = {
    'russia': 'Россия (Вся страна)',
    'germany': 'Германия',
    'france': 'Франция',
    'italy': 'Италия',
    'united-kingdom': 'Великобритания',
    'england': 'Англия',
    'spain': 'Испания',
    'poland': 'Польша',
    'belarus': 'Беларусь',
    'ukraine': 'Украина',
    'kazakhstan': 'Казахстан',
    'us': 'США (United States)',
    'canada': 'Канада',
    'mexico': 'Мексика',
    'china': 'Китай',
    'japan': 'Япония',
    'turkey': 'Турция',
    'finland': 'Финляндия',
    'sweden': 'Швеция',
    'norway': 'Норвегия',
    'austria': 'Австрия',
    'switzerland': 'Швейцария',
    'czech-republic': 'Чехия',
    'netherlands': 'Нидерланды',
    'belgium': 'Бельгия',
    'georgia': 'Грузия',
    'armenia': 'Армения',
    'azerbaijan': 'Азербайджан',
    'greece': 'Греция',
    'portugal': 'Португалия',
    'brazil': 'Бразилия',
    'argentina': 'Аргентина',
    'australia': 'Австралия',
    # Specific Russian regions & subjects (without Novaya Zemlya or extra territories)
    'russia/saint-petersburg': 'Санкт-Петербург (город, СПб, Питер)',
    'russia/leningrad-oblast': 'Ленинградская область (СПб и ЛО)',
    'russia/moscow': 'Москва (город, Мск)',
    'russia/moscow-oblast': 'Московская область (Москва и МО)',
    'russia/krasnodar': 'Краснодарский край и Сочи',
    'russia/tatarstan': 'Республика Татарстан (Казань)',
    'russia/sverdlovsk': 'Свердловская область (Екатеринбург)',
    'russia/novosibirsk': 'Новосибирская область',
    'russia/nizhny-novgorod': 'Нижегородская область',
    'russia/samara': 'Самарская область',
    'russia/rostov': 'Ростовская область',
    'russia/kaliningrad-region': 'Калининградская область (регион)',
    'russia/crimea': 'Республика Крым и Севастополь',
    'russia/primorsky': 'Приморский край (Владивосток)',
    'russia/karelia': 'Республика Карелия (Петрозаводск)',
    'russia/irkutsk': 'Иркутская область и Байкал',
    'russia/murmansk': 'Мурманская область (Кольский п-ов)',
    'russia/arkhangelsk': 'Архангельская область (материк без островов)',
    'russia/pskov': 'Псковская область',
    'russia/novgorod': 'Новгородская область',
    'russia/vologda': 'Вологодская область',
    'russia/voronezh': 'Воронежская область',
    'russia/volgograd': 'Волгоградская область',
    'russia/bashkortostan': 'Республика Башкортостан (Уфа)',
    'russia/perm': 'Пермский край',
    'russia/chelyabinsk': 'Челябинская область',
    'russia/tyumen': 'Тюменская область',
    'russia/krasnoyarsk': 'Красноярский край (Юг / Центр)',
    'russia/stavropol': 'Ставропольский край / КМВ',
    'russia/yaroslavl': 'Ярославская область',
    'russia/tver': 'Тверская область',
    # Federal Districts (clamped to mainland inhabited latitudes)
    'central-fed-district': 'Центральный ФО (все 18 областей)',
    'northwestern-fed-district': 'Северо-Западный ФО (материк без Новой Земли)',
    'siberian-fed-district': 'Сибирский ФО (вся Сибирь)',
    'ural-fed-district': 'Уральский ФО (весь Урал)',
    'volga-fed-district': 'Приволжский ФО (весь Поволжье)',
    'south-fed-district': 'Южный ФО (весь Юг России)',
    'north-caucasus-fed-district': 'Северо-Кавказский ФО (весь Кавказ)',
    'far-eastern-fed-district': 'Дальневосточный ФО (весь Дальний Восток)',
    'kaliningrad': 'Калининградская область',
    'crimean-fed-district': 'Крымский ФО',
}


def resolve_parent_id(item, by_id):
    pid = item.get('id', '')
    if '/' in pid:
        prefix = pid.split('/')[0]
        if prefix in by_id:
            return prefix
    return item.get('parent') or ''


def get_extract_continent(item, by_id):
    cid = item.get('id', '')
    if cid == 'russia' or item.get('parent') == 'russia' or cid.startswith('russia/'):
        return 'russia'
    curr = item
    while True:
        curr_id = curr.get('id', '')
        if curr_id in CONTINENT_ROOTS:
            return curr_id
        pid = resolve_parent_id(curr, by_id)
        if not pid or pid not in by_id:
            break
        curr = by_id[pid]
    return 'other'


def get_extract_country(item, by_id):
    cid = item.get('id', '')
    if cid == 'russia' or item.get('parent') == 'russia' or cid.startswith('russia/'):
        return 'russia'
    chain = [item]
    curr = item
    while True:
        pid = resolve_parent_id(curr, by_id)
        if not pid or pid not in by_id:
            break
        curr = by_id[pid]
        chain.append(curr)
    if len(chain) >= 2 and chain[-1].get('id') in CONTINENT_ROOTS:
        return chain[-2].get('id')
    return item.get('id')


# BeamNG Driving Discipline Templates: (Title, Icon, lon_w, lat_s, lon_e, lat_n, place_slug, style_block)
TRACK_SCENARIOS = [
    ('Стрит / Дрифт', '🏙️', 30.295, 59.925, 30.360, 59.955, 'russia/saint-petersburg', 'modern'),
    ('Хайвей Wangan', '🛣️', 30.410, 59.835, 30.490, 59.885, 'russia/saint-petersburg', 'modern'),
    ('Серпантин Touge', '⛰️', 40.280, 43.660, 40.335, 43.700, 'russia/krasnodar', 'village'),
    ('Ралли Ленобласть', '🌲', 30.150, 60.180, 30.240, 60.235, 'russia/leningrad-oblast', 'village'),
]

# Iconic World Driving Spots for the Random button
RANDOM_SPOTS = [
    {
        'title': 'Nürburgring Nordschleife (Германия)',
        'box': [6.940, 50.320, 7.020, 50.370],
        'place_id': 'germany',
        'desc': 'Культовая трасса «Зелёный ад»'
    },
    {
        'title': 'Shuto C1 Loop Tokyo (Япония)',
        'box': [139.750, 35.655, 139.785, 35.685],
        'place_id': 'japan',
        'desc': 'Ночной скоростной хайвей Ванган'
    },
    {
        'title': 'Monaco GP & Marina (Монако)',
        'box': [7.410, 43.725, 7.435, 43.745],
        'place_id': 'france',
        'desc': 'Знаменитые улицы и набережная'
    },
    {
        'title': 'Transfăgărășan Pass (Румыния)',
        'box': [24.580, 45.580, 24.640, 45.620],
        'place_id': 'romania',
        'desc': 'Один из красивейших высокогорных перевалов'
    },
    {
        'title': 'Stelvio Pass (Альпы, Италия)',
        'box': [10.420, 46.510, 10.480, 46.550],
        'place_id': 'italy',
        'desc': 'Экстремальный горный серпантин'
    },
    {
        'title': 'Сочи Автодром & Олимпийский парк',
        'box': [39.950, 43.400, 39.980, 43.425],
        'place_id': 'russia/krasnodar',
        'desc': 'Черноморское побережье и гоночный трек'
    },
    {
        'title': 'Санкт-Петербург: Невский & Набережные',
        'box': [30.290, 59.925, 30.360, 59.955],
        'place_id': 'russia/saint-petersburg',
        'desc': 'Мосты, каналы и прямые проспекты'
    },
    {
        'title': 'Красная Поляна: Роза Хутор Touge',
        'box': [40.280, 43.660, 40.330, 43.700],
        'place_id': 'russia/krasnodar',
        'desc': 'Крутой горный подъем и шпильки на Кавказе'
    }
]


def load_settings():
    mods = str(country_fetch.default_mods())
    settings = {'mods': mods, 'query': '', 'bookmarks': []}
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict):
            if isinstance(saved.get('mods'), str):
                settings['mods'] = saved['mods']
            if isinstance(saved.get('bookmarks'), list):
                settings['bookmarks'] = saved['bookmarks']
    return settings


def save_settings(mods, bookmarks=None):
    data = {'mods': mods}
    if bookmarks is not None:
        data['bookmarks'] = bookmarks
    else:
        try:
            if SETTINGS.exists():
                old = json.loads(SETTINGS.read_text(encoding='utf-8'))
                if isinstance(old.get('bookmarks'), list):
                    data['bookmarks'] = old['bookmarks']
        except Exception:
            pass
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def create_root():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk(fg_color=PALETTE['bg_app'])
    return root


class MapNameDialog(ctk.CTkToplevel):
    """Modal dialog prompting the user for a clean map name every time before creation."""
    def __init__(self, parent, default_name=""):
        super().__init__(parent)
        self.title("Название карты")
        self.result = None
        self.geometry("460x220")
        self.resizable(False, False)
        self.configure(fg_color=PALETTE['bg_card'])
        self.lift()
        self.attributes("-topmost", True)
        self.grab_set()

        ctk.CTkLabel(self, text="Укажите название карты для BeamNG.drive:",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', padx=20, pady=(18, 4))

        ctk.CTkLabel(self, text="Понятное имя отображается в списке карт BeamNG и в названии файла.",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                     text_color=PALETTE['text_dim']).pack(anchor='w', padx=20, pady=(0, 12))

        self.entry = ctk.CTkEntry(self, height=36,
                                  fg_color=PALETTE['bg_input'],
                                  border_color=PALETTE['border_highlight'],
                                  text_color=PALETTE['text_primary'],
                                  font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.entry.pack(fill='x', padx=20, pady=(0, 16))
        if default_name:
            self.entry.insert(0, default_name)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill='x', padx=20, pady=(0, 14))

        ctk.CTkButton(btn_row, text="Создать карту", width=140, height=32,
                      fg_color=PALETTE['btn_primary'],
                      hover_color=PALETTE['btn_primary_hover'],
                      text_color=PALETTE['btn_primary_text'],
                      font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                      command=self._on_ok).pack(side='right', padx=(8, 0))

        ctk.CTkButton(btn_row, text="Отмена", width=90, height=32,
                      fg_color=PALETTE['btn_default'],
                      hover_color=PALETTE['btn_default_hover'],
                      text_color=PALETTE['text_primary'],
                      font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                      command=self._on_cancel).pack(side='right')

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.after(100, self._focus)

    def _focus(self):
        try:
            self.entry.focus_set()
            self.entry.select_range(0, 'end')
        except Exception:
            pass

    def _on_ok(self):
        val = self.entry.get().strip()
        if not val:
            return
        self.result = val
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()

    def get_name(self):
        self.wait_window()
        return self.result


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
        root.geometry('1420x920')
        root.minsize(1220, 800)
        root.protocol('WM_DELETE_WINDOW', self.close)

        # Style standard ttk widgets for a unified utilitarian engineering look
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TFrame', background=PALETTE['bg_panel'])
        style.configure('TLabel', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=(FONT_FAMILY, 11))
        style.configure('TRadiobutton', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=(FONT_FAMILY, 11), indicatorcolor=PALETTE['bg_input'])
        style.map('TRadiobutton', background=[('active', PALETTE['bg_card'])], foreground=[('active', '#ffffff')])
        style.configure('TCheckbutton', background=PALETTE['bg_panel'], foreground=PALETTE['text_primary'], font=(FONT_FAMILY, 11), indicatorcolor=PALETTE['bg_input'])
        style.map('TCheckbutton', background=[('active', PALETTE['bg_card'])], foreground=[('active', '#ffffff')])
        style.configure('TButton', background=PALETTE['btn_default'], foreground=PALETTE['text_primary'], borderwidth=1, bordercolor=PALETTE['border'], focusthickness=0, font=(FONT_FAMILY, 11))
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
        self.build_mode = tk.StringVar(value='standalone')
        self.map_title = tk.StringVar(value='')
        self.current_preset_title = None

        self.continent_var = ctk.StringVar(value='Россия')
        self.country_var = ctk.StringVar(value='Россия (все округа)')

        self._build()
        self.show_look(looks.canonical({'block': 'general'}))
        self.select_mode('ready')

        for variable in [*self.slots.values(), *self.layers.values(), self.use_box, *self.box.values()]:
            variable.trace_add('write', self.options_changed)
        self.mods.trace_add('write', self.mods_changed)

        root.after(200, self.pump)
        if start_workers:
            self.reload(False)
            self.reload_map()
            self.pool.submit(self.load_boundaries)
            root.after(800, self.refresh_installed_maps)

    def _build(self):
        # Main horizontal container across the entire window
        main_layout = ctk.CTkFrame(self.root, fg_color="transparent")
        main_layout.pack(fill='both', expand=True, padx=8, pady=8)

        # =========================================================================
        # 1. LEFT PANEL (Width: 320px fixed) — Library, Explorer & System Settings
        # =========================================================================
        self.left_panel = ctk.CTkFrame(main_layout, width=320, corner_radius=10,
                                      fg_color=PALETTE['bg_panel'],
                                      border_width=1, border_color=PALETTE['border'])
        self.left_panel.pack(side='left', fill='y', padx=(0, 6))
        self.left_panel.pack_propagate(False)

        # --- Brand Header ---
        brand_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        brand_box.pack(fill='x', padx=12, pady=(12, 8))

        ctk.CTkLabel(brand_box, text='AroundWorldNG',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w')
        ctk.CTkLabel(brand_box, text='STUDIO WORKSTATION',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color=PALETTE['border_highlight']).pack(anchor='w', pady=(1, 0))

        # Divider
        ctk.CTkFrame(self.left_panel, height=1, fg_color=PALETTE['border']).pack(fill='x', padx=10, pady=(4, 8))

        # --- Section: Map Scale & Bounds Presets ("Формат и размер карты BeamNG") ---
        scale_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        scale_header.pack(fill='x', padx=12, pady=(0, 2))
        ctk.CTkLabel(scale_header, text='📐 ФОРМАТ И РАЗМЕР КАРТЫ',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['border_highlight']).pack(anchor='w')

        ctk.CTkLabel(self.left_panel, text='Быстрый масштаб области вокруг центра:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', padx=12, pady=(0, 4))

        scale_grid = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        scale_grid.pack(fill='x', padx=10, pady=(0, 4))
        scale_grid.columnconfigure(0, weight=1)
        scale_grid.columnconfigure(1, weight=1)

        scales = [
            ('🏎️ 1.5 × 1.5 км', 1.5, 'Дрифт / Квартал'),
            ('🏙️ 3.0 × 3.0 км', 3.0, 'Город (Оптимально)'),
            ('🛣️ 5.0 × 5.0 км', 5.0, 'Шоссе и трассы'),
            ('⛰️ 8.0 × 8.0 км', 8.0, 'Огромный открытый мир'),
        ]

        for idx, (label, km, desc) in enumerate(scales):
            row = idx // 2
            col = idx % 2
            btn = ctk.CTkButton(
                scale_grid,
                text=label,
                height=30,
                anchor='center',
                font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                fg_color=PALETTE['bg_card'],
                text_color=PALETTE['text_primary'],
                hover_color=PALETTE['btn_default_hover'],
                corner_radius=8,
                command=lambda _km=km: self.apply_map_scale(_km)
            )
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")

        # Utility row: Center on map view & Bookmarks
        util_row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        util_row.pack(fill='x', padx=10, pady=(2, 4))

        self.btn_center_view = ctk.CTkButton(
            util_row, text='🎯 По центру вида', height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=PALETTE['bg_card'], text_color=PALETTE['text_secondary'],
            hover_color=PALETTE['btn_default_hover'], corner_radius=8,
            command=self.center_box_on_view
        )
        self.btn_center_view.pack(side='left', fill='x', expand=True, padx=(0, 3))

        self.btn_bookmark = ctk.CTkButton(
            util_row, text='⭐ В закладки', height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=PALETTE['bg_card'], text_color=PALETTE['text_secondary'],
            hover_color=PALETTE['btn_default_hover'], corner_radius=8,
            command=self.add_bookmark
        )
        self.btn_bookmark.pack(side='left', fill='x', expand=True, padx=(3, 0))

        # Bookmarks selector dropdown
        self.bookmark_var = tk.StringVar(value='⭐ Мои закладки (0)')
        self.bookmark_menu = ctk.CTkOptionMenu(
            self.left_panel,
            variable=self.bookmark_var,
            values=['Нет сохраненных закладок'],
            height=26,
            fg_color=PALETTE['bg_input'],
            button_color=PALETTE['btn_default'],
            button_hover_color=PALETTE['btn_default_hover'],
            dropdown_fg_color=PALETTE['bg_card'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            command=self.on_bookmark_selected
        )
        self.bookmark_menu.pack(fill='x', padx=10, pady=(0, 6))

        # Divider
        ctk.CTkFrame(self.left_panel, height=1, fg_color=PALETTE['border']).pack(fill='x', padx=10, pady=(2, 8))

        # --- Section: Region Catalog ("Каталог регионов") ---
        catalog_header = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        catalog_header.pack(fill='x', padx=12, pady=(0, 4))
        ctk.CTkLabel(catalog_header, text='КАТАЛОГ РЕГИОНОВ',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        # 1. Continent Selector
        cont_row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        cont_row.pack(fill='x', padx=10, pady=(0, 4))
        ctk.CTkLabel(cont_row, text='Континент:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(0, 1))

        self.continent_menu = ctk.CTkOptionMenu(
            cont_row,
            variable=self.continent_var,
            values=list(CONTINENT_MAP.keys()),
            height=28,
            fg_color=PALETTE['bg_input'],
            button_color=PALETTE['btn_default'],
            button_hover_color=PALETTE['btn_default_hover'],
            dropdown_fg_color=PALETTE['bg_card'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self.on_continent_changed
        )
        self.continent_menu.pack(fill='x')

        # 2. Country Selector
        ctry_row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        ctry_row.pack(fill='x', padx=10, pady=(0, 4))
        ctk.CTkLabel(ctry_row, text='Страна:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(0, 1))

        self.country_menu = ctk.CTkOptionMenu(
            ctry_row,
            variable=self.country_var,
            values=['Россия (все округа)'],
            height=28,
            fg_color=PALETTE['bg_input'],
            button_color=PALETTE['btn_default'],
            button_hover_color=PALETTE['btn_default_hover'],
            dropdown_fg_color=PALETTE['bg_card'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self.on_country_changed
        )
        self.country_menu.pack(fill='x')

        # 3. Search Row (Global or filtered search)
        search_row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        search_row.pack(fill='x', padx=10, pady=(4, 6))

        self.entry_search = ctk.CTkEntry(search_row, textvariable=self.query, height=30,
                                         placeholder_text="🔍 Поиск страны или региона...",
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                         fg_color=PALETTE['bg_input'],
                                         border_color=PALETTE['border'])
        self.entry_search.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.entry_search.bind('<KeyRelease>', lambda _event: self.refill())

        self.btn_reload = ctk.CTkButton(search_row, text='🔄', width=38, height=30,
                                        fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                                        corner_radius=8,
                                        command=lambda: self.reload(True))
        self.btn_reload.pack(side='left')

        # 4. Listbox Container
        list_container = ctk.CTkFrame(self.left_panel, corner_radius=10,
                                      fg_color=PALETTE['bg_input'],
                                      border_width=1, border_color=PALETTE['border'])
        list_container.pack(fill='both', expand=True, padx=10, pady=(0, 8))

        self.list = tk.Listbox(list_container, exportselection=False,
                               bg=PALETTE['bg_input'], fg=PALETTE['text_primary'],
                               selectbackground=PALETTE['border_highlight'], selectforeground='#ffffff',
                               highlightthickness=0, bd=0, font=(FONT_FAMILY, 11), activestyle='none')
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
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        ctk.CTkLabel(sys_box, text='Папка модов BeamNG.drive:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(3, 1))

        mods_row = ctk.CTkFrame(sys_box, fg_color="transparent")
        mods_row.pack(fill='x', pady=(0, 6))

        self.entry_mods = ctk.CTkEntry(mods_row, textvariable=self.mods, height=28,
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                                       fg_color=PALETTE['bg_input'],
                                       border_color=PALETTE['border'])
        self.entry_mods.pack(side='left', fill='x', expand=True, padx=(0, 4))

        self.btn_browse = ctk.CTkButton(mods_row, text='Обзор…', width=60, height=28,
                                        fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                                        corner_radius=8,
                                        command=self.browse_mods)
        self.btn_browse.pack(side='left')

        self.btn_sync = ctk.CTkButton(sys_box, text='Синхронизировать ядро', height=30,
                                      fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                      text_color=PALETTE['text_primary'],
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                      corner_radius=8,
                                      command=self.refresh_planet)
        self.btn_sync.pack(fill='x')

        # =========================================================================
        # 2. CENTER PANEL (Flexible / Expands) — Viewport & Telemetry Console
        # =========================================================================
        self.center_panel = ctk.CTkFrame(main_layout, corner_radius=10,
                                        fg_color=PALETTE['bg_panel'],
                                        border_width=1, border_color=PALETTE['border'])
        self.center_panel.pack(side='left', fill='both', expand=True, padx=(0, 6))

        # --- Interactive Map Viewport ---
        map_wrapper = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        map_wrapper.pack(fill='both', expand=True, padx=8, pady=(8, 4))

        self.map = RegionMap(map_wrapper, self.select_box, on_city_select=self.on_city_selected)
        self.map.pack(fill='both', expand=True)
        self.map.canvas.configure(background=PALETTE['bg_input'], highlightbackground=PALETTE['border'])

        # --- Selection Details Sub-bar ---
        subbar = ctk.CTkFrame(self.center_panel, height=38, corner_radius=8,
                              fg_color=PALETTE['bg_card'],
                              border_width=1, border_color=PALETTE['border'])
        subbar.pack(fill='x', padx=8, pady=(0, 6))

        subbar_inner = ctk.CTkFrame(subbar, fg_color="transparent")
        subbar_inner.pack(fill='x', padx=8, pady=4)

        self.lbl_selection = ctk.CTkLabel(subbar_inner, textvariable=self.selection_text,
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                          text_color=PALETTE['selection_badge'])
        self.lbl_selection.pack(side='left', padx=(0, 8))

        self.btn_whole = ctk.CTkButton(subbar_inner, text='Весь регион', width=95, height=26,
                                       fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                       text_color=PALETTE['text_primary'],
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                       corner_radius=8,
                                       command=self.clear_box)
        self.btn_whole.pack(side='left', padx=(0, 4))

        self.btn_optimize = ctk.CTkButton(subbar_inner, text='Оптимальный источник', width=160, height=26,
                                          fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                          text_color=PALETTE['text_primary'],
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                          corner_radius=8,
                                          command=self.optimize_source)
        self.btn_optimize.pack(side='left')

        # --- Telemetry & Terminal Console (Bottom of Center Panel) ---
        console_frame = ctk.CTkFrame(self.center_panel, corner_radius=8,
                                     fg_color=PALETTE['bg_card'],
                                     border_width=1, border_color=PALETTE['border'])
        console_frame.pack(fill='x', padx=8, pady=(0, 8))

        console_header = ctk.CTkFrame(console_frame, fg_color="transparent")
        console_header.pack(fill='x', padx=8, pady=(6, 2))

        self.lbl_progress = ctk.CTkLabel(console_header, textvariable=self.progress_text,
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                         text_color=PALETTE['text_primary'])
        self.lbl_progress.pack(side='left')

        self.lbl_status = ctk.CTkLabel(console_header, textvariable=self.status,
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                                       text_color=PALETTE['text_secondary'])
        self.lbl_status.pack(side='right', padx=(10, 0))

        self.progressbar = ctk.CTkProgressBar(console_frame, height=5,
                                              fg_color=PALETTE['progress_track'],
                                              progress_color=PALETTE['progress_bar'])
        self.progressbar.pack(fill='x', padx=8, pady=(2, 6))
        self.progressbar.set(0)

        self.log = ctk.CTkTextbox(console_frame, height=96,
                                  font=ctk.CTkFont(family="Consolas", size=10),
                                  fg_color=PALETTE['bg_input'],
                                  text_color=PALETTE['text_primary'],
                                  border_width=1, border_color=PALETTE['border'],
                                  corner_radius=8)
        self.log.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.log.configure(state='disabled')

        # =========================================================================
        # 3. RIGHT PANEL (Width: 400px fixed) — Production Launch & Inspector
        # =========================================================================
        self.right_panel = ctk.CTkFrame(main_layout, width=440, corner_radius=10,
                                       fg_color=PALETTE['bg_panel'],
                                       border_width=1, border_color=PALETTE['border'])
        self.right_panel.pack(side='left', fill='y', padx=0)
        self.right_panel.pack_propagate(False)

        # --- Section: Production & Build Card ---
        prod_card = ctk.CTkFrame(self.right_panel, corner_radius=10,
                                 fg_color=PALETTE['bg_card'],
                                 border_width=1, border_color=PALETTE['border'])
        prod_card.pack(fill='x', padx=8, pady=(8, 6))

        ctk.CTkLabel(prod_card, text='ПРОИЗВОДСТВО КАРТЫ',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', padx=10, pady=(8, 6))

        # Two Distinct Prominent Mode Cards
        mode_box = ctk.CTkFrame(prod_card, fg_color="transparent")
        mode_box.pack(fill='x', padx=10, pady=(0, 8))

        ctk.CTkLabel(mode_box, text='ВЫБЕРИТЕ РЕЖИМ ГЕНЕРАЦИИ:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(0, 4))

        # CARD 1: Ready Standalone Level (Recommended)
        self.card_ready = ctk.CTkFrame(mode_box, corner_radius=10,
                                       fg_color=PALETTE['bg_card_selected'],
                                       border_width=2, border_color=PALETTE['border_highlight'],
                                       cursor="hand2")
        self.card_ready.pack(fill='x', pady=(0, 6))

        card_ready_inner = ctk.CTkFrame(self.card_ready, fg_color="transparent")
        card_ready_inner.pack(fill='x', padx=8, pady=6)

        c1_top = ctk.CTkFrame(card_ready_inner, fg_color="transparent")
        c1_top.pack(fill='x')
        ctk.CTkLabel(c1_top, text='🏁 ГОТОВАЯ КАРТА ДЛЯ BeamNG',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(side='left')
        ctk.CTkLabel(c1_top, text='[⚡ Рекомендуется]',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color=PALETTE['border_highlight']).pack(side='right')

        c1_desc = (
            "• Автономная трасса прямо в меню уровней BeamNG\n"
            "• 3D-рельеф (высоты) + асфальт DecalRoad с разметкой\n"
            "• 3D-здания с физической коллизией + деревья и фонари\n"
            "• Мгновенный запуск за 3-5 секунд!"
        )
        ctk.CTkLabel(card_ready_inner, text=c1_desc, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(3, 2))

        self.lbl_card_ready_ind = ctk.CTkLabel(card_ready_inner, text='● ВЫБРАН РЕЖИМ ГОТОВОЙ КАРТЫ',
                                               font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                               text_color=PALETTE['border_highlight'])
        self.lbl_card_ready_ind.pack(anchor='w')

        # CARD 2: Planet Streaming Pack
        self.card_planet = ctk.CTkFrame(mode_box, corner_radius=10,
                                        fg_color=PALETTE['bg_card'],
                                        border_width=1, border_color=PALETTE['border'],
                                        cursor="hand2")
        self.card_planet.pack(fill='x', pady=(0, 6))

        card_planet_inner = ctk.CTkFrame(self.card_planet, fg_color="transparent")
        card_planet_inner.pack(fill='x', padx=8, pady=6)

        c2_top = ctk.CTkFrame(card_planet_inner, fg_color="transparent")
        c2_top.pack(fill='x')
        ctk.CTkLabel(c2_top, text='🌍 ПАК ДЛЯ ПЛАНЕТЫ',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(side='left')
        ctk.CTkLabel(c2_top, text='[Глобальный мир]',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(side='right')

        c2_desc = (
            "• Стриминг дорог на лету по глобальной сетке планеты\n"
            "• Бесшовные поездки по всей планете Земля\n"
            "• Требует установленный базовый мод Планеты"
        )
        ctk.CTkLabel(card_planet_inner, text=c2_desc, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(3, 2))

        self.lbl_card_planet_ind = ctk.CTkLabel(card_planet_inner, text='○ Нажмите, чтобы выбрать этот режим',
                                                font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                                                text_color=PALETTE['text_dim'])
        self.lbl_card_planet_ind.pack(anchor='w')

        # Bind clicks to entire cards
        self._bind_card(self.card_ready, 'ready')
        self._bind_card(self.card_planet, 'planet')

        # Map Name Field
        title_box = ctk.CTkFrame(prod_card, fg_color="transparent")
        title_box.pack(fill='x', padx=10, pady=(0, 6))

        ctk.CTkLabel(title_box, text='НАЗВАНИЕ КАРТЫ (ДЛЯ BeamNG):',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(0, 2))

        self.title_entry = ctk.CTkEntry(
            title_box,
            textvariable=self.map_title,
            height=32,
            placeholder_text="Введите понятное название карты...",
            fg_color=PALETTE['bg_input'],
            border_color=PALETTE['border'],
            text_color=PALETTE['text_primary'],
            font=ctk.CTkFont(family=FONT_FAMILY, size=11)
        )
        self.title_entry.pack(fill='x')

        self.build_btn = ctk.CTkButton(prod_card, text='🚀 СОБРАТЬ ГОТОВУЮ КАРТУ',
                                       height=42,
                                       fg_color=PALETTE['btn_primary'],
                                       hover_color=PALETTE['btn_primary_hover'],
                                       text_color=PALETTE['btn_primary_text'],
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                                       corner_radius=12,
                                       command=self.build)
        self.build_btn.pack(fill='x', padx=10, pady=(4, 6))

        btn_subrow = ctk.CTkFrame(prod_card, fg_color="transparent")
        btn_subrow.pack(fill='x', padx=10, pady=(0, 8))

        self.stop_btn = ctk.CTkButton(btn_subrow, text='Прервать', width=80, height=28,
                                      fg_color=PALETTE['btn_danger'],
                                      hover_color=PALETTE['btn_danger_hover'],
                                      text_color=PALETTE['btn_danger_text'],
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                      corner_radius=8,
                                      state='disabled', command=self.stop)
        self.stop_btn.pack(side='left', padx=(0, 4))

        self.download_btn = ctk.CTkButton(btn_subrow, text='Готовый пак', width=110, height=28,
                                          fg_color=PALETTE['btn_default'],
                                          hover_color=PALETTE['btn_default_hover'],
                                          text_color=PALETTE['text_primary'],
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                          corner_radius=8,
                                          command=self.download_ready)
        self.download_btn.pack(side='left', padx=(0, 4))

        self.gdrive_btn = ctk.CTkButton(btn_subrow, text='Google Drive', width=110, height=28,
                                        fg_color=PALETTE['btn_default'],
                                        hover_color=PALETTE['btn_default_hover'],
                                        text_color=PALETTE['text_primary'],
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                        corner_radius=8,
                                        command=lambda: webbrowser.open(READY_MAPS_URL))
        self.gdrive_btn.pack(side='left')

        # Status & Estimates in Production Card
        est_box = ctk.CTkFrame(prod_card, fg_color="transparent")
        est_box.pack(fill='x', padx=10, pady=(0, 8))

        ctk.CTkLabel(est_box, textvariable=self.estimate_text, wraplength=410, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                     text_color=PALETTE['text_secondary']).pack(anchor='w')

        ctk.CTkLabel(est_box, textvariable=self.ready, wraplength=360, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(2, 0))

        ctk.CTkLabel(est_box, textvariable=self.size, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(1, 0))

        # --- Section: Parameter Tabs / Inspector ---
        self.tabs = ctk.CTkTabview(self.right_panel, corner_radius=10,
                                   fg_color=PALETTE['bg_card'],
                                   segmented_button_fg_color=PALETTE['bg_input'],
                                   segmented_button_selected_color=PALETTE['btn_primary'],
                                   segmented_button_selected_hover_color=PALETTE['btn_primary_hover'],
                                   text_color=PALETTE['text_primary'],
                                   segmented_button_font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"))
        self.tabs.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        tab_style = self.tabs.add('🎨 Стиль')
        tab_layers = self.tabs.add('🗺️ Слои')
        tab_coords = self.tabs.add('📐 Границы')
        tab_maps = self.tabs.add('💾 Мои карты')

        # TAB 1: ARCHITECTURE
        tab_style_scroll = ctk.CTkScrollableFrame(tab_style, fg_color="transparent")
        tab_style_scroll.pack(fill='both', expand=True)

        ctk.CTkLabel(tab_style_scroll, text='Стиль застройки (Asset Block):',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(2, 2))

        titles = [block['title'] for block in looks.BLOCKS]
        self.block_menu = ctk.CTkOptionMenu(tab_style_scroll, variable=self.block, values=titles,
                                            height=28,
                                            fg_color=PALETTE['bg_input'],
                                            button_color=PALETTE['btn_default'],
                                            button_hover_color=PALETTE['btn_default_hover'],
                                            dropdown_fg_color=PALETTE['bg_card'],
                                            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                            command=lambda _val: self.apply_block())
        self.block_menu.pack(fill='x', pady=(0, 8))

        ctk.CTkLabel(tab_style_scroll, text='Индивидуальные слоты материалов:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(2, 2))

        self.slot_menus = {}
        for slot, label in looks.SLOT_LABELS.items():
            row = ctk.CTkFrame(tab_style_scroll, fg_color="transparent")
            row.pack(fill='x', pady=2)
            ctk.CTkLabel(row, text=label, width=120, anchor='w',
                         font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                         text_color=PALETTE['text_secondary']).pack(side='left')
            values = list(looks.SLOTS[slot].values())
            menu = ctk.CTkOptionMenu(row, variable=self.slots[slot], values=values,
                                     height=26,
                                     fg_color=PALETTE['bg_input'],
                                     button_color=PALETTE['btn_default'],
                                     button_hover_color=PALETTE['btn_default_hover'],
                                     dropdown_fg_color=PALETTE['bg_card'],
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=10))
            menu.pack(side='left', fill='x', expand=True)
            self.slot_menus[slot] = menu

        # 2D Facade Material Preview
        preview_box = ctk.CTkFrame(tab_style_scroll, corner_radius=10,
                                   fg_color=PALETTE['bg_input'],
                                   border_width=1, border_color=PALETTE['border'])
        preview_box.pack(fill='x', pady=(8, 4))

        self.preview_label = ctk.CTkLabel(preview_box, text='')
        self.preview_label.pack(padx=4, pady=4)

        ctk.CTkLabel(tab_style_scroll, textvariable=self.preview_text, wraplength=340, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w')

        # TAB 2: LAYERS
        ctk.CTkLabel(tab_layers, text='Активные слои данных OSM:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(4, 2))
        ctk.CTkLabel(tab_layers, text='(Дорожная сеть и высотный рельеф включены всегда)',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(0, 8))

        self.layer_switches = {}
        for key, label, _default in looks.LAYERS:
            sw = ctk.CTkSwitch(tab_layers, text=label, variable=self.layers[key],
                               progress_color=PALETTE['btn_primary'],
                               font=ctk.CTkFont(family=FONT_FAMILY, size=11))
            sw.pack(anchor='w', pady=4)
            self.layer_switches[key] = sw

        # TAB 3: COORDINATES (BBOX)
        ctk.CTkLabel(tab_coords, text='Ограничение области карты:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(anchor='w', pady=(4, 2))

        self.sw_box = ctk.CTkSwitch(tab_coords, text='Ограничить выбранным прямоугольником',
                                    variable=self.use_box,
                                    progress_color=PALETTE['btn_primary'],
                                    font=ctk.CTkFont(family=FONT_FAMILY, size=11))
        self.sw_box.pack(anchor='w', pady=(4, 6))

        coords_grid = ctk.CTkFrame(tab_coords, fg_color="transparent")
        coords_grid.pack(fill='x', pady=2)

        labels_ru = {'w': 'Запад (W lon)', 's': 'Юг (S lat)', 'e': 'Восток (E lon)', 'n': 'Север (N lat)'}
        for name, _hint in (('w', 'W'), ('s', 'S'), ('e', 'E'), ('n', 'N')):
            row = ctk.CTkFrame(coords_grid, fg_color="transparent")
            row.pack(fill='x', pady=3)
            ctk.CTkLabel(row, text=labels_ru[name], width=120, anchor='w',
                         font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                         text_color=PALETTE['text_secondary']).pack(side='left')
            entry = ctk.CTkEntry(row, textvariable=self.box[name], height=28,
                                 fg_color=PALETTE['bg_input'], border_color=PALETTE['border'],
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=11))
            entry.pack(side='left', fill='x', expand=True)

        ctk.CTkLabel(tab_coords,
                     text='Совет: вы можете растянуть область мышкой на интерактивной карте в центре, удерживая ЛКМ в режиме «Выделение рамкой».',
                     wraplength=340, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(10, 0))

        # TAB 4: MY MAPS (УДАЛЕНИЕ И УПРАВЛЕНИЕ КАРТАМИ)
        maps_top = ctk.CTkFrame(tab_maps, fg_color="transparent")
        maps_top.pack(fill='x', pady=(4, 4))

        ctk.CTkLabel(maps_top, text='Установленные карты в BeamNG:',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(side='left')

        self.btn_maps_refresh = ctk.CTkButton(maps_top, text='🔄', width=32, height=26,
                                              fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                              text_color=PALETTE['text_primary'],
                                              font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                              corner_radius=8,
                                              command=self.refresh_installed_maps)
        self.btn_maps_refresh.pack(side='right', padx=(4, 0))

        self.btn_open_mods = ctk.CTkButton(maps_top, text='📁 Папка mods', height=26,
                                           fg_color=PALETTE['btn_default'], hover_color=PALETTE['btn_default_hover'],
                                           text_color=PALETTE['text_primary'],
                                           font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                           corner_radius=8,
                                           command=self.open_mods_folder)
        self.btn_open_mods.pack(side='right')

        ctk.CTkLabel(tab_maps,
                     text='Здесь отображаются готовые уровни и паки из папки mods. Вы можете быстро удалить ненужные карты одной кнопкой.',
                     wraplength=340, justify='left',
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_dim']).pack(anchor='w', pady=(0, 6))

        self.maps_scroll = ctk.CTkScrollableFrame(tab_maps, fg_color="transparent")
        self.maps_scroll.pack(fill='both', expand=True)

        # Controls list for busy state toggling
        self.controls = [self.left_panel, subbar, prod_card, self.tabs]

        # Initial mode selection visual state
        self.select_mode('ready')

        # Load installed maps into tab
        self.refresh_installed_maps()
        self.update_bookmarks_ui()

    def _bind_card(self, widget, mode):
        widget.bind("<Button-1>", lambda _e: self.select_mode(mode))
        for child in widget.winfo_children():
            self._bind_card(child, mode)

    def select_mode(self, mode):
        if self.running:
            return
        if mode in ('ready', 'standalone'):
            self.build_mode.set('standalone')
            self.card_ready.configure(fg_color=PALETTE['card_selected'], border_color=PALETTE['border_highlight'], border_width=2)
            self.lbl_card_ready_ind.configure(text='● ВЫБРАН РЕЖИМ ГОТОВОЙ КАРТЫ', text_color=PALETTE['border_highlight'],
                                              font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"))
            self.card_planet.configure(fg_color=PALETTE['bg_card'], border_color=PALETTE['border'], border_width=1)
            self.lbl_card_planet_ind.configure(text='○ Нажмите, чтобы выбрать этот режим', text_color=PALETTE['text_dim'],
                                               font=ctk.CTkFont(family=FONT_FAMILY, size=10))
            self.build_btn.configure(
                text='🚀 СОБРАТЬ ГОТОВУЮ КАРТУ',
                fg_color=PALETTE['btn_primary'],
                hover_color=PALETTE['btn_primary_hover'],
                text_color=PALETTE['btn_primary_text']
            )
        else:
            self.build_mode.set('planet')
            self.card_ready.configure(fg_color=PALETTE['bg_card'], border_color=PALETTE['border'], border_width=1)
            self.lbl_card_ready_ind.configure(text='○ Нажмите, чтобы выбрать этот режим', text_color=PALETTE['text_dim'],
                                              font=ctk.CTkFont(family=FONT_FAMILY, size=10))
            self.card_planet.configure(fg_color=PALETTE['card_selected'], border_color=PALETTE['border_highlight'], border_width=2)
            self.lbl_card_planet_ind.configure(text='● ВЫБРАН РЕЖИМ ПАКА ДЛЯ ПЛАНЕТЫ', text_color=PALETTE['border_highlight'],
                                               font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"))
            self.build_btn.configure(
                text='🌍 СОБРАТЬ ПАК ДЛЯ ПЛАНЕТЫ',
                fg_color=PALETTE['btn_primary'],
                hover_color=PALETTE['btn_primary_hover'],
                text_color=PALETTE['btn_primary_text']
            )
        self.update_estimate()

    def on_city_selected(self, city_name):
        self.map_title.set(city_name)
        self.use_box.set(True)
        self.options_changed()

    def format_country_name(self, country_id):
        if country_id in COUNTRY_TRANSLATIONS:
            return COUNTRY_TRANSLATIONS[country_id]
        if hasattr(self, 'by_id') and country_id in self.by_id:
            return self.by_id[country_id]['name']
        return country_id.replace('-', ' ').title()

    def on_continent_changed(self, _val=None):
        selected_cont_label = self.continent_var.get()
        cont_id = CONTINENT_MAP.get(selected_cont_label)
        
        if not hasattr(self, 'places') or not self.places:
            return
        
        countries = set()
        for p in self.places:
            p_cont = get_extract_continent(p, self.by_id)
            if cont_id is None or p_cont == cont_id:
                c_id = get_extract_country(p, self.by_id)
                if c_id:
                    countries.add(c_id)
        
        sorted_countries = sorted(countries, key=lambda c: self.format_country_name(c).casefold())
        country_display = ['Все страны'] + [f"{self.format_country_name(c)} ({c})" for c in sorted_countries]
        
        self.country_menu.configure(values=country_display)
        self.country_var.set('Все страны')
        self.refill()

    def on_country_changed(self, _val=None):
        self.refill()

    def open_mods_folder(self):
        mods = self.mods.get()
        if mods and os.path.exists(mods):
            target = Path(mods) / 'mods' if (Path(mods) / 'mods').is_dir() else Path(mods)
            try:
                os.startfile(str(target))
            except Exception as exc:
                self.say(f'Не удалось открыть папку: {exc}')
        else:
            messagebox.showinfo('AroundWorldNG', f'Папка mods не найдена: {mods}')

    def refresh_installed_maps(self):
        if not hasattr(self, 'maps_scroll'):
            return
        for w in getattr(self, 'map_item_widgets', []):
            try:
                w.destroy()
            except Exception:
                pass
        self.map_item_widgets = []
        
        mods = self.mods.get()
        if not mods or not os.path.isdir(mods):
            lbl = ctk.CTkLabel(self.maps_scroll, text='Папка mods BeamNG.drive не найдена.',
                              font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                              text_color=PALETTE['text_dim'])
            lbl.pack(anchor='w', padx=10, pady=10)
            self.map_item_widgets.append(lbl)
            return
        
        items = []
        mods_path = Path(mods)
        search_dirs = [mods_path / 'mods', mods_path] if (mods_path / 'mods').is_dir() else [mods_path]
        seen_files = set()
        try:
            for sdir in search_dirs:
                if not sdir.is_dir():
                    continue
                for zip_file in sdir.glob('*.zip'):
                    if zip_file.name in seen_files:
                        continue
                    seen_files.add(zip_file.name)
                    name = zip_file.name
                    lower = name.lower()
                    if lower in {'aroundworldng_planet.zip', 'earthng_planet.zip', 'aroundworldng_scenery.zip', 'earthng_scenery.zip'}:
                        continue
                    
                    is_standalone = lower.startswith('awng_')
                    is_planet_pack = lower.startswith('aroundworldng_') or lower.startswith('earthng_')
                    
                    if not (is_standalone or is_planet_pack):
                        continue
                    
                    title = None
                    size_mb = os.path.getsize(zip_file) / (1024 * 1024)
                    mtime_str = datetime.datetime.fromtimestamp(os.path.getmtime(zip_file)).strftime('%d.%m.%Y %H:%M')
                    
                    if is_standalone:
                        map_type = "Автономный уровень (Готовая карта)"
                        try:
                            import zipfile
                            with zipfile.ZipFile(zip_file, 'r') as zf:
                                for zname in zf.namelist():
                                    if zname.endswith('info.json') and 'levels/' in zname:
                                        info_data = json.loads(zf.read(zname).decode('utf-8'))
                                        title = info_data.get('title')
                                        break
                        except Exception:
                            pass
                        if not title:
                            title = zip_file.stem.replace('awng_', '').replace('_', ' ').title()
                        items.append({
                            'path': zip_file,
                            'title': title,
                            'filename': name,
                            'type': map_type,
                            'size_mb': size_mb,
                            'mtime': mtime_str,
                            'icon': '🏁'
                        })
                    elif is_planet_pack:
                        map_type = "Пак для Планеты (AroundWorldNG)"
                        clean_name = zip_file.stem.replace('aroundworldng_', '').replace('earthng_', '')
                        title = self.format_country_name(clean_name)
                        items.append({
                            'path': zip_file,
                            'title': title,
                            'filename': name,
                            'type': map_type,
                            'size_mb': size_mb,
                            'mtime': mtime_str,
                            'icon': '🌍'
                        })
        except Exception as exc:
            self.say(f'Ошибка сканирования папки mods: {exc}')
        
        if not items:
            empty_box = ctk.CTkFrame(self.maps_scroll, fg_color="transparent")
            empty_box.pack(fill='both', expand=True, padx=10, pady=20)
            ctk.CTkLabel(empty_box, text='📭 Созданные карты не найдены в папке mods.\nСгенерируйте первую готовую карту выше!',
                         justify='center', font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                         text_color=PALETTE['text_dim']).pack(anchor='center')
            self.map_item_widgets.append(empty_box)
            return
        
        items.sort(key=lambda x: os.path.getmtime(x['path']), reverse=True)
        for item in items:
            self._create_map_item_card(item)

    def _create_map_item_card(self, item):
        card = ctk.CTkFrame(self.maps_scroll, fg_color=PALETTE['bg_input'],
                            border_width=1, border_color=PALETTE['border'], corner_radius=10)
        card.pack(fill='x', padx=2, pady=3)
        self.map_item_widgets.append(card)
        
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill='x', padx=8, pady=6)
        
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side='left', fill='both', expand=True)
        
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor='w')
        
        ctk.CTkLabel(title_row, text=f"{item['icon']}  {item['title']}",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                     text_color=PALETTE['text_primary']).pack(side='left')
        
        details = f"{item['filename']}  •  {item['size_mb']:.1f} МБ  •  {item['mtime']}  •  {item['type']}"
        ctk.CTkLabel(left, text=details,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                     text_color=PALETTE['text_secondary']).pack(anchor='w', pady=(2, 0))
        
        btn_del = ctk.CTkButton(inner, text='🗑️ Удалить', width=75, height=28,
                                fg_color=PALETTE['btn_danger'],
                                hover_color=PALETTE['btn_danger_hover'],
                                text_color=PALETTE['btn_danger_text'],
                                font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                                corner_radius=8,
                                command=lambda p=item['path'], t=item['title']: self.delete_map(p, t))
        btn_del.pack(side='right', padx=(6, 0))

    def delete_map(self, path, title):
        if self.running:
            messagebox.showwarning('AroundWorldNG', 'Нельзя удалять карты во время текущей генерации.')
            return
        
        size_mb = os.path.getsize(path) / (1024 * 1024) if path.is_file() else 0
        confirm = messagebox.askyesno(
            'Удаление карты',
            f'Вы действительно хотите удалить эту карту?\n\n'
            f'Название: «{title}»\n'
            f'Файл: {path.name} ({size_mb:.1f} МБ)\n\n'
            f'Файл будет удален из папки mods BeamNG.drive.'
        )
        if not confirm:
            return
        
        try:
            if path.is_file():
                os.remove(path)
                self.say(f'Карта «{title}» ({path.name}) успешно удалена.')
                self.refresh_installed_maps()
            else:
                self.say(f'Файл {path.name} не найден.')
                self.refresh_installed_maps()
        except Exception as exc:
            messagebox.showerror('Ошибка удаления', f'Не удалось удалить файл:\n{exc}')


    def apply_map_scale(self, km_size):
        if self.running:
            return
        import math
        try:
            curr_box = self.chosen_box()
        except ValueError:
            curr_box = None
            
        if curr_box and self.use_box.get():
            c_lon = (curr_box[0] + curr_box[2]) / 2.0
            c_lat = (curr_box[1] + curr_box[3]) / 2.0
        else:
            c_lon, c_lat = unproject(*self.map.center)
            
        d_lat = (km_size / 2.0) / 111.139
        d_lon = (km_size / 2.0) / (111.139 * max(0.1, math.cos(math.radians(c_lat))))
        w = round(c_lon - d_lon, 6)
        s = round(c_lat - d_lat, 6)
        e = round(c_lon + d_lon, 6)
        n = round(c_lat + d_lat, 6)
        
        self.freeze = True
        self.box['w'].set(f'{w:.6f}')
        self.box['s'].set(f'{s:.6f}')
        self.box['e'].set(f'{e:.6f}')
        self.box['n'].set(f'{n:.6f}')
        self.use_box.set(True)
        self.freeze = False
        
        self.map.selection = [w, s, e, n]
        self.map.schedule()
        self.resolve_source_for_box([w, s, e, n])
        self.options_changed()
        self.say(f'📐 Задан размер карты: {km_size:.1f} × {km_size:.1f} км (~{km_size*km_size:.1f} км²)')

    def center_box_on_view(self):
        if self.running:
            return
        import math
        try:
            box = self.chosen_box()
        except ValueError:
            box = None
            
        c_lon, c_lat = unproject(*self.map.center)
        if box and self.use_box.get():
            half_w = (box[2] - box[0]) / 2.0
            half_h = (box[3] - box[1]) / 2.0
            w = round(c_lon - half_w, 6)
            s = round(c_lat - half_h, 6)
            e = round(c_lon + half_w, 6)
            n = round(c_lat + half_h, 6)
        else:
            d_lat = 1.5 / 111.139
            d_lon = 1.5 / (111.139 * max(0.1, math.cos(math.radians(c_lat))))
            w = round(c_lon - d_lon, 6)
            s = round(c_lat - d_lat, 6)
            e = round(c_lon + d_lon, 6)
            n = round(c_lat + d_lat, 6)
            
        self.freeze = True
        self.box['w'].set(f'{w:.6f}')
        self.box['s'].set(f'{s:.6f}')
        self.box['e'].set(f'{e:.6f}')
        self.box['n'].set(f'{n:.6f}')
        self.use_box.set(True)
        self.freeze = False
        
        self.map.selection = [w, s, e, n]
        self.map.schedule()
        self.resolve_source_for_box([w, s, e, n])
        self.options_changed()
        self.say('🎯 Рамка отцентрирована по текущему виду карты.')

    def add_bookmark(self):
        if self.running:
            return
        title = self.map_title.get().strip() or 'Моя локация'
        try:
            box = self.chosen_box()
        except ValueError:
            box = None
        if not box:
            self.say('Сначала выделите область на карте для сохранения в закладки.')
            return
        w, s, e, n = box
        place_id = self.place['id'] if self.place else 'russia'
        bookmarks = self.settings.get('bookmarks', [])
        bookmarks = [b for b in bookmarks if b.get('title') != title]
        bookmarks.insert(0, {
            'title': title,
            'box': [round(w, 5), round(s, 5), round(e, 5), round(n, 5)],
            'place_id': place_id
        })
        self.settings['bookmarks'] = bookmarks[:30]
        save_settings(self.mods.get(), self.settings['bookmarks'])
        self.update_bookmarks_ui()
        self.say(f'⭐ Локация «{title}» сохранена в закладки!')

    def update_bookmarks_ui(self):
        bookmarks = self.settings.get('bookmarks', [])
        if not hasattr(self, 'bookmark_menu'):
            return
        if bookmarks:
            values = ['📂 Мои закладки:'] + [f"⭐ {b['title']}" for b in bookmarks]
            self.bookmark_menu.configure(values=values)
            self.bookmark_var.set(f"⭐ Мои закладки ({len(bookmarks)})")
        else:
            self.bookmark_menu.configure(values=['Нет сохраненных закладок'])
            self.bookmark_var.set('⭐ Мои закладки (0)')

    def on_bookmark_selected(self, val):
        if not val or val.startswith('📂') or 'Нет сохраненных' in val:
            return
        clean_title = val.replace('⭐', '').strip()
        bookmarks = self.settings.get('bookmarks', [])
        for b in bookmarks:
            if b.get('title') == clean_title:
                w, s, e, n = b['box']
                self.map_title.set(clean_title)
                self.freeze = True
                self.box['w'].set(f'{w:.6f}')
                self.box['s'].set(f'{s:.6f}')
                self.box['e'].set(f'{e:.6f}')
                self.box['n'].set(f'{n:.6f}')
                self.use_box.set(True)
                self.freeze = False
                
                place_id = b.get('place_id', 'russia')
                target_place = self.by_id.get(place_id)
                if target_place:
                    self.select_place(target_place, fit=False, preserve_look=True, update_box=False)
                
                self.map.center_on_coords((w + e) / 2, (s + n) / 2, zoom=13, box=[w, s, e, n])
                self.options_changed()
                self.say(f'Загружена закладка: «{clean_title}»')
                break

    def select_city_item(self, item):
        city_title = item['display_name'].split('(')[0].strip()
        self.map_title.set(city_title)
        w, s, e, n = item['box']
        self.freeze = True
        self.box['w'].set(f'{w:.6f}')
        self.box['s'].set(f'{s:.6f}')
        self.box['e'].set(f'{e:.6f}')
        self.box['n'].set(f'{n:.6f}')
        self.use_box.set(True)
        self.freeze = False

        found_place = None
        city_needle = item['name'].casefold()
        for p in self.places:
            if city_needle in p['id'].casefold() or city_needle in p['name'].casefold():
                found_place = p
                break
        if not found_place:
            if 19.0 <= item['lon'] <= 180.0 and 41.0 <= item['lat'] <= 82.0:
                found_place = self.by_id.get('russia')
        if found_place:
            self.select_place(found_place, fit=False, preserve_look=False, update_box=False)

        self.map.center_on_coords(item['lon'], item['lat'], zoom=13, box=item['box'])
        self.options_changed()
        self.say(f'Выбран город: {item["display_name"]} [BBox: ~3.2×3.2 км]')

    def apply_preset(self, lon_w, lat_s, lon_e, lat_n, place_id, title=None):
        if self.running:
            return
        self.current_preset_title = title
        if title:
            self.map_title.set(title)
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
        self.lines.put(str(text))

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
            if count > 2000:
                self.log.delete('1.0', f'{count-2000}.0')
            self.log.see('end')
            self.log.configure(state='disabled')
            self.status.set(messages[-1])

        if self.running and self.started is not None:
            elapsed = time.monotonic() - self.started
            label = f'Прошло времени: {timing.duration(elapsed)}'
            if self.active_stage:
                label = f'{self.active_stage} · {label}'
                index = timing.STAGES.index(self.active_stage) if self.active_stage in timing.STAGES else None
                if index is not None:
                    label = f'{index+1}/{len(timing.STAGES)} · {label}'
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
        self.map.selection = box
        self.resolve_source_for_box(box)
        self.options_changed()

    def resolve_source_for_box(self, box):
        if self.running or not getattr(self, 'boundaries', None):
            return
        from shapely.geometry import box as make_rect
        box_rect = make_rect(*box)
        
        # 1. If currently selected place already covers, contains or intersects the box, keep it! Never jump!
        if self.place and self.place['id'] in self.boundaries:
            curr_geom = self.boundaries[self.place['id']]
            if curr_geom and (curr_geom.covers(box_rect) or curr_geom.contains(box_rect) or curr_geom.intersects(box_rect)):
                self.status.set(f'Регион: {self.format_country_name(self.place["id"])}')
                return

        # 2. Find the smallest covering region and update source place WITHOUT touching user box or view
        key = places.smallest_covering(self.boundaries, box, self.by_id)
        if key and key in self.by_id:
            self.select_place(self.by_id[key], fit=False, preserve_look=True, update_box=False)
            self.status.set(f'Источник данных: {self.format_country_name(key)}')

    def clear_box(self):
        if not self.running:
            if self.place and 'box' in self.place:
                w, s, e, n = self.place['box']
                self.freeze = True
                self.box['w'].set(f'{w:.6f}')
                self.box['s'].set(f'{s:.6f}')
                self.box['e'].set(f'{e:.6f}')
                self.box['n'].set(f'{n:.6f}')
                self.use_box.set(True)
                self.freeze = False
                self.map.selection = [w, s, e, n]
                self.map.fit(self.place['box'])
            else:
                self.use_box.set(False)
                self.map.selection = None
                self.map.fit_source()
            self.options_changed()

    def optimize_source(self):
        if self.running:
            return
        try:
            box = self.chosen_box()
        except ValueError:
            return
        if box is None:
            return
        self.resolve_source_for_box(box)

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
        self.refresh_installed_maps()
        self.update_bookmarks_ui()
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
        if getattr(self, 'build_mode', None) and self.build_mode.get() == 'standalone':
            if not self.use_box.get():
                self.estimate_text.set('💡 Выделите область рамкой на карте или выберите шаблон слева.')
            else:
                self.estimate_text.set('⚡ Готовая карта BeamNG: запекание рельефа, дорог и 3D зданий.\n'
                                       'Сборка ~5–20 сек. Загрузка в игре мгновенная!')
            return
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
        self.on_continent_changed()

    def refill(self):
        needle = self.query.get().strip().casefold()
        selected_cont_label = self.continent_var.get()
        cont_id = CONTINENT_MAP.get(selected_cont_label)
        
        selected_ctry_label = self.country_var.get()
        selected_ctry_id = None
        if selected_ctry_label and selected_ctry_label != 'Все страны':
            if '(' in selected_ctry_label and selected_ctry_label.endswith(')'):
                selected_ctry_id = selected_ctry_label.split('(')[-1].rstrip(')')
            else:
                for cid, trans in COUNTRY_TRANSLATIONS.items():
                    if trans == selected_ctry_label:
                        selected_ctry_id = cid
                        break
        
        filtered = []
        for place in self.places:
            p_cont = get_extract_continent(place, self.by_id)
            p_ctry = get_extract_country(place, self.by_id)
            pid = place['id']
            trans_pid = COUNTRY_TRANSLATIONS.get(pid, '')
            trans_ctry = COUNTRY_TRANSLATIONS.get(p_ctry, '')
            parent_name = places.parent_name(place, self.by_id) or ''
            
            matches_needle = True
            if needle:
                matches_needle = (
                    needle in place['name'].casefold()
                    or needle in pid.casefold()
                    or needle in trans_pid.casefold()
                    or needle in trans_ctry.casefold()
                    or needle in parent_name.casefold()
                )
            if not matches_needle:
                continue
            
            if cont_id is not None and not (needle and selected_cont_label == 'Все континенты'):
                if p_cont != cont_id:
                    continue
            
            if selected_ctry_id is not None and not (needle and selected_ctry_label == 'Все страны'):
                if p_ctry != selected_ctry_id:
                    continue
            
            filtered.append(place)
        
        if needle and not filtered:
            for place in self.places:
                p_ctry = get_extract_country(place, self.by_id)
                pid = place['id']
                trans_pid = COUNTRY_TRANSLATIONS.get(pid, '')
                trans_ctry = COUNTRY_TRANSLATIONS.get(p_ctry, '')
                parent_name = places.parent_name(place, self.by_id) or ''
                if (needle in place['name'].casefold()
                    or needle in pid.casefold()
                    or needle in trans_pid.casefold()
                    or needle in trans_ctry.casefold()
                    or needle in parent_name.casefold()):
                    filtered.append(place)
        
        def sort_key(p):
            pid = p['id']
            trans = COUNTRY_TRANSLATIONS.get(pid, p['name'])
            # 0 for specific subjects/regions with box (Saint Petersburg, Moscow, Leningrad Oblast, etc.)
            # 1 for federal districts / subregions
            # 2 for continent/country roots
            priority = 0 if 'box' in p else (2 if pid in CONTINENT_ROOTS or not p.get('parent') else 1)
            return (priority, trans.casefold())

        filtered.sort(key=sort_key)

        # Include matching cities from FALLBACK_CITIES when searching
        city_items = []
        if needle:
            import math
            for row in FALLBACK_CITIES:
                lat, lon = row[0], row[1]
                en_name = str(row[3])
                ru_name = str(row[4]) if len(row) > 4 and row[4] else en_name
                if needle in en_name.casefold() or needle in ru_name.casefold():
                    d_lat = 0.015
                    d_lon = 0.015 / max(0.1, math.cos(math.radians(lat)))
                    box = [round(lon - d_lon, 5), round(lat - d_lat, 5),
                           round(lon + d_lon, 5), round(lat + d_lat, 5)]
                    city_items.append({
                        'kind': 'city',
                        'id': f'city/{en_name.lower().replace(" ", "-")}',
                        'name': en_name,
                        'display_name': ru_name,
                        'lat': lat,
                        'lon': lon,
                        'box': box
                    })

        self.shown = city_items + filtered
        self.list.delete(0, 'end')
        for item in self.shown:
            if item.get('kind') == 'city':
                label = f"🏙️ {item['display_name']} ({item['name']})"
            else:
                place = item
                pid = place['id']
                parent = places.parent_name(place, self.by_id)
                trans_name = COUNTRY_TRANSLATIONS.get(pid)
                
                if pid in CONTINENT_ROOTS or (not parent and pid in COUNTRY_TRANSLATIONS):
                    label = f"🌐 {trans_name or place['name']} (Вся территория)"
                elif trans_name:
                    suffix = f'  —  {parent}' if parent and 'box' not in place else ''
                    label = f"{trans_name}{suffix}"
                else:
                    suffix = f'  —  {parent}' if parent else ''
                    label = f"{place['name']}{suffix}"
            
            self.list.insert('end', label)
            if self.place and item.get('id') == self.place.get('id'):
                self.list.selection_set('end')

    def on_select(self):
        if self.running:
            return
        selection = self.list.curselection()
        if not selection:
            return
        item = self.shown[selection[0]]
        if item.get('kind') == 'city':
            self.select_city_item(item)
        else:
            self.freeze = True
            self.use_box.set(False)
            self.freeze = False
            self.select_place(item)

    def select_place(self, place, fit=True, preserve_look=False, update_box=True):
        self.place = place
        clean_title = COUNTRY_TRANSLATIONS.get(place['id']) or place.get('title') or place['name']
        if '(' in clean_title:
            clean_title = clean_title.split('(')[0].strip()
        if update_box and not getattr(self, 'current_preset_title', None):
            self.map_title.set(clean_title)
        if not preserve_look:
            self.show_look(looks.recommended(place['id'], self.by_id))
        self.map.boundary = self.boundaries.get(place['id'])
        if update_box:
            if 'box' in place:
                w, s, e, n = place['box']
                self.freeze = True
                self.box['w'].set(f'{w:.6f}')
                self.box['s'].set(f'{s:.6f}')
                self.box['e'].set(f'{e:.6f}')
                self.box['n'].set(f'{n:.6f}')
                self.use_box.set(True)
                self.freeze = False
                self.map.selection = [w, s, e, n]
                if fit:
                    self.map.fit(place['box'])
            else:
                self.use_box.set(False)
                self.map.selection = None
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
            if self.place and 'box' in self.place:
                return list(self.place['box'])
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
        self.refresh_installed_maps()
        self.update_bookmarks_ui()

    def download_ready(self):
        if self.place is None:
            return
        info = getattr(self, '_ready', None) or {}
        slug_id = places.slug(self.place['id'])
        mods = self.mods.get()

        def target():
            if self.cancel.is_set():
                raise InterruptedError('install stopped')
            if info.get('state') == 'local':
                path = country_fetch.install_zip(info['path'], mods, slug_id, cancel=self.cancel)
            elif info.get('state') == 'url':
                dest = ROOT / 'out' / 'country-setup' / f'aroundworldng_{slug_id}.zip'
                country_fetch.download(info['url'], dest, self.say, self.cancel)
                path = country_fetch.install_zip(dest, mods, slug_id, cancel=self.cancel)
            else:
                self.say('Готовый пак не найден')
                return
            self.say(f'Пак установлен в: {path}')
        self.run(target)

    def build(self):
        if self.running:
            return
        if self.place is None:
            messagebox.showinfo('AroundWorldNG', 'Сначала выберите регион из списка.')
            return

        mode = self.build_mode.get()

        if mode == 'standalone':
            try:
                box = self.chosen_box()
            except ValueError as exc:
                messagebox.showerror('AroundWorldNG', str(exc))
                return

            if not box:
                messagebox.showinfo(
                    'AroundWorldNG',
                    'Для создания готовой карты (автономного уровня) требуется выбрать область на карте.\n\n'
                    'Поставьте галочку «Ограничить выбранным прямоугольником» и выделите рамку на карте, '
                    'либо нажмите один из быстрых пресетов слева (Кудрово, Мурино, Москва-Сити).'
                )
                return
        else:
            try:
                box = self.chosen_box()
                boundary = self.boundaries.get(self.place['id'])
                if box and boundary is not None:
                    from shapely.geometry import box as rectangle
                    if not boundary.covers(rectangle(*box)):
                        raise ValueError('Выделенная область выходит за границы выбранного источника. '
                                         'Используйте кнопку «Оптимальный источник» или выделите область внутри региона.')
            except ValueError as exc:
                messagebox.showerror('AroundWorldNG', str(exc))
                return

        # Prompt the user for a clean map name EVERY TIME:
        suggested = self.map_title.get().strip() or getattr(self, 'current_preset_title', None) or self.place['name']
        dialog = MapNameDialog(self.root, default_name=suggested)
        chosen_title = dialog.get_name()
        if not chosen_title:
            self.say('Сборка отменена: название карты не указано.')
            return

        self.map_title.set(chosen_title)
        title = chosen_title

        place, mods = self.place, self.mods.get()
        look = self.chosen_look()
        include = self.chosen_include()

        if mode == 'standalone':
            self.say(f"Генерация готовой карты: «{title}» (автономный уровень BeamNG).")

            def target():
                import export_standalone
                export_standalone.export_standalone_level(
                    place, mods, box,
                    look=look, include=include, title=title,
                    emit=self.say, cancel=self.cancel, progress=self.stage_progress
                )

            self.run(target)
            return

        # Planet streaming pack mode:
        if box and self.boundaries.get(place['id']) is None:
            self.say('Границы региона неизвестны: проверка охвата пропущена. Будут экспортированы данные внутри рамки.')
        key, estimate, _reason, _cached = self.estimate_inputs()
        block = looks.BLOCK_BY_ID.get(look['block'], looks.BLOCK_BY_ID['general'])['title']

        def target():
            import export_standalone
            clean_slug = export_standalone.slugify(title)
            self.say(f"Генерация пака для Планеты: «{title}» (id: {clean_slug}), стиль «{block}».")
            country_fetch.build_place(place, mods, look=look, include=include, box=box,
                                      title=title, slug_id=clean_slug,
                                      by_id=self.by_id, emit=self.say, cancel=self.cancel, progress=self.stage_progress)

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
