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

    import country_ui

    def main():
        root = country_ui.create_root()
        app = country_ui.Setup(root)
        root.mainloop()

    if __name__ == "__main__":
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
