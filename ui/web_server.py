"""
Lightweight Web Server for Interactive Map Selector and Generator UI.
Built on Python's native http.server with zero additional web framework dependencies.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import pathlib
import threading
import webbrowser

from core.config import MapConfig
from generator import AroundWorldGenerator

PORT = 8080
UI_DIR = pathlib.Path(__file__).parent


class AroundWorldWebHandler(SimpleHTTPRequestHandler):
    """Handles static files and generation API requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(UI_DIR / "index.html", "rb") as f:
                self.wfile.write(f.read())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/generate":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(body)

            print(f"[WebUI] Received generation request: {data}")

            try:
                cfg = MapConfig(
                    level_name=data.get("name", "custom_map"),
                    title=data.get("title", "Custom Real-World Map"),
                    center_lat=float(data["lat"]),
                    center_lon=float(data["lon"]),
                    size_meters=float(data["size"]),
                    heightmap_res=int(data.get("res", 1025)),
                    install_to_beamng=bool(data.get("install", True)),
                )

                generator = AroundWorldGenerator(cfg)
                pkg_path = generator.generate()

                resp_payload = {
                    "status": "success",
                    "message": f"Карта успешно создана!\nАрхив: {pkg_path.name}\nПуть: {pkg_path.resolve()}",
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                resp_payload = {"status": "error", "message": f"Ошибка генерации: {str(e)}"}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(resp_payload, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_web_ui(port: int = PORT):
    server = HTTPServer(("127.0.0.1", port), AroundWorldWebHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f" AroundWorldNG Web UI запущен по адресу: {url}")
    print(f" Нажмите Ctrl+C для остановки сервера.")
    print(f"=======================================================\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WebUI] Сервер остановлен.")
