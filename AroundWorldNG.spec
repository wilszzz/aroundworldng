# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [
    ('aroundworldng/fast_tree_materials.json', 'aroundworldng'),
    ('aroundworldng/fast_tree_materials.json', '.'),
    ('aroundworldng/ready_packs.json', 'aroundworldng'),
    ('aroundworldng/ready_packs.json', '.'),
    ('aroundworldng/planet/materials.json', 'aroundworldng/planet'),
    ('aroundworldng/planet/materials.json', 'planet'),
    ('icon.ico', '.'),
]
binaries = []
hiddenimports = [
    'customtkinter',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'shapely',
    'shapely.geometry',
    'shapely.ops',
    'pyproj',
    'osmium',
    'numpy',
    'requests',
    'urllib.request',
    'tkinter',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.ttk',
    'tkinter.font',
]

awng_mods = [f[:-3] for f in os.listdir('aroundworldng') if f.endswith('.py') and not f.startswith('__')]
hiddenimports.extend(awng_mods)
hiddenimports.extend(['aroundworldng.' + m for m in awng_mods])

for pkg in ['customtkinter', 'pyproj', 'shapely', 'osmium']:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

a = Analysis(
    ['AroundWorldNG.py'],
    pathex=['.', 'aroundworldng'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'IPython', 'jupyter'],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AroundWorldNG',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AroundWorldNG',
)
