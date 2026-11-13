"""Integration tests verifying the integrity and stability of generator.lua and builder_preview."""
from pathlib import Path
import zipfile
import pytest

MODS_DIR = Path(r"C:\Users\wilsz\AppData\Local\BeamNG\BeamNG.drive\current\mods")
ROOT = Path(__file__).resolve().parents[1]

def test_zip_archives_deduplication():
    """Verify that planet mod archives have exactly one generator.lua entry and no duplicates."""
    for zip_name in ("aroundworldng_planet.zip", "earthng_planet.zip"):
        zip_path = MODS_DIR / zip_name
        assert zip_path.is_file(), f"{zip_name} does not exist in mods directory!"
        with zipfile.ZipFile(zip_path, "r") as z:
            gen_entries = [info for info in z.infolist() if info.filename == "lua/ge/extensions/e2r/generator.lua"]
            assert len(gen_entries) == 1, f"{zip_name} has {len(gen_entries)} generator.lua entries (expected exactly 1)"

def test_generator_luajit_compilation():
    """Verify that generator.lua passes LuaJIT compilation and respects the 200 locals limit."""
    import sys
    sys.path.append(r"C:\Users\wilsz\Desktop\earthng\.venv\Lib\site-packages")
    import lupa
    lua = lupa.LuaRuntime()

    zip_path = MODS_DIR / "aroundworldng_planet.zip"
    with zipfile.ZipFile(zip_path, "r") as z:
        code = z.read("lua/ge/extensions/e2r/generator.lua").decode("utf-8")

    # Compile bytecode in LuaJIT - raises an exception if > 200 locals or syntax error
    lua.compile(code)

def test_generator_branding_and_safe_materials():
    """Verify generator.lua has proper rebrand strings and does not contain broken material identifiers."""
    zip_path = MODS_DIR / "aroundworldng_planet.zip"
    with zipfile.ZipFile(zip_path, "r") as z:
        code = z.read("lua/ge/extensions/e2r/generator.lua").decode("utf-8")

    assert "aroundworldng-lua-v1" in code
    assert "Пятёрочка" in code
    assert "Магнит" in code
    assert "function BLD.garageDoors(scene, doors, a, b, length, base, seam)" in code
    assert "wall_wall_block" not in code
    assert "local detailed = not options.far and BLD.city" in code
    assert "maxFloors = 25" in code

def test_builder_preview_render():
    """Verify builder_preview.render generates preview without error using installed planet textures."""
    import sys
    sys.path.insert(0, str(ROOT / "aroundworldng"))
    import builder_preview

    look = {
        "block": "soviet-panel",
        "buildings": "panel",
        "asphalt": "smooth",
        "verge": "grass",
        "markings": "white",
    }
    include = {"water": False, "forest": True}
    img, sources = builder_preview.render(look, include, str(MODS_DIR.parent))
    assert img.size == (580, 320)
    assert len(sources) > 0
    # Must pull textures from installed planet
    assert any(s == "installed planet" for s in sources.values())
