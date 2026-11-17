"""Audit/download raw Terrarium sources. No road profiles or geometry are prepared here."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import time
import urllib.request

import tls


def auto_detect_proxy():
    if os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY'):
        return os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    import socket
    for port in (7890, 7897, 10808, 10809, 2080, 1080):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.15):
                url = f'http://127.0.0.1:{port}'
                for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'):
                    os.environ[k] = url
                return url
        except (OSError, socket.timeout):
            continue
    return None


auto_detect_proxy()


def audit(index, cache):
    """DEM under every source tile's coverage, not the package box: a country's box is half
    sea and neighbours (Ukraine: OSM tiles only where the data is)."""
    tile=lambda lon,lat: ((lon+180)/360*4096,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*4096)
    keys=set()
    for t in index['tiles'].values():
        w,s,e,n=t['coverage']
        x0,y0=tile(w,n); x1,y1=tile(e,s)
        # One extra tile handles complete OSM features and filtered edge samples.
        keys.update((x,y) for x in range(math.floor(x0)-1,math.floor(x1)+2)
                    for y in range(math.floor(y0)-1,math.floor(y1)+2))
    return [Path(cache)/'terrain/12'/str(x)/f'{y}.png' for x,y in sorted(keys)]


# Terrarium has seams of impossible depth: along 30 degrees E in the Black Sea a stripe four pixels
# wide down to -13 km (-3.3 km on the shore at 46.3 N). A pixel further than SEAM from the lower median
# of the eight pixels SEAM_RING away takes that median.
SEAM = 1000.
SEAM_RING = 6
SEAM_MAX = 4096


def clean_dsm_to_dtm(heights, kernel_size=5, spike_thresh=3.5):
    """Strip radar DSM rooftop spikes and fill courtyard shadow pits from a DEM tile.
    Uses morphological opening (erosion followed by dilation) to identify bare earth
    and morphological closing to eliminate void pits."""
    import numpy as np
    try:
        import scipy.ndimage as ndi
    except ImportError:
        return np.asarray(heights, dtype=np.float64)

    h = np.asarray(heights, dtype=np.float64)
    if not h.size or h.ndim != 2:
        return h

    # Bare earth envelope via opening (removes objects sticking UP by kernel_size pixels)
    opened = ndi.grey_opening(h, size=kernel_size)
    # Void envelope via closing (fills pits sinking DOWN by kernel_size pixels)
    closed = ndi.grey_closing(h, size=kernel_size)

    # Positive spikes (e.g. 16-25 floor roofs): where raw DEM exceeds opened ground by spike_thresh
    spike_mask = (h - opened) > spike_thresh
    # Negative pits (e.g. courtyard radar void shadows): where raw DEM sinks below closed ground by spike_thresh
    pit_mask = (closed - h) > spike_thresh

    dtm = h.copy()
    dtm[spike_mask] = opened[spike_mask]
    dtm[pit_mask] = closed[pit_mask]
    return dtm


def terrarium_heights(rgb):
    """Metres of an (h, w, 3) Terrarium RGB array."""
    import numpy as np
    a = np.asarray(rgb, dtype=np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def terrarium_rgb(heights):
    """The (h, w, 3) uint8 Terrarium encoding of metres (1/256 m steps)."""
    import numpy as np
    v = np.round((np.asarray(heights, dtype=np.float64) + 32768) * 256).astype(np.int64)
    v = np.clip(v, 0, (1 << 24) - 1)
    return np.stack([v >> 16, (v >> 8) & 255, v & 255], axis=-1).astype(np.uint8)


def mend_seams(heights):
    """(heights, mended pixel count) of one tile: see SEAM. The input is not changed."""
    import numpy as np
    h = np.asarray(heights, dtype=np.float64)
    if not h.size or float(h.max() - h.min()) <= SEAM:
        return h, 0
    r = SEAM_RING
    n, m = h.shape

    def along(size, d):
        k = np.arange(size) + d
        return np.where((k < 0) | (k >= size), np.arange(size) - d, k)

    ring = np.stack([h[np.ix_(along(n, dy), along(m, dx))] for dy in (-r, 0, r) for dx in (-r, 0, r) if dy or dx])
    ring.sort(axis=0)
    median = ring[3]
    bad = np.abs(h - median) > SEAM
    if not bad.any() or int(bad.sum()) > SEAM_MAX:
        return h, 0
    out = h.copy()
    out[bad] = median[bad]
    return out, int(bad.sum())


def mend_file(path, backup=None):
    """Mend a cached tile's seams in place."""
    import shutil
    import numpy as np
    from PIL import Image
    path = Path(path)
    with Image.open(path) as image:
        rgb = np.asarray(image.convert('RGB'))
    heights, count = mend_seams(terrarium_heights(rgb))
    if count:
        if backup is not None:
            keep = Path(backup) / path.parent.name / path.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, keep)
        tmp = path.with_suffix(f'.{os.getpid()}.mend.part')
        Image.fromarray(terrarium_rgb(heights), 'RGB').save(tmp, format='PNG')
        os.replace(tmp, path)
    return count


def fetch(path):
    from PIL import Image
    if path.exists():
        return
    parent = path.parent.name
    name = path.name
    urls = [
        f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/12/{parent}/{name}',
        f'https://elevation-tiles-prod.s3.amazonaws.com/terrarium/12/{parent}/{name}',
        f'https://elevation-tiles-prod.s3.us-east-1.amazonaws.com/terrarium/12/{parent}/{name}',
    ]
    data = None
    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'AroundWorldNG/1.0'})
            with urllib.request.urlopen(req, timeout=15, context=tls.context()) as response:
                data = response.read()
            if data:
                break
        except Exception as exc:
            last_err = exc
            continue
    if not data:
        raise last_err or OSError(f"Failed to fetch DEM {parent}/{name}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.{os.getpid()}.png.part')
    tmp.write_bytes(data)
    with Image.open(tmp) as image:
        if image.size != (256, 256):
            raise ValueError(f'invalid DEM {name}')
        image.verify()
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5)


def height(lat,lon,cache):
    """Raw Terrarium height in metres at a point (bilinear in the z12 tile), fetched if missing.
    For placing cameras; the exporter samples its own despiked grid."""
    from PIL import Image
    fx=(lon+180)/360*4096*256-.5; fy=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*4096*256-.5
    x0,y0=math.floor(fx),math.floor(fy); u,v=fx-x0,fy-y0
    def at(px,py):
        path=Path(cache)/'terrain/12'/str(px//256)/f'{py//256}.png'
        fetch(path)
        with Image.open(path) as image:
            r,g,b=image.convert('RGB').getpixel((px%256,py%256))
        return r*256+g+b/256-32768
    return ((at(x0,y0)*(1-u)+at(x0+1,y0)*u)*(1-v)+(at(x0,y0+1)*(1-u)+at(x0+1,y0+1)*u)*v)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',required=True); p.add_argument('--cache',required=True)
    p.add_argument('--download',action='store_true')
    a=p.parse_args(); index=json.loads((Path(a.sources)/'index.json').read_text())
    paths=audit(index,a.cache); missing=[p for p in paths if not p.exists()]
    print(f'DEM: {len(paths)-len(missing)}/{len(paths)} local; {len(missing)} missing',flush=True)
    if a.download:
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(fetch,missing))
        print('Raw DEM sources ready; no derived data generated.',flush=True)
    elif missing:
        raise SystemExit(1)


if __name__=='__main__':
    main()
