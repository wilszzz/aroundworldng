"""Tk region picker. Reuses the planet's offline Natural Earth map; OpenStreetMap street
tiles are fetched only while the user turns street detail on."""
from collections import OrderedDict
import io
import json
import math
from functools import lru_cache
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import urllib.request
import zipfile

from PIL import Image, ImageTk

import paths
import tls

MAX_LAT = 85.05112878
MAX_ZOOM = 14          # offline map, its last level enlarged
ONLINE_MAX_ZOOM = 17   # street names and blocks are legible here
def get_rounded_font():
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for candidate in ('Rubik', 'Comfortaa', 'Nunito', 'Segoe UI Variable Text', 'Century Gothic', 'Segoe UI'):
            if candidate in available:
                return candidate
    except Exception:
        pass
    return 'Rubik'

FONT_FAMILY = get_rounded_font()


def rgb(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert('RGB')


def project(lon, lat):
    lat = math.radians(max(-MAX_LAT, min(MAX_LAT, lat)))
    return (lon + 180) / 360, (1 - math.asinh(math.tan(lat)) / math.pi) / 2


def unproject(x, y):
    return max(-180, min(180, x * 360 - 180)), math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * max(0, min(1, y))))))


FALLBACK_CITIES = [
    [59.9343, 30.3351, 1, 'Saint Petersburg (SPb)', 'Санкт-Петербург (СПб, Питер)', 1, 5600000],
    [55.7558, 37.6173, 1, 'Moscow (Msk)', 'Москва (МСК)', 1, 13100000],
    [59.9070, 30.5050, 2, 'Kudrovo', 'Кудрово (СПб)', 0, 70000],
    [60.0450, 30.4450, 2, 'Murino', 'Мурино (СПб)', 0, 100000],
    [55.0084, 82.9357, 2, 'Novosibirsk', 'Новосибирск', 0, 1630000],
    [56.8389, 60.6057, 2, 'Yekaterinburg', 'Екатеринбург', 0, 1540000],
    [55.8304, 49.0661, 2, 'Kazan', 'Казань', 0, 1310000],
    [56.2965, 43.9361, 2, 'Nizhny Novgorod', 'Нижний Новгород', 0, 1220000],
    [53.2415, 50.2212, 2, 'Samara', 'Самара', 0, 1170000],
    [54.9885, 73.3242, 2, 'Omsk', 'Омск', 0, 1110000],
    [47.2357, 39.7015, 2, 'Rostov-on-Don', 'Ростов-на-Дону', 0, 1140000],
    [54.7388, 55.9721, 2, 'Ufa', 'Уфа', 0, 1140000],
    [56.0153, 92.8932, 2, 'Krasnoyarsk', 'Красноярск', 0, 1190000],
    [51.6608, 39.2003, 2, 'Voronezh', 'Воронеж', 0, 1050000],
    [58.0105, 56.2502, 2, 'Perm', 'Пермь', 0, 1030000],
    [48.7080, 44.5133, 2, 'Volgograd', 'Волгоград', 0, 1020000],
    [45.0355, 38.9753, 2, 'Krasnodar', 'Краснодар', 0, 1120000],
    [51.5406, 46.0086, 2, 'Saratov', 'Саратов', 0, 900000],
    [57.1522, 65.5272, 2, 'Tyumen', 'Тюмень', 0, 850000],
    [53.5303, 49.3461, 2, 'Tolyatti', 'Тольятти', 0, 680000],
    [54.7104, 20.4522, 2, 'Kaliningrad', 'Калининград', 0, 490000],
    [43.6028, 39.7342, 2, 'Sochi', 'Сочи', 0, 460000],
    [53.9045, 27.5615, 1, 'Minsk', 'Минск', 1, 2000000],
    [50.4501, 30.5234, 1, 'Kyiv', 'Киев', 1, 2900000],
    [43.2220, 76.8512, 1, 'Almaty', 'Алматы', 0, 2100000],
    [51.1694, 71.4491, 1, 'Astana', 'Астана', 1, 1350000],
    [52.5200, 13.4050, 1, 'Berlin', 'Берлин', 1, 3700000],
    [48.8566, 2.3522, 1, 'Paris', 'Париж', 1, 2160000],
    [51.5074, -0.1278, 1, 'London', 'Лондон', 1, 8980000],
    [41.9028, 12.4964, 1, 'Rome', 'Рим', 1, 2870000],
    [40.4168, -3.7038, 1, 'Madrid', 'Мадрид', 1, 3220000],
    [40.7128, -74.0060, 1, 'New York City', 'Нью-Йорк', 0, 8330000],
    [34.0522, -118.2437, 1, 'Los Angeles', 'Лос-Анджелес', 0, 3900000],
    [37.7749, -122.4194, 1, 'San Francisco', 'Сан-Франциско', 0, 870000],
    [35.6762, 139.6503, 1, 'Tokyo', 'Токио', 1, 14000000],
]


class MapData:
    def __init__(self, root, mods):
        self.directory = Path(root) / 'out' / 'basemap' / '3'
        self.archive = None
        self.index = {}
        self.labels = []
        coast_file = Path(root) / 'mod/aroundworldng/planet/coastline.json'
        if not coast_file.exists():
            coast_file = Path(root) / 'mod/earthng/planet/coastline.json'
        self.coast = json.loads(coast_file.read_text()) if coast_file.exists() else []
        try:
            if not (self.directory / 'index.json').exists():
                candidates = [
                    Path(mods) / 'aroundworldng_planet.zip',
                    Path(mods) / 'earthng_planet.zip',
                    Path(root) / 'out' / 'mod' / 'aroundworldng_planet.zip',
                    Path(root) / 'out' / 'aroundworldng_planet.zip',
                    Path(root) / 'mod' / 'aroundworldng_planet.zip',
                    Path(mods) / 'mods' / 'aroundworldng_planet.zip',
                    Path(mods) / 'mods' / 'earthng_planet.zip',
                ]
                for cand in candidates:
                    if cand.exists():
                        self.archive = zipfile.ZipFile(cand)
                        break
            if self.archive or (self.directory / 'index.json').exists():
                try:
                    self.index = json.loads(self.read('index.json'))
                except Exception:
                    self.index = {}
                try:
                    self.labels = json.loads(self.read('labels.json')).get('places', [])
                except Exception:
                    self.labels = []
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self.close()

        # Merge fallback cities if labels are few or empty
        existing_names = {str(r[3]).casefold() for r in self.labels}
        for fb in FALLBACK_CITIES:
            if str(fb[3]).casefold() not in existing_names:
                self.labels.append(fb)

    def read(self, name):
        if self.archive:
            for prefix in ('aroundworldng/planet/basemap/', 'earthng/planet/basemap/'):
                try:
                    return self.archive.read(prefix + name)
                except KeyError:
                    pass
            raise KeyError(name)
        return (self.directory / name).read_bytes()

    @lru_cache(maxsize=96)
    def tile(self, key):
        name = self.index.get('tiles', {}).get(key)
        if name:
            try:
                return rgb(self.read(f't/{name}.png'))
            except (OSError, KeyError):
                pass
        return None

    def close(self):
        self.tile.cache_clear()
        if self.archive:
            self.archive.close()
            self.archive = None
        self.index = {}


class OnlineTiles:
    """OpenStreetMap raster tiles for street detail, kept to the tile usage policy
    (https://operations.osmfoundation.org/policies/tiles/): an identifying User-Agent, two
    connections, only tiles still on screen (no prefetch), a week-long disk cache and the
    attribution drawn on the map. Workers only download; the Tk thread owns all state."""
    URL = 'https://tile.openstreetmap.org/{}/{}/{}.png'
    AGENT = 'AroundWorldNG-MapStudio/1.0 (+https://github.com/aroundworldng)'
    MAX_AGE = 7 * 86400
    RETRY = 60
    KEEP = 160   # decoded tiles in memory, ~31 MB

    def __init__(self, cache, workers=2):
        self.cache = Path(cache)
        self.images = OrderedDict()
        self.expires = {}
        self.queued = set()
        self.failed = OrderedDict()
        self.visible = set()
        self.error = None
        self.todo = queue.LifoQueue()   # the latest view first
        self.arrived = queue.SimpleQueue()
        self.closed = threading.Event()
        self.workers = []
        for _ in range(workers):
            worker = threading.Thread(target=self.work, daemon=True)
            self.workers.append(worker)
            worker.start()

    def path(self, key):
        z, x, y = key
        return self.cache / str(z) / str(x) / f'{y}.png'

    def get(self, key):
        """The tile, or a stale cached copy or None while it downloads (queued once)."""
        image = self.images.get(key)
        fresh = False
        if image is not None:
            self.images.move_to_end(key)
            fresh = time.time() < self.expires.get(key, 0)
        else:
            path = self.path(key)
            try:
                expires = path.stat().st_mtime + self.MAX_AGE
                image = self.keep(key, rgb(path.read_bytes()), expires)
                fresh = time.time() < expires
            except (OSError, ValueError):
                pass
        if not self.closed.is_set() and not fresh and key not in self.queued and time.time() - self.failed.get(key, 0) > self.RETRY:
            self.queued.add(key)
            self.todo.put(key)
        return image

    def keep(self, key, image, expires=None):
        self.images[key] = image
        self.expires[key] = time.time() + self.MAX_AGE if expires is None else expires
        self.images.move_to_end(key)
        while len(self.images) > self.KEEP:
            old, _ = self.images.popitem(last=False)
            self.expires.pop(old, None)
        return image

    def work(self):
        while True:
            key = self.todo.get()
            if key is None or self.closed.is_set():
                return
            self.fetch(key)

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        self.visible = set()
        for _ in self.workers:
            self.todo.put(None)

    def fetch(self, key):
        # A tile panned off screen before its turn is dropped; it queues again if seen again.
        if key not in self.visible:
            self.arrived.put((key, None, None))
            return
        try:
            self.arrived.put((key, self.download(key), None))
        except (OSError, ValueError) as exc:
            self.arrived.put((key, None, exc))

    def download(self, key):
        request = urllib.request.Request(self.URL.format(*key), headers={'User-Agent': self.AGENT})
        with urllib.request.urlopen(request, timeout=20, context=tls.context()) as response:
            data = response.read()
        image = rgb(data)   # an error page is never cached as a tile
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix('.part')
        part.write_bytes(data)
        part.replace(path)
        return image

    def drain(self):
        """Take finished downloads; True when a tile arrived and the map should redraw."""
        arrived = False
        while True:
            try:
                key, image, error = self.arrived.get_nowait()
            except queue.Empty:
                return arrived
            self.queued.discard(key)
            if error is not None:
                self.failed[key], self.error = time.time(), str(error)
                self.failed.move_to_end(key)
                while len(self.failed) > self.KEEP:
                    self.failed.popitem(last=False)
            elif image is not None:
                self.keep(key, image)
                self.failed.pop(key, None)
                self.error, arrived = None, True


class RegionMap(ctk.CTkFrame):
    def __init__(self, parent, on_box, on_city_select=None):
        super().__init__(parent, fg_color="transparent")
        self.on_box = on_box
        self.on_city_select = on_city_select
        self.data = None
        self.boundary = None
        self.selection = None
        self.center = project(30.5, 50.45)
        self.zoom = 4
        self.pending = None
        self.polling = None
        self.online = None
        self.enabled = True
        self.drag = None
        self.photos = []

        # Styled Toolbar matching #292929 and #C88E9b with rounded shapes
        bar = ctk.CTkFrame(self, fg_color="#292929", corner_radius=10, border_width=1, border_color="#3d3a3d")
        bar.pack(fill='x', pady=(0, 5))
        bar_inner = ctk.CTkFrame(bar, fg_color="transparent")
        bar_inner.pack(fill='x', padx=6, pady=4)

        self.mode = tk.StringVar(value='pan')
        self.mode_seg = ctk.CTkSegmentedButton(
            bar_inner,
            values=['✋ Перемещение', '⬚ Выделение рамкой'],
            selected_color='#C88E9b',
            selected_hover_color='#d99fad',
            unselected_color='#1f1f22',
            unselected_hover_color='#2d2d31',
            text_color='#ffffff',
            corner_radius=8,
            height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight='bold'),
            command=self._on_mode_change
        )
        self.mode_seg.set('✋ Перемещение')
        self.mode_seg.pack(side='left', padx=(0, 6))

        self.btn_zoom_in = ctk.CTkButton(
            bar_inner, text='➕', width=32, height=28,
            fg_color='#36363a', hover_color='#45454b', text_color='#ffffff',
            corner_radius=8, font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight='bold'),
            command=lambda: self.change_zoom(1)
        )
        self.btn_zoom_in.pack(side='left', padx=(0, 3))

        self.btn_zoom_out = ctk.CTkButton(
            bar_inner, text='➖', width=32, height=28,
            fg_color='#36363a', hover_color='#45454b', text_color='#ffffff',
            corner_radius=8, font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight='bold'),
            command=lambda: self.change_zoom(-1)
        )
        self.btn_zoom_out.pack(side='left', padx=(0, 6))

        self.btn_fit = ctk.CTkButton(
            bar_inner, text='🎯 Вписать регион', height=28,
            fg_color='#36363a', hover_color='#45454b', text_color='#ffffff',
            corner_radius=8, font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self.fit_source
        )
        self.btn_fit.pack(side='left', padx=(0, 8))

        self.streets = tk.BooleanVar(value=True)
        self.switch_streets = ctk.CTkSwitch(
            bar_inner, text='Улицы (OSM онлайн)',
            variable=self.streets,
            progress_color='#C88E9b',
            button_color='#ffffff',
            button_hover_color='#eeeeee',
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self.toggle_streets
        )
        self.switch_streets.pack(side='left', padx=(0, 4))

        self.canvas = tk.Canvas(self, background='#19191d', highlightthickness=1, highlightbackground='#3d3a3d', height=390)
        self.canvas.pack(fill='both', expand=True, pady=(0, 4))
        self.canvas.bind('<Configure>', lambda _: self.schedule())
        self.canvas.bind('<MouseWheel>', lambda e: self.change_zoom(1 if e.delta > 0 else -1, e.x, e.y))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)

        info_bar = ctk.CTkFrame(self, fg_color="transparent")
        info_bar.pack(fill='x', pady=(0, 2))

        self.hint = tk.StringVar(value='Перемещение: ЛКМ. Рамка области: «Выделение рамкой» + протяните ЛКМ. Масштаб: колесо мыши.')
        self.lbl_hint = ctk.CTkLabel(info_bar, textvariable=self.hint, text_color='#9e9498',
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=10), wraplength=700)
        self.lbl_hint.pack(anchor='w')

        self.credit = tk.StringVar()
        self.lbl_credit = ctk.CTkLabel(info_bar, textvariable=self.credit, text_color='#736b6f',
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=9), wraplength=700)
        self.lbl_credit.pack(anchor='w')

        self.toggle_streets()

    def _on_mode_change(self, val):
        if 'рамкой' in val:
            self.mode.set('select')
        else:
            self.mode.set('pan')

    def center_on_coords(self, lon, lat, zoom=13, box=None):
        self.center = project(lon, lat)
        self.zoom = min(self.max_zoom(), zoom)
        if box is not None:
            self.selection = box
            if self.on_box:
                self.on_box(box)
        self.schedule()

    def toggle_streets(self):
        if self.streets.get():
            if self.online is None:
                self.online = OnlineTiles(paths.OUT / 'osm-tiles')
            self.credit.set('Natural Earth (оффлайн) • детализация улиц © OpenStreetMap (онлайн)')
        else:
            if self.online:
                self.online.visible = set()
            self.credit.set('Natural Earth • оффлайн обзорная карта (без детальных улиц)')
            if self.zoom > MAX_ZOOM:
                self.change_zoom(MAX_ZOOM - self.zoom)
        self.schedule()

    def destroy(self):
        for callback in (self.pending, self.polling):
            if callback is not None:
                self.after_cancel(callback)
        self.pending = self.polling = None
        if self.online:
            self.online.close()
        if self.data:
            self.data.close()
        super().destroy()

    def max_zoom(self):
        return ONLINE_MAX_ZOOM if self.streets.get() else MAX_ZOOM

    def xy(self, lon, lat):
        x, y = project(lon, lat)
        scale = 256 * 2 ** self.zoom
        return ((x - self.center[0]) * scale + self.canvas.winfo_width() / 2,
                (y - self.center[1]) * scale + self.canvas.winfo_height() / 2)

    def geo(self, x, y):
        scale = 256 * 2 ** self.zoom
        return unproject(self.center[0] + (x - self.canvas.winfo_width() / 2) / scale,
                         self.center[1] + (y - self.canvas.winfo_height() / 2) / scale)

    def fit_source(self):
        if self.boundary is not None:
            self.fit(self.boundary.bounds)

    def fit(self, box):
        w, s, e, n = box
        x0, y0 = project(w, n)
        x1, y1 = project(e, s)
        self.center = ((x0 + x1) / 2, (y0 + y1) / 2)
        width, height = max(200, self.canvas.winfo_width() - 40), max(160, self.canvas.winfo_height() - 40)
        self.zoom = max(1, min(self.max_zoom(), math.floor(math.log2(min(width / max(1e-9, x1-x0), height / max(1e-9, y1-y0)) / 256))))
        self.schedule()

    def change_zoom(self, delta, x=None, y=None):
        if x is None:
            x, y = self.canvas.winfo_width()/2, self.canvas.winfo_height()/2
        before = project(*self.geo(x, y))
        self.zoom = max(1, min(self.max_zoom(), self.zoom + delta))
        scale = 256 * 2 ** self.zoom
        self.center = (before[0] - (x-self.canvas.winfo_width()/2)/scale,
                       before[1] - (y-self.canvas.winfo_height()/2)/scale)
        self.schedule()

    def press(self, event):
        if self.enabled:
            self.drag = (event.x, event.y, self.center, self.mode.get())

    def motion(self, event):
        if not self.drag:
            return
        x, y, center, mode = self.drag
        if mode == 'pan':
            scale = 256 * 2 ** self.zoom
            self.center = tuple(max(0, min(1, v)) for v in
                                (center[0]-(event.x-x)/scale, center[1]-(event.y-y)/scale))
            self.schedule()
        else:
            self.canvas.delete('drag')
            self.canvas.create_rectangle(x, y, event.x, event.y, outline='#C88E9b', width=3, tags='drag')

    def release(self, event):
        if not self.drag:
            return
        x, y, _center, mode = self.drag
        self.drag = None
        self.canvas.delete('drag')
        if mode == 'select' and abs(event.x-x) >= 4 and abs(event.y-y) >= 4:
            a, b = self.geo(x, y), self.geo(event.x, event.y)
            box = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
            self.on_box(box)

    def schedule(self):
        if self.pending is None:
            self.pending = self.after(30, self.draw)

    def poll(self):
        self.polling = None
        if self.online.drain():
            self.schedule()   # draw polls again while tiles are still on the way
        elif self.online.queued:
            self.polling = self.after(150, self.poll)
        elif self.online.error:
            self.schedule()   # show why street detail is missing

    def tile_grid(self, z, size, width, height):
        """(x, y, left, top) of the zoom-z tiles, drawn size px wide, that cover the canvas."""
        ox, oy = self.center[0]*2**z*size-width/2, self.center[1]*2**z*size-height/2
        return [(x, y, x*size-ox, y*size-oy)
                for x in range(max(0, math.floor(ox/size)), min(2**z, math.ceil((ox+width)/size)))
                for y in range(max(0, math.floor(oy/size)), min(2**z, math.ceil((oy+height)/size)))]

    def paste(self, tile, left, top, size, width, height):
        # Crop before resizing: zoom 14 must not allocate a 16384² bitmap.
        dx, dy = max(0, left), max(0, top)
        dw, dh = min(width, left+size)-dx, min(height, top+size)-dy
        crop = ((dx-left)*256/size, (dy-top)*256/size,
                (dx+dw-left)*256/size, (dy+dh-top)*256/size)
        rendered = tile.transform((max(1, math.ceil(dw)), max(1, math.ceil(dh))), Image.Transform.EXTENT, crop)
        photo = ImageTk.PhotoImage(rendered)
        self.photos.append(photo)
        self.canvas.create_image(dx, dy, image=photo, anchor='nw')

    def draw(self):
        self.pending = None
        c = self.canvas
        c.delete('all')
        self.photos = []
        width, height = c.winfo_width(), c.winfo_height()
        local = self.data.index['maxZoom'] if self.data and self.data.index else None
        streets = []
        if self.online and self.streets.get() and (local is None or self.zoom > local):
            grid = self.tile_grid(self.zoom, 256, width, height)
            self.online.visible = {(self.zoom, x, y) for x, y, _left, _top in grid}
            streets = [(self.online.get((self.zoom, x, y)), left, top) for x, y, left, top in grid]
        elif self.online:
            self.online.visible = set()
        if streets and all(tile is not None for tile, _left, _top in streets):
            pass   # street tiles cover the whole canvas
        elif local is not None:
            # Enlarge the highest local tile for city-scale selection.
            z = min(self.zoom, local)
            size = 256 * 2 ** (self.zoom-z)
            for x, y, left, top in self.tile_grid(z, size, width, height):
                tile = self.data.tile(f'{z}/{x}/{y}')
                if tile:
                    self.paste(tile, left, top, size, width, height)
        elif self.data:
            for ring in self.data.coast:
                points = [v for lon, lat in ring for v in self.xy(lon, lat)]
                if len(points) >= 6:
                    c.create_polygon(points, fill='#f2efe9', outline='#9aafa6')
        for tile, left, top in streets:
            if tile is not None:
                self.paste(tile, left, top, 256, width, height)
        if streets:
            note = '© OpenStreetMap contributors'
            if self.online.error:
                note = f'Street detail unavailable ({self.online.error}) · {note}'
            c.create_text(width-4, height-4, text=note, anchor='se', fill='#273640', font=(FONT_FAMILY, 8))
            if self.online.queued and self.polling is None:
                self.polling = self.after(150, self.poll)
        if self.data and not streets:   # street tiles carry their own names
            for row in self.data.labels:
                lat, lon, minzoom, label = row[:4]
                if self.zoom < minzoom + 1:
                    continue
                x, y = self.xy(lon, lat)
                if 0 < x < width and 0 < y < height:
                    c.create_oval(x-2, y-2, x+2, y+2, fill='#445461', outline='')
                    c.create_text(x+5, y, text=label, anchor='w', fill='#273640', font=(FONT_FAMILY, 9))
        if self.boundary is not None:
            polygons = list(self.boundary.geoms) if self.boundary.geom_type == 'MultiPolygon' else [self.boundary]
            for polygon in polygons:
                if polygon.geom_type != 'Polygon':
                    continue
                for ring in (polygon.exterior, *polygon.interiors):
                    coords = list(ring.coords)
                    step = max(1, len(coords)//1500)
                    points = [v for lon, lat in coords[::step] + [coords[-1]] for v in self.xy(lon, lat)]
                    if len(points) >= 4:
                        c.create_line(points, fill='#5c4266', width=1, dash=(4, 4))
        if self.selection:
            w, s, e, n = self.selection
            c.create_rectangle(*self.xy(w, n), *self.xy(e, s), outline='#C88E9b', width=3,
                               fill='#C88E9b', stipple='gray25')
