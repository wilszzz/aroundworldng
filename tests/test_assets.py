import zipfile, json, glob, re

mod_zip = zipfile.ZipFile('build/sochi_track.zip')
mod_files = set(mod_zip.namelist())

bng_files = set()
for f in glob.glob('C:/me/Steam/steamapps/common/BeamNG.drive/**/*.zip', recursive=True):
    try:
        z = zipfile.ZipFile(f)
        for n in z.namelist():
            bng_files.add(n)
            bng_files.add('/' + n)
    except Exception:
        pass

print(f"Total BeamNG core assets indexed: {len(bng_files)}")

missing_assets = []

def check_path(ref, src):
    if not ref or not isinstance(ref, str) or not (ref.startswith('/') or ref.startswith('assets/') or ref.startswith('levels/')):
        return
    clean = ref.lstrip('/')
    in_mod = ('levels/sochi_track/' + clean) in mod_files or clean in mod_files or ref in mod_files
    in_bng = clean in bng_files or ('/' + clean) in bng_files or ref in bng_files
    
    if not in_mod and not in_bng:
        alt_link = clean + '.link'
        alt_dds = clean.replace('.png', '.dds') if clean.endswith('.png') else clean.replace('.dds', '.png')
        alt_color_dds = clean.replace('.color.png', '.color.dds')
        alt_data_dds = clean.replace('.data.png', '.data.dds')
        alt_norm_dds = clean.replace('.normal.png', '.normal.dds')
        if (alt_link in bng_files or alt_dds in bng_files or 
            alt_color_dds in bng_files or alt_data_dds in bng_files or alt_norm_dds in bng_files):
            in_bng = True
            
    if not in_mod and not in_bng:
        missing_assets.append((ref, src))

for n in mod_zip.namelist():
    if 'items.level.json' in n:
        for line in mod_zip.read(n).decode('utf-8').splitlines():
            if not line.strip(): continue
            obj = json.loads(line)
            if 'shapeName' in obj:
                check_path(obj['shapeName'], n)

if 'levels/sochi_track/art/forest/managedItemData.json' in mod_files:
    m = json.loads(mod_zip.read('levels/sochi_track/art/forest/managedItemData.json').decode('utf-8'))
    for k, v in m.items():
        if 'shapeFile' in v:
            check_path(v['shapeFile'], 'managedItemData.json')

for n in mod_zip.namelist():
    if n.endswith('materials.json'):
        txt = mod_zip.read(n).decode('utf-8')
        for path in re.findall(r'"(/[^"]+\.[a-zA-Z0-9]+)"', txt):
            check_path(path, n)
        for path in re.findall(r'"(assets/[^"]+\.[a-zA-Z0-9]+)"', txt):
            check_path(path, n)
        for path in re.findall(r'"(levels/[^"]+\.[a-zA-Z0-9]+)"', txt):
            check_path(path, n)

if missing_assets:
    print(f"FAILED: Found {len(missing_assets)} missing asset references:")
    for ref, src in missing_assets:
        print(f"  - {ref} (in {src})")
else:
    print("SUCCESS: 100% of asset references exist in the mod or in BeamNG core!")
