"""
AroundWorldNG — CLI and Main Entry Point.
"""

import argparse
import pathlib
import sys

# Ensure UTF-8 output encoding on Windows consoles and protect against None stdout in GUI/noconsole
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from core.config import MapConfig
from generator import AroundWorldGenerator


def parse_args():
    parser = argparse.ArgumentParser(
        description="AroundWorldNG: Real-world BeamNG.drive Map Generator using Yandex Maps and OSM"
    )
    parser.add_argument("--lat", type=float, default=55.751244, help="Center latitude (e.g. 55.751244)")
    parser.add_argument("--lon", type=float, default=37.618423, help="Center longitude (e.g. 37.618423)")
    parser.add_argument("--size", type=float, default=1024.0, help="Map size in meters (e.g. 1024, 2048, 4096)")
    parser.add_argument("--name", type=str, default="custom_yandex_map", help="Level folder/file name")
    parser.add_argument("--title", type=str, default="Custom Real-World Map", help="Display title in BeamNG menu")
    parser.add_argument("--res", type=int, default=1025, choices=[513, 1025, 2049, 4097], help="Heightmap resolution")
    parser.add_argument("--zoom", type=int, default=18, help="Yandex Satellite zoom level (16-19)")
    parser.add_argument("--install", action="store_true", help="Auto-copy mod zip directly into BeamNG mods folder")
    parser.add_argument("--web", action="store_true", help="Start interactive web interface with map selector")
    return parser.parse_args()


def main():
    try:
        if len(sys.argv) == 1:
            print("=" * 70)
            print("  AroundWorldNG - Генератор карт реального мира для BeamNG.drive")
            print("=" * 70)
            print("  Запуск интерактивного визуального веб-интерфейса карты...")
            print("  (Для использования через командную строку: AroundWorldNG.exe --help)")
            print("=" * 70 + "\n")
            from ui.web_server import start_web_ui
            start_web_ui()
            return

        args = parse_args()

        if args.web:
            from ui.web_server import start_web_ui
            start_web_ui()
            return

        config = MapConfig(
            level_name=args.name,
            title=args.title,
            center_lat=args.lat,
            center_lon=args.lon,
            size_meters=args.size,
            heightmap_res=args.res,
            sat_zoom=args.zoom,
            install_to_beamng=args.install,
            output_dir=pathlib.Path("build"),
        )

        generator = AroundWorldGenerator(config)
        generator.generate()
    except KeyboardInterrupt:
        print("\n[AroundWorldNG] Работа завершена пользователем.")
    except Exception as e:
        import traceback
        print("\n" + "=" * 70)
        print("  [AroundWorldNG] КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ:")
        print("=" * 70)
        traceback.print_exc()
        print("=" * 70)
        try:
            input("\nНажмите Enter для выхода...")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
