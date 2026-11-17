"""AroundWorldNG Map Studio - Standalone Executable Entrypoint."""
import multiprocessing
import os
import sys
import traceback
from pathlib import Path

multiprocessing.freeze_support()

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

os.chdir(str(ROOT))

log_file = ROOT / "startup_error.log"

try:
    # Ensure both ROOT and ROOT/aroundworldng are on sys.path
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    awng_dir = ROOT / "aroundworldng"
    if awng_dir.is_dir() and str(awng_dir) not in sys.path:
        sys.path.insert(0, str(awng_dir))

    import country_fetch
    country_fetch.auto_detect_proxy()

    if __name__ == "__main__":
        if len(sys.argv) > 1:
            first = sys.argv[1]
            if first == "--cli-job" and len(sys.argv) > 2:
                import build_country
                build_country.run_job(Path(sys.argv[2]))
                sys.exit(0)
            elif first == "--cli-cut":
                import osm_tiles_country
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                osm_tiles_country.main()
                sys.exit(0)
            elif first == "--job" and len(sys.argv) > 2:
                import build_country
                build_country.run_job(Path(sys.argv[2]))
                sys.exit(0)
            elif first.endswith(".py"):
                script_name = Path(first).stem
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                if script_name == "build_country":
                    import build_country
                    build_country.main()
                    sys.exit(0)
                elif script_name == "osm_tiles_country":
                    import osm_tiles_country
                    osm_tiles_country.main()
                    sys.exit(0)

        import country_ui

        auto_build_query = None
        if len(sys.argv) > 1:
            for idx, arg in enumerate(sys.argv):
                if arg == "--auto-build" and idx + 1 < len(sys.argv):
                    auto_build_query = sys.argv[idx + 1]
                    break

        def main():
            root = country_ui.create_root()
            app = country_ui.Setup(root)

            if auto_build_query:
                def trigger_auto_build():
                    if not app.places:
                        root.after(500, trigger_auto_build)
                        return
                    q = auto_build_query.casefold()
                    matched = None
                    for p in app.places:
                        if q in p['name'].casefold() or q in p['id'].casefold():
                            matched = p
                            break
                    if not matched and app.places:
                        matched = app.places[0]
                    if matched:
                        app.select_place(matched)

                    def do_build():
                        try:
                            if hasattr(app, 'optimize_source'):
                                app.optimize_source()
                        except Exception:
                            pass
                        app.build()

                    root.after(1200, do_build)

                root.after(1000, trigger_auto_build)

            root.mainloop()

        main()

except Exception as exc:
    with open(log_file, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("AroundWorldNG Error", f"Ошибка запуска:\n{exc}\n\nПодробности в {log_file}")
        r.destroy()
    except Exception:
        pass
    sys.exit(1)
