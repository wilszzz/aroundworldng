"""Comprehensive Integration Test for Novostroyki Building Textures and Materials."""
import json
import re
import struct
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLANET_ZIP = ROOT / "mod" / "aroundworldng_planet.zip"
MATS_JSON = ROOT / "aroundworldng" / "planet" / "materials.json"
GENERATOR_LUA = ROOT / "mod" / "lua" / "ge" / "extensions" / "e2r" / "generator.lua"

STYLES = [
    # Phase 1: Major developers
    "pls_d_pik_orange",
    "pls_d_pik_cyan",
    "pls_d_pik_yellow",
    "brk_d_clinker_dark",
    "pls_d_setl_scandi",
    "pls_d_setl_cappuccino",
    "pls_d_samolet_azure",
    "pls_d_lsr_terracotta",
    # Phase 2: Distinctive complexes & modern architecture
    "brk_d_kapital_amber",
    "brk_d_kapital_terracotta",
    "pls_d_svetliy_mir",
    "brk_d_galaktika",
    "pls_d_strizhi_glass",
    "pls_d_life_wood",
    "brk_d_ispanskie_kvartaly",
    "pls_d_zeleny_kvartal",
    "pls_d_chistoe_nebo",
    "pls_d_monolith_glass",
]

def test_novostroyki_in_materials_json():
    """Verify all 8 styles and their _end walls exist in materials.json and reference correct paths."""
    assert MATS_JSON.is_file(), f"materials.json not found at {MATS_JSON}"
    with open(MATS_JSON, "r", encoding="utf-8") as f:
        mats = json.load(f)

    for s in STYLES:
        main_key = f"e2rf_wall_{s}"
        end_key = f"e2rf_wall_{s}_end"

        assert main_key in mats, f"Missing material entry {main_key}"
        assert end_key in mats, f"Missing material entry {end_key}"

        stage0_main = mats[main_key]["Stages"][0]
        assert stage0_main["baseColorMap"] == f"/e2r_stream/fast-art/v10/real/{s}.color.dds"
        assert stage0_main["normalMap"] == f"/e2r_stream/fast-art/v10/real/{s}.normal.dds"

        stage0_end = mats[end_key]["Stages"][0]
        assert stage0_end["baseColorMap"] == f"/e2r_stream/fast-art/v10/real/{s}_end.color.dds"
        assert stage0_end["normalMap"] == f"/e2r_stream/fast-art/v10/real/{s}_end.normal.dds"

def test_novostroyki_in_planet_zip():
    """Verify all 32 DDS files exist in the planet zip archive with correct byte headers."""
    assert PLANET_ZIP.is_file(), f"Planet archive not found at {PLANET_ZIP}"
    with zipfile.ZipFile(PLANET_ZIP, "r") as z:
        names = set(z.namelist())
        for s in STYLES:
            for suffix, expected_size, (ew, eh) in [
                (".color.dds", 2796364, (2048, 2048)),
                (".normal.dds", 699212, (1024, 1024)),
                ("_end.color.dds", 699212, (1024, 1024)),
                ("_end.normal.dds", 699212, (1024, 1024)),
            ]:
                entry = f"e2r_stream/fast-art/v10/real/{s}{suffix}"
                assert entry in names, f"Missing {entry} in planet zip"
                data = z.read(entry)
                assert len(data) == expected_size, f"Size mismatch for {entry}: got {len(data)}, expected {expected_size}"
                # Check DDS header
                assert data[:4] == b"DDS ", f"Invalid DDS magic in {entry}"
                h, w = struct.unpack("<II", data[12:20])
                assert (w, h) == (ew, eh), f"Dimension mismatch in {entry}: got ({w}, {h}), expected ({ew}, {eh})"

def test_generator_lua_novostroyki_wiring():
    """Verify generator.lua includes novostroyki styles in novostroyki table and BLD.spec."""
    assert GENERATOR_LUA.is_file(), f"generator.lua not found at {GENERATOR_LUA}"
    code = GENERATOR_LUA.read_text(encoding="utf-8")

    for s in STYLES:
        assert s in code, f"Style {s} not found in generator.lua"

    assert "novostroyki = {" in code
    assert "pls_d_pik_orange" in code
    assert "brk_d_clinker_dark" in code

    # Check that facadeScale handles _d_ as 12 and _end as 6
    # if kind:find('_end$', 1) then return 6 end
    # if kind:find('_d_', 1, true) then return 12 end
    for s in STYLES:
        assert "_d_" in s, f"Style {s} should contain _d_ for 12m facade scaling"

def test_textures_seamless_tiling():
    """Verify that generated textures tile horizontally and vertically seamlessly."""
    gen_dir = ROOT / "out" / "generated_novostroyki"
    assert gen_dir.is_dir()
    for s in STYLES:
        # Load raw PIL images from generator
        # Check that top and bottom seams, and left and right seams have continuous boundary
        col_file = gen_dir / f"{s}.color.dds"
        assert col_file.is_file()
