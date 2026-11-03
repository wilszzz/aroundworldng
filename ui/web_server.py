"""
Lightweight Web Server for Interactive Map Selector and Generator UI.
Built on Python's native http.server with zero additional web framework dependencies.
Includes real-time background task tracking, log streaming, OSM geocoding, and preset locations.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional

from core.config import MapConfig, get_resource_path
from generator import AroundWorldGenerator

PORT = 8080
UI_DIR = get_resource_path("ui")

# Curated presets of iconic racing and scenic locations
PRESETS = [
    {
        "id": "sochi_autodrom",
        "name": "Сочи Автодром / Олимпийский парк",
        "badge": "🏁 Трасса F1",
        "lat": 43.4056,
        "lon": 39.9547,
        "size": 2048,
        "res": 1025,
        "title": "Сочи Автодром (Олимпийский парк)",
        "level_name": "sochi_autodrom",
        "desc": "Ровная скоростная трасса вокруг олимпийских стадионов и набережной Черного моря"
    },
    {
        "id": "krasnaya_polyana",
        "name": "Красная Поляна / Роза Хутор",
        "badge": "⛰️ Горный серпантин",
        "lat": 43.6744,
        "lon": 40.2974,
        "size": 2048,
        "res": 1025,
        "title": "Красная Поляна — Горные виражи",
        "level_name": "krasnaya_polyana",
        "desc": "Захватывающий горный рельеф Кавказа с крутыми спусками, мостами и шпильками"
    },
    {
        "id": "nurburgring",
        "name": "Нюрбургринг Нордшляйфе (Зелёный ад)",
        "badge": "👑 Легендарный трек",
        "lat": 50.3341,
        "lon": 6.9427,
        "size": 4096,
        "res": 2049,
        "title": "Nürburgring Nordschleife",
        "level_name": "nurburgring_nordschleife",
        "desc": "20-километровый культовый автодром в лесах Айфеля с перепадами высот до 300 метров"
    },
    {
        "id": "monaco_gp",
        "name": "Монте-Карло / Монако",
        "badge": "🏎️ Городской трек",
        "lat": 43.7384,
        "lon": 7.4246,
        "size": 2048,
        "res": 1025,
        "title": "Monaco GP Circuit",
        "level_name": "monaco_gp_circuit",
        "desc": "Узкие набережные, казино, тоннели и шпильки знаменитого княжества"
    },
    {
        "id": "mount_haruna",
        "name": "Гора Харуна / Акина (Touge)",
        "badge": "🚗 Дрифт & Touge",
        "lat": 36.4770,
        "lon": 138.8770,
        "size": 4096,
        "res": 2049,
        "title": "Mount Haruna (Akina Touge)",
        "level_name": "mount_haruna_touge",
        "desc": "Культовый японский горный спуск со связками из 5 шпилек подряд и крутыми виражами"
    },
    {
        "id": "moscow_msu",
        "name": "Москва, Воробьёвы горы / МГУ",
        "badge": "🏙️ Городская локация",
        "lat": 55.7029,
        "lon": 37.5309,
        "size": 2048,
        "res": 1025,
        "title": "Москва — Воробьёвы горы",
        "level_name": "moscow_sparrow_hills",
        "desc": "Широкие проспекты, смотровая площадка, набережная Москвы-реки и здание МГУ"
    },
    {
        "id": "transfagarasan",
        "name": "Серпантин Трансфэгэрашан (Румыния)",
        "badge": "🌲 Высокогорье",
        "lat": 45.5982,
        "lon": 24.6166,
        "size": 4096,
        "res": 2049,
        "title": "Transfăgărășan Mountain Pass",
        "level_name": "transfagarasan_pass",
        "desc": "Одна из самых живописных и сложных высокогорных дорог Европы через Карпаты"
    },
    {
        "id": "vladivostok",
        "name": "Владивосток — Золотой Рог",
        "badge": "🌊 Побережье",
        "lat": 43.1155,
        "lon": 131.8855,
        "size": 2048,
        "res": 1025,
        "title": "Владивосток — Бухта Золотой Рог",
        "level_name": "vladivostok_bay",
        "desc": "Холмистый приморский рельеф с крутыми подъемами, мостами и бухтой"
    }
]


class TaskState:
    """Thread-safe state container for active level generation."""

    def __init__(self):
        self.lock = threading.Lock()
        self.status = "idle"  # "idle" | "running" | "success" | "error"
        self.progress = 0
        self.stage = "Ожидание запуска"
        self.logs: List[str] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.start_time: Optional[float] = None
        self.elapsed_sec: float = 0.0

    def start(self, title: str):
        with self.lock:
            self.status = "running"
            self.progress = 5
            self.stage = f"Инициализация пайплайна: {title}..."
            self.logs = [f"[{time.strftime('%H:%M:%S')}] ▶ Запуск пайплайна генерации для: {title}"]
            self.result = None
            self.error = None
            self.start_time = time.time()
            self.elapsed_sec = 0.0

    def add_log(self, raw_message: str):
        timestamp = time.strftime("%H:%M:%S")
        for line in raw_message.splitlines():
            clean = line.strip("\r\n")
            if not clean:
                continue
            with self.lock:
                self.logs.append(f"[{timestamp}] {clean}")
                self._update_progress_from_log(clean)

    def _update_progress_from_log(self, line: str):
        lower = line.lower()
        if "aroundworldng — generating level" in lower or "generating level" in lower:
            self.progress = max(self.progress, 10)
            self.stage = "Расчет географических границ (Bounding Box)..."
        elif "satellite" in lower or "yandex" in lower or "fetch_bbox" in lower:
            self.progress = max(self.progress, 25)
            self.stage = "Загрузка спутниковых снимков Яндекс..."
        elif "elevation" in lower or "dem" in lower:
            self.progress = max(self.progress, 40)
            self.stage = "Получение матрицы высот рельефа (DEM)..."
        elif "openstreetmap" in lower or "osm" in lower:
            self.progress = max(self.progress, 55)
            self.stage = "Загрузка дорожной сети и зданий OpenStreetMap..."
        elif "spatialexclusion" in lower or "exclusion" in lower or "filter_buildings" in lower:
            self.progress = max(self.progress, 65)
            self.stage = "Фильтрация артефактов и очистка коридоров дорог..."
        elif "roadcarver" in lower or "carve_roads" in lower or "road" in lower:
            self.progress = max(self.progress, 75)
            self.stage = "Прорезка и сглаживание дорожного полотна..."
        elif "heightmap" in lower or "torque3d" in lower:
            self.progress = max(self.progress, 85)
            self.stage = "Генерация 16-битного рельефа и theTerrain.ter..."
        elif "levelbuilder" in lower or "assembling" in lower:
            self.progress = max(self.progress, 92)
            self.stage = "Сборка PBR-материалов, сплайнов и упаковка BeamNG мода..."
        elif "successfully packaged mod zip" in lower or "output mod:" in lower:
            self.progress = 100
            self.stage = "Генерация успешно завершена!"

    def finish_success(self, pkg_path: pathlib.Path, installed: bool):
        with self.lock:
            self.status = "success"
            self.progress = 100
            self.stage = "Карта успешно создана и упакована!"
            if self.start_time:
                self.elapsed_sec = round(time.time() - self.start_time, 1)
            self.result = {
                "name": pkg_path.name,
                "path": str(pkg_path.resolve()),
                "parent_dir": str(pkg_path.parent.resolve()),
                "installed": installed,
                "elapsed_sec": self.elapsed_sec,
            }
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] ✅ [OK] Готово! Архив мода: {pkg_path.resolve()}")

    def finish_error(self, err_message: str):
        with self.lock:
            self.status = "error"
            self.stage = f"Ошибка: {err_message}"
            self.error = err_message
            if self.start_time:
                self.elapsed_sec = round(time.time() - self.start_time, 1)
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] ❌ [ERROR] {err_message}")

    def get_snapshot(self, since: int = 0) -> Dict[str, Any]:
        with self.lock:
            total_logs = len(self.logs)
            slice_since = max(0, min(since, total_logs))
            new_logs = self.logs[slice_since:]
            current_elapsed = self.elapsed_sec
            if self.status == "running" and self.start_time:
                current_elapsed = round(time.time() - self.start_time, 1)

            return {
                "status": self.status,
                "progress": self.progress,
                "stage": self.stage,
                "logs": new_logs,
                "log_total": total_logs,
                "result": self.result,
                "error": self.error,
                "elapsed_sec": current_elapsed,
            }


# Singleton task state
current_task = TaskState()


class StreamInterceptor:
    """Tee wrapper capturing stdout/stderr while streaming to original console."""

    def __init__(self, original_stream, on_line_callback):
        self.original = original_stream
        self.callback = on_line_callback
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, s):
        try:
            self.original.write(s)
            self.original.flush()
        except Exception:
            pass

        with self._lock:
            self._buffer += s
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                clean = line.strip("\r")
                if clean:
                    self.callback(clean)

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass

        with self._lock:
            clean = self._buffer.strip("\r\n ")
            if clean:
                self.callback(clean)
                self._buffer = ""

    def __getattr__(self, name):
        return getattr(self.original, name)


def _run_generator_thread(cfg: MapConfig):
    """Background worker executing the level generation pipeline."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    interceptor = StreamInterceptor(old_stdout, current_task.add_log)
    sys.stdout = interceptor
    sys.stderr = interceptor
    try:
        generator = AroundWorldGenerator(cfg)
        pkg_path = generator.generate()
        current_task.finish_success(pkg_path, cfg.install_to_beamng)
    except Exception as e:
        tb = traceback.format_exc()
        current_task.finish_error(str(e))
        current_task.add_log(tb)
    finally:
        interceptor.flush()
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def open_system_folder(path_str: str):
    """Safely opens the target file or folder in Windows Explorer or system file manager."""
    try:
        target = pathlib.Path(path_str).resolve()
        if not target.exists():
            return False

        if sys.platform == "win32":
            if target.is_file():
                subprocess.Popen(f'explorer /select,"{str(target)}"')
            else:
                os.startfile(str(target))
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if target.is_file() else "", str(target)])
            return True
        else:
            folder = target.parent if target.is_file() else target
            subprocess.Popen(["xdg-open", str(folder)])
            return True
    except Exception as e:
        print(f"[WebUI] Error opening system folder: {e}")
        return False


class AroundWorldWebHandler(SimpleHTTPRequestHandler):
    """Handles static files, API requests, real-time logging, and geocoding."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def _send_json(self, data: Any, status_code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            index_path = get_resource_path("ui/index.html")
            if not index_path.exists():
                self.send_error(404, "index.html not found")
                return
            with open(index_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            since = 0
            try:
                since = int(query.get("since", ["0"])[0])
            except ValueError:
                since = 0
            self._send_json(current_task.get_snapshot(since=since))
            return

        if path == "/api/presets":
            self._send_json(PRESETS)
            return

        if path == "/api/geocode":
            query = urllib.parse.parse_qs(parsed.query)
            q = query.get("q", [""])[0].strip()
            if not q:
                self._send_json([])
                return

            try:
                # Proxy search to OpenStreetMap Nominatim with respectful User-Agent
                params = urllib.parse.urlencode({
                    "format": "json",
                    "q": q,
                    "addressdetails": "1",
                    "limit": "6"
                })
                url = f"https://nominatim.openstreetmap.org/search?{params}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "AroundWorldNG-BeamNG/1.1.3 (BeamNG.drive procedural map tool)"
                    }
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json(data)
            except Exception as e:
                print(f"[WebUI] Geocode proxy error: {e}")
                self._send_json({"error": str(e), "results": []}, status_code=200)
            return

        # Fallback to static files
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/generate":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json({"status": "error", "message": "Некорректный JSON payload"}, status_code=400)
                return

            # Check if generation is already running
            if current_task.status == "running":
                self._send_json(
                    {"status": "busy", "message": "Генерация уже выполняется. Дождитесь завершения."},
                    status_code=409
                )
                return

            try:
                lat = float(data["lat"])
                lon = float(data["lon"])
                size = float(data["size"])
                res = int(data.get("res", 1025))

                if not (-85.0 <= lat <= 85.0):
                    raise ValueError(f"Широта {lat} вне допустимого диапазона [-85, 85]")
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError(f"Долгота {lon} вне допустимого диапазона [-180, 180]")
                if size < 256 or size > 16384:
                    raise ValueError(f"Размер карты {size}м вне диапазона [256, 16384]")

                cfg = MapConfig(
                    level_name=data.get("name", "custom_map"),
                    title=data.get("title", "Custom Real-World Map"),
                    center_lat=lat,
                    center_lon=lon,
                    size_meters=size,
                    heightmap_res=res,
                    install_to_beamng=bool(data.get("install", True)),
                )

                # Initialize state and spawn generation worker thread
                current_task.start(cfg.title)
                worker = threading.Thread(
                    target=_run_generator_thread,
                    args=(cfg,),
                    daemon=True,
                    name="AroundWorld-Generator-Worker"
                )
                worker.start()

                # If caller requested synchronous response (e.g. for testing/scripts)
                if data.get("sync", False):
                    worker.join()
                    snapshot = current_task.get_snapshot()
                    self._send_json(snapshot, status_code=200 if snapshot["status"] == "success" else 500)
                    return

                self._send_json({
                    "status": "started",
                    "message": "Пайплайн генерации запущен в фоновом режиме",
                    "config": {
                        "name": cfg.level_name,
                        "title": cfg.title,
                        "lat": cfg.center_lat,
                        "lon": cfg.center_lon,
                        "size": cfg.size_meters,
                        "res": cfg.heightmap_res,
                    }
                }, status_code=202)
            except Exception as e:
                self._send_json({"status": "error", "message": f"Ошибка параметров: {str(e)}"}, status_code=400)
            return

        if path == "/api/open_folder":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(body)
                target_path = data.get("path")
                if not target_path:
                    # Default to current task result path or build directory
                    if current_task.result and "path" in current_task.result:
                        target_path = current_task.result["path"]
                    else:
                        target_path = str(pathlib.Path("build").resolve())

                success = open_system_folder(target_path)
                self._send_json({"status": "ok" if success else "failed", "path": target_path})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status_code=500)
            return

        self.send_error(404, "Endpoint not found")

    def log_message(self, format, *args):
        # Silence routine static file polling logs to keep terminal clean
        if len(args) > 0 and isinstance(args[0], str) and "/api/status" in args[0]:
            return
        super().log_message(format, *args)


def start_web_ui(port: int = PORT, open_browser: bool = True):
    """Starts the web server and opens the browser interface."""
    server = HTTPServer(("127.0.0.1", port), AroundWorldWebHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f" AroundWorldNG Web UI v1.1.3 запущен по адресу: {url}")
    print(f" Нажмите Ctrl+C для остановки сервера.")
    print(f"=======================================================\n")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WebUI] Сервер остановлен.")
