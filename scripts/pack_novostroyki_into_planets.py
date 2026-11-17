"""Packs the 32 newly generated novostroyki DDS textures, updated materials.json,
and updated generator.lua into all planet archives across repo, desktop, and BeamNG mods.
"""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

TARGET_ZIPS = [
    Path(r"mod\aroundworldng_planet.zip"),
    Path(r"mod\earthng_planet.zip"),
    Path(r"C:\Users\wilsz\Desktop\AWNG\aroundworldng_planet.zip"),
    Path(r"C:\Users\wilsz\Desktop\AWNG\earthng_planet.zip"),
    Path(r"C:\Users\wilsz\AppData\Local\BeamNG\BeamNG.drive\current\mods\aroundworldng_planet.zip"),
    Path(r"C:\Users\wilsz\AppData\Local\BeamNG\BeamNG.drive\current\mods\earthng_planet.zip"),
]

def pack_archive(zip_path: Path, dds_files: list[Path], materials_bytes: bytes, generator_bytes: bytes):
    if not zip_path.is_file():
        print(f"Skipping non-existent zip: {zip_path}")
        return

    print(f"Packing into {zip_path} ({zip_path.stat().st_size} bytes)...")
    tmp_path = zip_path.with_suffix(".tmp.zip")

    # Map of filename in zip -> data bytes to inject/replace
    inject_map = {}
    for dds in dds_files:
        zip_name = f"e2r_stream/fast-art/v10/real/{dds.name}"
        inject_map[zip_name] = dds.read_bytes()

    inject_map["aroundworldng/planet/materials.json"] = materials_bytes
    inject_map["earthng/planet/materials.json"] = materials_bytes
    inject_map["lua/ge/extensions/e2r/generator.lua"] = generator_bytes

    with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        seen = set()
        for item in zin.infolist():
            fn = item.filename
            if fn in seen:
                continue
            seen.add(fn)

            if fn in inject_map:
                zout.writestr(fn, inject_map[fn])
            else:
                zout.writestr(item, zin.read(fn))

        # Write any new files not previously in the zip
        for fn, data in inject_map.items():
            if fn not in seen:
                zout.writestr(fn, data)
                seen.add(fn)

    # In-place overwrite (safe even if BeamNG has the file open for reading)
    with open(tmp_path, "rb") as fin, open(zip_path, "r+b") as fout:
        fout.seek(0)
        shutil.copyfileobj(fin, fout)
        fout.truncate()
    try:
        tmp_path.unlink()
    except Exception:
        pass
    print(f"  Successfully updated {zip_path} (new size: {zip_path.stat().st_size} bytes)")

def verify_archive(zip_path: Path, expected_textures: list[str]):
    if not zip_path.is_file():
        return
    with zipfile.ZipFile(zip_path, "r") as z:
        names = set(z.namelist())
        for tex in expected_textures:
            entry = f"e2r_stream/fast-art/v10/real/{tex}"
            assert entry in names, f"Missing {entry} in {zip_path}"
        assert "aroundworldng/planet/materials.json" in names
        assert "lua/ge/extensions/e2r/generator.lua" in names
        # Check generator.lua deduplication
        gen_count = sum(1 for n in z.namelist() if n == "lua/ge/extensions/e2r/generator.lua")
        assert gen_count == 1, f"Duplicate generator.lua ({gen_count}) in {zip_path}"
    print(f"  Verified {zip_path.name}: all textures, materials, and generator intact!")

def main():
    gen_dir = Path("out/generated_novostroyki")
    dds_files = sorted(list(gen_dir.glob("*.dds")))
    assert len(dds_files) == 72, f"Expected 72 DDS files, found {len(dds_files)}"

    materials_bytes = Path("aroundworldng/planet/materials.json").read_bytes()
    generator_bytes = Path("mod/lua/ge/extensions/e2r/generator.lua").read_bytes()

    for zp in TARGET_ZIPS:
        pack_archive(zp, dds_files, materials_bytes, generator_bytes)

    print("\nVerifying all updated planet archives...")
    tex_names = [f.name for f in dds_files]
    for zp in TARGET_ZIPS:
        verify_archive(zp, tex_names)

    print("\nAll planet archives updated and verified successfully!")

if __name__ == "__main__":
    main()
