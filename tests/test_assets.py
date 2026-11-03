import zipfile, json, glob, re

mod_zip = zipfile.ZipFile('build/sochi_track.zip')
mod_files = set(mod_zip.namelist())

bng_files = set()
# Scan only core content assets to minimize RAM footprint
for f in glob.glob('C:/me/Steam/steamapps/common/BeamNG.drive/content/assets/**/*.zip', recursive=True):
    try:
        with zipfile.ZipFile(f) as z:
            for n in z.namelist():
                bng_files.add(n)
    except Exception:
        pass

for extra in [
    'C:/me/Steam/steamapps/common/BeamNG.drive/content/levels/west_coast_usa.zip',
    'C:/me/Steam/steamapps/common/BeamNG.drive/content/levels/template.zip',
]:
    try:
        with zipfile.ZipFile(extra) as z:
            for n in z.namelist():
                bng_files.add(n)
    except Exception:
        pass

print(f"Total BeamNG core assets indexed: {len(bng_files)}")

missing_assets = []

def check_path(ref, src):
    if not ref or not isinstance(ref, str) or not (ref.startswith('/') or ref.startswith('assets/') or ref.startswith('levels/')):
        return
    clean = ref.lstrip('/')
    in_mod = ('levels/sochi_track/' + clean) in mod_files or clean in mod_files or ref in mod_files
    in_bng = clean in bng_files or ref in bng_files
    
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
        if isinstance(v, dict) and 'shapeFile' in v:
            check_path(v['shapeFile'], 'managedItemData.json')

for n in mod_zip.namelist():
    if n.endswith('.materials.json'):
        raw = mod_zip.read(n).decode('utf-8', errors='ignore')
        raw = re.sub(r',\s*([\]}])', r'\1', raw)
        mats = json.loads(raw)
        for mname, m in mats.items():
            if not isinstance(m, dict): continue
            for k, v in m.items():
                if isinstance(v, str) and (v.endswith('.png') or v.endswith('.dds')):
                    check_path(v, f'{n}:{mname}')
            for s in m.get('Stages', []):
                if not isinstance(s, dict): continue
                for k, v in s.items():
                    if isinstance(v, str) and (v.endswith('.png') or v.endswith('.dds')):
                        check_path(v, f'{n}:{mname}')

if missing_assets:
    print(f"FAILED: Found {len(missing_assets)} missing asset references:")
    for a, s in missing_assets[:20]:
        print(f"  - {a} (in {s})")
else:
    print("SUCCESS: 100% of asset references exist in the mod or in BeamNG core!")
