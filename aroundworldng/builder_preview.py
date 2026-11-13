"""AroundWorldNG Procedural Generation Preview:
Dynamic architectural elevation and streetscape rendering reflecting real procedural generation.

Features previewed:
- Selected architectural archetypes (SPB high-rises, historical neoclassical, Soviet panels, brick blocks)
- Procedural windows, glass reflections, balconies, and loggias
- Ground-floor commercial storefronts and entrance groups with canopies
- Roof architecture (parapets, elevator machinery rooms, vents)
- Courtyard infrastructure (street workout bars, playgrounds with sandboxes and slides, gazebos, fences)
- Multi-model parked vehicles (sedan, SUV/crossover, hatchback)
- Road network (real asphalt textures, lane markings, pedestrian zebra crossings, stop lines)
- Pedestrian infrastructure (paved sidewalks, concrete curbs, benches, urns, glass transit stops, streetlamps)
- Water bodies (granite canal embankments with water reflection when the water layer is active)
- Trees and greenery (broadleaf, conifer, mixed, trimmed hedges)

All additions to the generator must be reflected in this preview.
"""
from __future__ import annotations

from functools import lru_cache
import io
import math
from pathlib import Path
import struct
import zipfile

from PIL import Image, ImageDraw, ImageFilter

import fast_style

if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[1]


def decode_image(data):
    # Pillow understands BC1/2/3 UNORM but not their sRGB header variants.
    # Decode those bytes as display RGB by patching the in-memory header.
    if len(data) >= 148 and data[:4] == b'DDS ' and data[84:88] == b'DX10':
        fmt = struct.unpack_from('<I', data, 128)[0]
        if fmt in (72, 75, 78):
            data = data[:128] + struct.pack('<I', fmt-1) + data[132:]
    with Image.open(io.BytesIO(data)) as opened:
        return opened.convert('RGB')


@lru_cache(maxsize=128)
def material(kind, mods):
    """Retrieve material texture from planet archive, local art, game texture, or fallback."""
    mat_key = 'e2rf_' + kind
    spec = fast_style.MATERIALS.get(mat_key, {}).get('Stages', [{}])[0]
    path = spec.get('baseColorMap', '')
    source = None
    image = None

    if path.startswith('/e2r_stream/'):
        relative = path.lstrip('/')
        # Check aroundworldng_planet.zip first, then earthng_planet.zip
        for p_name in ('aroundworldng_planet.zip', 'earthng_planet.zip'):
            planet = Path(mods) / 'mods' / p_name
            try:
                with zipfile.ZipFile(planet) as archive:
                    image = decode_image(archive.read(relative))
                    source = 'installed planet'
                    break
            except Exception:
                pass
        if image is None:
            suffix = relative.split('fast-art/', 1)[-1]
            for folder in ('art-distributable', 'art'):
                local = ROOT / 'data' / folder / suffix
                try:
                    image = decode_image(local.read_bytes())
                    source = 'local art'
                    break
                except Exception:
                    pass
    elif path.startswith('/assets/'):
        import fast_art
        try:
            relative = path.lstrip('/')[:-4] + '.dds'
            for name in ('tileable.zip', 'terrain.zip'):
                archive_path = fast_art.ASSETS / name
                if not archive_path.exists():
                    continue
                with zipfile.ZipFile(archive_path) as archive:
                    if relative in archive.namelist():
                        image = decode_image(archive.read(relative))
                        source = 'game texture'
                        break
        except Exception:
            pass

    if image is None:
        info = fast_style.KINDS.get(kind)
        colour = info[1] if info else [.5, .5, .5, 1]
        image = Image.new('RGB', (96, 96), tuple(round(v * 255) for v in colour[:3]))
        source = 'colour fallback'
    else:
        image.thumbnail((256, 256))
        tint = spec.get('baseColorFactor', [1, 1, 1])
        if tint != [1, 1, 1]:
            channels = image.split()
            image = Image.merge('RGB', [ch.point([min(255, round(v * tint[i])) for v in range(256)])
                                        for i, ch in enumerate(channels)])
    return image, source


def get_archetype_walls(block_id, building_choice):
    """Resolve wall materials and architectural styles for preview buildings."""
    if block_id == 'spb-new':
        return [
            ('wall_pls_d_new', 'wall_pls_d_euro_warm', 'modern_highrise'),
            ('wall_pls_d_tile', 'wall_brk_d_sil', 'modern_comfort'),
            ('wall_pnl_white', 'wall_brk_d_dark', 'modern_mixed'),
        ]
    elif block_id == 'spb-historic':
        return [
            ('wall_pls_d_stalin', 'wall_pls_d_ashlar', 'historic_spb'),
            ('wall_pls_yellow', 'wall_pls_d_stalin_red', 'historic_spb'),
            ('wall_pls_cream', 'wall_pls_d_euro_warm', 'historic_spb'),
        ]
    elif block_id == 'soviet-panel':
        return [
            ('wall_pnl_grey', 'wall_pnl_patch_grey', 'soviet_panel'),
            ('wall_lgg_cream', 'wall_pnl_beige', 'soviet_brezhnevka'),
            ('wall_pnl_beige', 'wall_pnl_white', 'soviet_panel'),
        ]
    elif block_id == 'soviet-brick':
        return [
            ('wall_brk_d_sil', 'wall_brk_d_red', 'soviet_brick'),
            ('wall_brk_d_red', 'wall_brk_d_old', 'soviet_brick'),
            ('wall_lgg_cream', 'wall_brk_d_dark', 'soviet_brick'),
        ]
    else:
        mapping = {
            'panel': [('wall_pnl_grey', 'wall_pnl_patch_grey', 'soviet_panel'),
                      ('wall_lgg_cream', 'wall_pnl_beige', 'soviet_brezhnevka'),
                      ('wall_pnl_white', 'wall_pnl_grey', 'soviet_panel')],
            'brick': [('wall_brk_d_red', 'wall_brk_d_old', 'soviet_brick'),
                      ('wall_brk_d_sil', 'wall_brk_d_red', 'soviet_brick'),
                      ('wall_brk_d_dark', 'wall_brk_d_sil', 'soviet_brick')],
            'plaster': [('wall_pls_d_stalin', 'wall_pls_d_ashlar', 'historic_spb'),
                        ('wall_pls_yellow', 'wall_pls_cream', 'historic_spb'),
                        ('wall_pls_d_euro_warm', 'wall_pls_peach', 'historic_spb')],
            'mixed': [('wall_pls_d_new', 'wall_pls_d_blue', 'modern_highrise'),
                      ('wall_pnl_grey', 'wall_brk_d_red', 'soviet_panel'),
                      ('wall_pls_cream', 'wall_off_blue', 'modern_mixed')],
        }
        return mapping.get(building_choice, mapping['mixed'])


def render(look, include, mods, latitude=50):
    """Render procedural cutaway preview of the active configuration."""
    W, H = 580, 320
    image = Image.new('RGB', (W, H), '#7c96af')
    draw = ImageDraw.Draw(image)
    sources = {}

    block_id = look.get('block', 'general')
    bld_choice = look.get('buildings', 'panel')
    asphalt_choice = look.get('asphalt', 'smooth')
    road_kind = {'smooth': 'road', 'worn': 'road_worn', 'fresh': 'road_major'}.get(asphalt_choice, 'road')
    verge_choice = look.get('verge', 'grass')
    verge_kind = {'grass': 'ground', 'dirt': 'bare_ground', 'dry': 'heath', 'gravel': 'scree'}.get(verge_choice, 'ground')
    markings = look.get('markings', 'white')

    def draw_texture_patch(kind, rect, repeat_x, repeat_y=None):
        if repeat_y is None:
            repeat_y = repeat_x
        texture, source = material(kind, mods)
        sources[kind] = source
        x0, y0, x1, y1 = rect
        pw, ph = max(1, x1 - x0), max(1, y1 - y0)
        patch = Image.new('RGB', (pw, ph))
        tile = texture.resize((repeat_x, repeat_y), Image.Resampling.LANCZOS)
        for tx in range(0, pw, repeat_x):
            for ty in range(0, ph, repeat_y):
                patch.paste(tile, (tx, ty))
        image.paste(patch, (x0, y0))

    # ---------------------------------------------------------
    # 1. Sky & Atmospheric Daylight Gradient
    # ---------------------------------------------------------
    for y in range(0, 180):
        t = y / 180.0
        r = int(108 + (185 - 108) * t)
        g = int(139 + (204 - 139) * t)
        b = int(166 + (221 - 166) * t)
        draw.line((0, y, W, y), fill=(r, g, b))

    # ---------------------------------------------------------
    # 2. Distant Background City Skyline Silhouette
    # ---------------------------------------------------------
    distant_color = (144, 164, 180)
    skyline_pts = [
        (0, 180), (0, 115), (45, 115), (45, 130), (80, 130), (80, 95), (105, 95),
        (105, 140), (140, 140), (160, 105), (185, 105), (185, 135), (250, 135),
        (280, 85), (300, 85), (300, 130), (370, 130), (395, 110), (420, 110),
        (420, 140), (490, 140), (510, 90), (535, 90), (535, 125), (W, 125), (W, 180)
    ]
    draw.polygon(skyline_pts, fill=distant_color)

    # ---------------------------------------------------------
    # 3. Ground / Verge / Yard Base
    # ---------------------------------------------------------
    Y_VERGE = 175
    Y_SIDEWALK = 205
    Y_CURB = 226
    Y_ROAD = 230
    draw_texture_patch(verge_kind, (0, Y_VERGE, W, Y_ROAD), 48)

    # ---------------------------------------------------------
    # 4. Procedural Buildings (if enabled)
    # ---------------------------------------------------------
    bld_archetypes = get_archetype_walls(block_id, bld_choice)
    if include.get('buildings', True):
        # Determine waterfront width if water is enabled
        has_water = bool(include.get('water', True))
        right_bld_max = W - 75 if has_water else W - 15

        buildings_specs = [
            {'rect': (20, 32, 185, Y_VERGE), 'walls': bld_archetypes[0],
             'floors': 12 if 'highrise' in bld_archetypes[0][2] else (5 if 'historic' in bld_archetypes[0][2] else 9)},
            {'rect': (195, 52, 365, Y_VERGE), 'walls': bld_archetypes[1],
             'floors': 10 if 'highrise' in bld_archetypes[1][2] else (4 if 'historic' in bld_archetypes[1][2] else 5)},
            {'rect': (375, 24, right_bld_max, Y_VERGE), 'walls': bld_archetypes[2],
             'floors': 14 if 'highrise' in bld_archetypes[2][2] else (5 if 'historic' in bld_archetypes[2][2] else 9)},
        ]

        for spec_idx, spec in enumerate(buildings_specs):
            bx0, by0, bx1, by1 = spec['rect']
            w_primary, w_accent, b_style = spec['walls']
            bw = bx1 - bx0
            bh = by1 - by0

            # Roof Elevator superstructure & ventilation box
            draw.rectangle((bx0 + 22, by0 - 14, bx0 + 55, by0), fill='#4b5358', outline='#353a3e')
            draw.rectangle((bx1 - 42, by0 - 10, bx1 - 18, by0), fill='#525a60', outline='#353a3e')

            # Base facade texture
            draw_texture_patch(w_primary, (bx0, by0, bx1, by1), 48)

            # Modern ventilated facade vertical accent paneling (comfort-class high-rises)
            if 'modern' in b_style:
                stripe_w = 36
                sx0 = bx0 + 30
                draw_texture_patch(w_accent, (sx0, by0, sx0 + stripe_w, by1 - 30), 48)
                if bw > 130:
                    sx1 = bx1 - 40
                    draw_texture_patch(w_accent, (sx1 - 24, by0, sx1, by1 - 30), 48)

            # Roof parapet trim
            draw.rectangle((bx0 - 2, by0 - 4, bx1 + 2, by0), fill='#3c4246', outline='#282d30')
            # Building edge outline
            draw.rectangle((bx0, by0, bx1, by1), outline='#2e3338', width=1)

            # Ground floor shop / entrance podium
            podium_h = 28
            py0 = by1 - podium_h
            if spec_idx == 0:
                # Left building: Residential entrance + Ground-floor "ПРОДУКТЫ 24" shopfront
                draw.rectangle((bx0, py0, bx1, by1), outline='#3b4045')
                # Porch on the left
                porch_x = bx0 + 12
                draw.rectangle((porch_x, by1 - 22, porch_x + 16, by1), fill='#28292c', outline='#171718')
                draw.rectangle((porch_x - 4, by1 - 24, porch_x + 20, by1 - 21), fill='#50555a')
                draw.rectangle((porch_x + 6, by1 - 26, porch_x + 10, by1 - 24), fill='#fff2b2')
                # Russian "ПРОДУКТЫ 24" shopfront on the right
                sh_x0, sh_x1 = bx0 + 44, bx1 - 8
                draw.rectangle((sh_x0, py0, sh_x1, by1), fill='#1e293b', outline='#334155')
                # Commercial shop glazing & mullions
                draw.rectangle((sh_x0 + 4, py0 + 3, sh_x1 - 4, by1 - 2), fill='#2c4155', outline='#172554')
                draw.line(((sh_x0 + sh_x1) // 2, py0 + 3, (sh_x0 + sh_x1) // 2, by1 - 2), fill='#475569', width=2)
                # Fascia signboard band (Green with white letters)
                draw.rectangle((sh_x0 - 2, py0 - 8, sh_x1 + 2, py0), fill='#14532d', outline='#166534')
                draw.rectangle((sh_x0 - 2, py0 - 1, sh_x1 + 2, py0), fill='#22c55e')
                # Lettering "ПРОДУКТЫ 24" (pixel glyphs)
                draw.text((sh_x0 + 10, py0 - 8), "ПРОДУКТЫ  24", fill='#f8fafc')
            elif spec_idx == 1:
                # Middle building: Ground-floor "ВКУСНО — И ТОЧКА" / Fast-Food Cafe
                sh_x0, sh_x1 = bx0 + 16, bx1 - 16
                draw.rectangle((sh_x0, py0, sh_x1, by1), fill='#1e293b', outline='#334155')
                draw.rectangle((sh_x0 + 4, py0 + 4, sh_x1 - 4, by1 - 2), fill='#334155', outline='#0f172a')
                draw.line(((sh_x0 + sh_x1) // 2, py0 + 4, (sh_x0 + sh_x1) // 2, by1 - 2), fill='#475569', width=2)
                # Warm indoor illumination
                draw.rectangle((sh_x0 + 6, py0 + 6, (sh_x0 + sh_x1) // 2 - 2, by1 - 4), fill='#475569')
                # Fascia signboard band: Dark forest green with warm orange bottom stripe
                draw.rectangle((sh_x0 - 2, py0 - 9, sh_x1 + 2, py0), fill='#1c3726', outline='#0f2417')
                draw.rectangle((sh_x0 - 2, py0 - 2, sh_x1 + 2, py0), fill='#ea580c')
                # Brand logo / name: "ВКУСНО — И ТОЧКА"
                draw.text((sh_x0 + 14, py0 - 9), "ВКУСНО — И ТОЧКА", fill='#fef08a')
            elif 'modern' in b_style or 'historic' in b_style:
                draw_texture_patch('wall_off_blue' if 'modern' in b_style else 'wall_shop_dark', (bx0, py0, bx1, by1), 40)
                draw.rectangle((bx0, py0 - 4, bx1, py0), fill='#2b3137')
                for sx in range(bx0 + 20, bx1 - 15, 42):
                    draw.line((sx, py0, sx, by1), fill='#1a1d20', width=2)
            else:
                draw.rectangle((bx0, py0, bx1, by1), outline='#3b4045')
                porch_x = bx0 + bw // 2 - 12
                draw.rectangle((porch_x, by1 - 22, porch_x + 16, by1), fill='#28292c', outline='#171718')
                draw.rectangle((porch_x - 4, by1 - 24, porch_x + 20, by1 - 21), fill='#50555a')
                draw.rectangle((porch_x + 6, by1 - 26, porch_x + 10, by1 - 24), fill='#fff2b2')

            # Windows & Balconies
            cols = max(3, bw // 26)
            col_step = bw / cols
            row_h = (bh - podium_h - 10) / (spec['floors'] - 1)
            row_h = max(11, min(18, row_h))

            balcony_col = 1 if cols >= 4 else -1
            cur_y = by0 + 10

            while cur_y < by1 - podium_h - 8:
                for c in range(cols):
                    wx0 = int(bx0 + c * col_step + 4)
                    wx1 = int(wx0 + col_step - 8)
                    wy0 = int(cur_y)
                    wy1 = int(cur_y + row_h - 4)

                    if c == balcony_col and ('modern' in b_style or 'soviet' in b_style):
                        # Balcony unit
                        draw.rectangle((wx0 - 2, wy1 - 1, wx1 + 2, wy1 + 1), fill='#6b7278')
                        if 'modern' in b_style:
                            # Full panoramic glass balcony with reflections
                            draw.rectangle((wx0 - 2, wy0 - 1, wx1 + 2, wy1), fill='#3d627a', outline='#2b4556')
                            draw.line((wx0 + 1, wy0 + 2, wx1 - 3, wy1 - 2), fill='#6794b2', width=1)
                            draw.line((wx0 - 2, wy0 + (wy1 - wy0) // 2, wx1 + 2, wy0 + (wy1 - wy0) // 2), fill='#2b4556', width=1)
                        else:
                            # Soviet panel / corrugated balustrade
                            draw.rectangle((wx0, wy0, wx1, wy1 - 5), fill='#384c59', outline='#242e35')
                            draw.rectangle((wx0 - 2, wy1 - 6, wx1 + 2, wy1), fill='#7a8288', outline='#4a5055')
                    else:
                        # Regular window
                        frame_color = '#25292c' if 'modern' in b_style else ('#8c9298' if 'soviet' in b_style else '#4a3d32')
                        draw.rectangle((wx0, wy0, wx1, wy1), fill=frame_color)
                        glass_color = '#385166' if (c + int(cur_y)) % 7 != 0 else '#4d6980'
                        draw.rectangle((wx0 + 1, wy0 + 1, wx1 - 1, wy1 - 1), fill=glass_color)
                        mw = (wx0 + wx1) // 2
                        draw.line((mw, wy0 + 1, mw, wy1 - 1), fill=frame_color, width=1)
                        if wy1 - wy0 > 13:
                            draw.line((wx0 + 1, wy0 + 4, wx1 - 1, wy0 + 4), fill=frame_color, width=1)
                        draw.line((wx0 - 1, wy1, wx1 + 1, wy1), fill='#d8dce0', width=1)

                        # Window AC unit under some windows
                        if cur_y < by1 - podium_h - 18 and (c * 7 + int(cur_y)) % 11 == 0:
                            ac_x0 = wx0 + (wx1 - wx0) // 2 - 4
                            ac_y0 = wy1 + 1
                            draw.rectangle((ac_x0, ac_y0, ac_x0 + 8, ac_y0 + 5), fill='#e6eaed', outline='#8a949e')
                            draw.line((ac_x0 + 5, ac_y0 + 1, ac_x0 + 5, ac_y0 + 4), fill='#4a525a', width=1)

                        if 'historic' in b_style and (int(cur_y - by0) // int(row_h)) % 2 == 0:
                            draw.polygon([(wx0 - 2, wy0 - 1), (mw, wy0 - 4), (wx1 + 2, wy0 - 1)], fill='#e2dbca')

                cur_y += row_h

            # Downpipes at corners for soviet / historic buildings
            if 'soviet' in b_style or 'historic' in b_style:
                pipe_x = bx0 + 2
                draw.line((pipe_x, by0 + 8, pipe_x, by1 - 4), fill='#6b757d', width=2)
                draw.polygon([(pipe_x - 2, by0 + 6), (pipe_x + 2, by0 + 6), (pipe_x, by0 + 9)], fill='#50575d')

            # Real address plate (blue plate with white frame)
            plate_x = bx0 + 6
            plate_y = by1 - podium_h - 14
            draw.rectangle((plate_x, plate_y, plate_x + 14, plate_y + 8), fill='#1b3a5c', outline='#ffffff')
            draw.line((plate_x + 2, plate_y + 2, plate_x + 12, plate_y + 2), fill='#ffffff', width=1)
            draw.line((plate_x + 4, plate_y + 5, plate_x + 10, plate_y + 5), fill='#ffffff', width=1)

    # ---------------------------------------------------------
    # 5. Courtyard Infrastructure & Props (when cover is enabled)
    # ---------------------------------------------------------
    if include.get('cover', True):
        # A) Street Workout Zone (pull-up bars + parallel dip bars)
        wo_x = 38
        draw.line((wo_x, Y_SIDEWALK, wo_x, Y_SIDEWALK - 24), fill='#23272a', width=2)
        draw.line((wo_x + 15, Y_SIDEWALK, wo_x + 15, Y_SIDEWALK - 28), fill='#23272a', width=2)
        draw.line((wo_x + 30, Y_SIDEWALK, wo_x + 30, Y_SIDEWALK - 32), fill='#23272a', width=2)
        draw.line((wo_x, Y_SIDEWALK - 23, wo_x + 15, Y_SIDEWALK - 23), fill='#d23434', width=2)
        draw.line((wo_x + 15, Y_SIDEWALK - 27, wo_x + 30, Y_SIDEWALK - 27), fill='#d23434', width=2)

        dp_x = wo_x + 38
        draw.line((dp_x, Y_SIDEWALK, dp_x, Y_SIDEWALK - 16), fill='#23272a', width=2)
        draw.line((dp_x + 13, Y_SIDEWALK, dp_x + 13, Y_SIDEWALK - 16), fill='#23272a', width=2)
        draw.line((dp_x, Y_SIDEWALK - 15, dp_x + 13, Y_SIDEWALK - 15), fill='#e6af2e', width=2)

        # B) Children's Playground (sandbox with 4-slope canopy + slide)
        sb_x = 112
        draw.rectangle((sb_x, Y_SIDEWALK - 5, sb_x + 26, Y_SIDEWALK), fill='#d4be88', outline='#bf503b')
        draw.line((sb_x + 13, Y_SIDEWALK - 5, sb_x + 13, Y_SIDEWALK - 22), fill='#454f55', width=2)
        draw.polygon([(sb_x + 13, Y_SIDEWALK - 26), (sb_x + 1, Y_SIDEWALK - 20), (sb_x + 25, Y_SIDEWALK - 20)], fill='#d93829')

        sl_x = 150
        draw.line((sl_x, Y_SIDEWALK, sl_x, Y_SIDEWALK - 22), fill='#2b6cb0', width=2)
        draw.line((sl_x, Y_SIDEWALK - 22, sl_x + 18, Y_SIDEWALK - 4), fill='#ecc94b', width=3)

        # C) Yard Gazebo / Pavilion (Беседка)
        gz_x = 188
        draw.line((gz_x + 4, Y_SIDEWALK, gz_x + 4, Y_SIDEWALK - 20), fill='#5c4033', width=2)
        draw.line((gz_x + 24, Y_SIDEWALK, gz_x + 24, Y_SIDEWALK - 20), fill='#5c4033', width=2)
        draw.polygon([(gz_x + 14, Y_SIDEWALK - 28), (gz_x, Y_SIDEWALK - 20), (gz_x + 28, Y_SIDEWALK - 20)], fill='#7c2d12', outline='#451a03')
        draw.line((gz_x + 6, Y_SIDEWALK - 7, gz_x + 22, Y_SIDEWALK - 7), fill='#854d0e', width=2)

        # D) Carpet Beater & Clothes Airer (Выбивалка для ковров)
        cb_x = 224
        draw.line((cb_x, Y_SIDEWALK, cb_x, Y_SIDEWALK - 20), fill='#2563eb', width=2)
        draw.line((cb_x + 14, Y_SIDEWALK, cb_x + 14, Y_SIDEWALK - 20), fill='#2563eb', width=2)
        draw.line((cb_x, Y_SIDEWALK - 20, cb_x + 14, Y_SIDEWALK - 20), fill='#2563eb', width=2)
        draw.line((cb_x, Y_SIDEWALK - 10, cb_x + 14, Y_SIDEWALK - 10), fill='#2563eb', width=1)

        # E) Courtyard Transformer Substation (Трансформаторная будка ТП)
        tp_x = 246
        draw.rectangle((tp_x, Y_SIDEWALK - 24, tp_x + 26, Y_SIDEWALK), fill='#d1d5db', outline='#4b5563')
        draw.rectangle((tp_x - 2, Y_SIDEWALK - 26, tp_x + 28, Y_SIDEWALK - 23), fill='#374151')
        draw.rectangle((tp_x + 6, Y_SIDEWALK - 18, tp_x + 20, Y_SIDEWALK), fill='#1f2937', outline='#111827')
        draw.polygon([(tp_x + 13, Y_SIDEWALK - 15), (tp_x + 11, Y_SIDEWALK - 12), (tp_x + 15, Y_SIDEWALK - 12)], fill='#facc15')

        # F) Russian Metal Garage Box (Гараж-ракушка / пенал)
        gb_x = 280
        draw.rectangle((gb_x, Y_SIDEWALK - 22, gb_x + 30, Y_SIDEWALK), fill='#6b7280', outline='#374151')
        draw.polygon([(gb_x - 2, Y_SIDEWALK - 22), (gb_x + 15, Y_SIDEWALK - 26), (gb_x + 32, Y_SIDEWALK - 22)], fill='#4b5563')
        draw.rectangle((gb_x + 2, Y_SIDEWALK - 19, gb_x + 14, Y_SIDEWALK), fill='#1d4ed8', outline='#1e3a8a')
        draw.rectangle((gb_x + 16, Y_SIDEWALK - 19, gb_x + 28, Y_SIDEWALK), fill='#1d4ed8', outline='#1e3a8a')
        draw.rectangle((gb_x + 14, Y_SIDEWALK - 10, gb_x + 16, Y_SIDEWALK - 8), fill='#facc15')
        draw.rectangle((gb_x - 1, Y_SIDEWALK - 20, gb_x + 31, Y_SIDEWALK - 18), fill='#374151')

    # ---------------------------------------------------------
    # 6. Barriers & Fences (when barriers is enabled)
    # ---------------------------------------------------------
    if include.get('barriers', True):
        f_x = 236
        draw_texture_patch('fence_wall', (f_x, Y_SIDEWALK - 18, f_x + 45, Y_SIDEWALK), 22)
        draw.rectangle((f_x, Y_SIDEWALK - 18, f_x + 45, Y_SIDEWALK), outline='#4a4f54')

    # ---------------------------------------------------------
    # 7. Bus Stop Transit Shelter (when stops and statics enabled)
    # ---------------------------------------------------------
    if look.get('statics') != 'none' and include.get('stops', True):
        bs_x = 295
        draw.rectangle((bs_x, Y_SIDEWALK - 26, bs_x + 38, Y_SIDEWALK), outline='#333d45', width=2)
        draw.rectangle((bs_x + 1, Y_SIDEWALK - 25, bs_x + 37, Y_SIDEWALK - 1), fill='#6b8da6')
        draw.rectangle((bs_x - 3, Y_SIDEWALK - 29, bs_x + 41, Y_SIDEWALK - 25), fill='#232a30')
        draw.line((bs_x + 6, Y_SIDEWALK - 9, bs_x + 32, Y_SIDEWALK - 9), fill='#a16207', width=2)
        draw.rectangle((bs_x + 30, Y_SIDEWALK - 22, bs_x + 36, Y_SIDEWALK - 14), fill='#ffffff', outline='#0f172a')

    # ---------------------------------------------------------
    # 8. Trees & Greenery (when treeRows or cover enabled)
    # ---------------------------------------------------------
    if include.get('treeRows', True) or include.get('cover', True):
        tree_choice = look.get('trees', 'regional')
        is_conifer = (tree_choice == 'conifer') or (tree_choice == 'regional' and abs(latitude) > 58)
        tree_positions = [80, 185, 350, 485]
        for idx, tx in enumerate(tree_positions):
            draw.line((tx, Y_SIDEWALK, tx, Y_SIDEWALK - 36), fill='#423528', width=3)
            if is_conifer or (tree_choice == 'mixed' and idx % 2):
                draw.polygon([(tx, Y_SIDEWALK - 68), (tx - 16, Y_SIDEWALK - 28), (tx + 16, Y_SIDEWALK - 28)], fill='#23422e')
                draw.polygon([(tx, Y_SIDEWALK - 60), (tx - 12, Y_SIDEWALK - 24), (tx + 12, Y_SIDEWALK - 24)], fill='#2c5339')
            else:
                draw.ellipse((tx - 20, Y_SIDEWALK - 64, tx + 20, Y_SIDEWALK - 26), fill='#3c6332')
                draw.ellipse((tx - 16, Y_SIDEWALK - 60, tx + 16, Y_SIDEWALK - 30), fill='#4a7c3e')

        for bx in (25, 68, 142, 280, 440):
            draw.ellipse((bx - 8, Y_SIDEWALK - 10, bx + 8, Y_SIDEWALK), fill='#466b37')

    # ---------------------------------------------------------
    # 9. Water Body / Canal Embankment (when water is enabled)
    # ---------------------------------------------------------
    if include.get('water', True):
        water_x0 = W - 68
        # Granite stone retaining wall
        draw_texture_patch('wall_pls_d_ashlar', (water_x0, Y_VERGE - 10, water_x0 + 12, Y_ROAD), 24)
        draw.rectangle((water_x0, Y_VERGE - 10, water_x0 + 12, Y_ROAD), outline='#3a3d42')
        # Embankment wrought-iron railing
        draw.line((water_x0, Y_VERGE - 18, water_x0 + 12, Y_VERGE - 18), fill='#18181b', width=2)
        draw.line((water_x0 + 6, Y_VERGE - 18, water_x0 + 6, Y_VERGE - 10), fill='#18181b', width=2)
        # Water surface
        draw.rectangle((water_x0 + 12, Y_VERGE, W, H), fill='#2b506e')
        # Water ripples / sky reflection highlights
        for wy in range(Y_VERGE + 12, H, 14):
            draw.line((water_x0 + 16, wy, W - 6, wy), fill='#48769c', width=2)
            draw.line((water_x0 + 26, wy + 4, W - 14, wy + 4), fill='#73a4cc', width=1)

    # ---------------------------------------------------------
    # 10. Paved Sidewalk & Curbs
    # ---------------------------------------------------------
    sidewalk_w = W - 68 if include.get('water', True) else W
    draw_texture_patch('sidewalk', (0, Y_SIDEWALK, sidewalk_w, Y_CURB), 32)
    draw_texture_patch('curb', (0, Y_CURB, sidewalk_w, Y_ROAD), 16)
    draw.line((0, Y_CURB, sidewalk_w, Y_CURB), fill='#8f9499', width=1)
    draw.line((0, Y_ROAD, sidewalk_w, Y_ROAD), fill='#3b3d40', width=1)

    # Sidewalk Furniture (bench & litter urn)
    bench_x = 405
    draw.line((bench_x, Y_CURB - 4, bench_x + 22, Y_CURB - 4), fill='#854d0e', width=2)
    draw.line((bench_x + 2, Y_CURB - 1, bench_x + 2, Y_CURB - 8), fill='#27272a', width=2)
    draw.line((bench_x + 20, Y_CURB - 1, bench_x + 20, Y_CURB - 8), fill='#27272a', width=2)
    draw.rectangle((bench_x + 27, Y_CURB - 8, bench_x + 33, Y_CURB - 1), fill='#52525b', outline='#27272a')

    # Street Lighting Posts (when statics == 'street')
    if look.get('statics') == 'street':
        for lx in (255, 395):
            if block_id == 'spb-historic':
                draw.line((lx, Y_CURB, lx, Y_SIDEWALK - 45), fill='#1e2225', width=3)
                draw.line((lx - 5, Y_SIDEWALK - 45, lx + 5, Y_SIDEWALK - 45), fill='#1e2225', width=2)
                draw.polygon([(lx - 4, Y_SIDEWALK - 52), (lx + 4, Y_SIDEWALK - 52),
                              (lx + 2, Y_SIDEWALK - 45), (lx - 2, Y_SIDEWALK - 45)],
                             fill='#fff4cc', outline='#1e2225')
            else:
                draw.line((lx, Y_CURB, lx, Y_SIDEWALK - 52), fill='#3a4248', width=3)
                draw.line((lx, Y_SIDEWALK - 52, lx + 14, Y_SIDEWALK - 55), fill='#3a4248', width=2)
                draw.rectangle((lx + 9, Y_SIDEWALK - 56, lx + 16, Y_SIDEWALK - 53), fill='#fffae0')

    # ---------------------------------------------------------
    # 11. Roadway & Asphalt
    # ---------------------------------------------------------
    draw_texture_patch(road_kind, (0, Y_ROAD, sidewalk_w, H), 64)

    # ---------------------------------------------------------
    # 12. Road Markings (markings slot)
    # ---------------------------------------------------------
    if markings != 'none':
        mark_color = '#facc15' if markings == 'yellow' else '#f1f5f9'
        line_y = Y_ROAD + 48
        for x in range(0, sidewalk_w, 48):
            draw.rectangle((x, line_y, x + 24, line_y + 2), fill=mark_color)

        cross_x0 = 435
        cross_x1 = min(sidewalk_w - 10, 495)
        draw.rectangle((cross_x0 - 6, Y_ROAD + 4, cross_x0 - 4, H - 4), fill=mark_color)
        stripe_idx = 0
        for zx in range(cross_x0, cross_x1, 10):
            stripe_col = '#eab308' if (stripe_idx % 2 == 1) else mark_color
            draw.rectangle((zx, Y_ROAD + 4, zx + 5, H - 4), fill=stripe_col)
            stripe_idx += 1

    # ---------------------------------------------------------
    # 13. Parked Multi-Body Vehicles (Lada, GAZelle, SUV, Hatch)
    # ---------------------------------------------------------
    def draw_car(cx, cy, body_type, body_color):
        wheel_r = 7
        draw.ellipse((cx + 10, cy + 10, cx + 10 + wheel_r * 2, cy + 10 + wheel_r * 2), fill='#18181b')
        draw.ellipse((cx + 13, cy + 13, cx + 10 + wheel_r * 2 - 3, cy + 10 + wheel_r * 2 - 3), fill='#a1a1aa')
        draw.ellipse((cx + 52, cy + 10, cx + 52 + wheel_r * 2, cy + 10 + wheel_r * 2), fill='#18181b')
        draw.ellipse((cx + 55, cy + 13, cx + 52 + wheel_r * 2 - 3, cy + 10 + wheel_r * 2 - 3), fill='#a1a1aa')

        if body_type == 'lada':
            # Classic Soviet/Russian 3-box sedan (VAZ 2105/2107 / Zhiguli)
            body_poly = [
                (cx, cy + 11), (cx + 17, cy + 11), (cx + 23, cy + 2),
                (cx + 47, cy + 2), (cx + 53, cy + 10), (cx + 69, cy + 10),
                (cx + 69, cy + 16), (cx, cy + 16)
            ]
            draw.polygon(body_poly, fill=body_color, outline='#0f172a')
            draw.polygon([(cx + 24, cy + 4), (cx + 46, cy + 4), (cx + 51, cy + 10), (cx + 20, cy + 10)], fill='#385268')
            draw.line((cx + 35, cy + 4, cx + 35, cy + 10), fill='#1e293b', width=1)
            draw.rectangle((cx - 1, cy + 14, cx + 2, cy + 16), fill='#475569')
            draw.rectangle((cx + 67, cy + 14, cx + 70, cy + 16), fill='#475569')
            draw.rectangle((cx, cy + 11, cx + 2, cy + 14), fill='#fef08a')
            draw.rectangle((cx, cy + 11, cx + 1, cy + 12), fill='#f97316')
            draw.rectangle((cx + 67, cy + 10, cx + 69, cy + 13), fill='#dc2626')
        elif body_type == 'gazel':
            # Russian commercial light truck / van (GAZelle 3302)
            cab_poly = [
                (cx, cy + 13), (cx + 11, cy + 12), (cx + 18, cy + 2),
                (cx + 34, cy + 2), (cx + 34, cy + 16), (cx, cy + 16)
            ]
            draw.polygon(cab_poly, fill=body_color, outline='#0f172a')
            draw.polygon([(cx + 14, cy + 4), (cx + 31, cy + 4), (cx + 31, cy + 11), (cx + 12, cy + 11)], fill='#2b3d4f')
            draw.line((cx + 22, cy + 4, cx + 22, cy + 11), fill='#1e293b', width=1)
            draw.rectangle((cx - 1, cy + 14, cx + 3, cy + 16), fill='#334155')
            draw.rectangle((cx, cy + 12, cx + 2, cy + 14), fill='#fef08a')
            cargo_box = [(cx + 35, cy - 6), (cx + 74, cy - 6), (cx + 74, cy + 16), (cx + 35, cy + 16)]
            draw.polygon(cargo_box, fill='#64748b', outline='#1e293b')
            draw.line((cx + 48, cy - 5, cx + 48, cy + 15), fill='#475569', width=1)
            draw.line((cx + 61, cy - 5, cx + 61, cy + 15), fill='#475569', width=1)
            draw.rectangle((cx + 72, cy + 12, cx + 74, cy + 15), fill='#dc2626')
            draw.rectangle((cx + 70, cy + 16, cx + 74, cy + 19), fill='#0f172a')
        elif body_type == 'sedan':
            body_poly = [
                (cx, cy + 12), (cx + 18, cy + 12), (cx + 25, cy + 2),
                (cx + 48, cy + 2), (cx + 56, cy + 10), (cx + 72, cy + 10),
                (cx + 72, cy + 16), (cx, cy + 16)
            ]
            draw.polygon(body_poly, fill=body_color, outline='#0f172a')
            draw.polygon([(cx + 27, cy + 4), (cx + 47, cy + 4), (cx + 53, cy + 10), (cx + 23, cy + 10)], fill='#385268')
            draw.line((cx + 37, cy + 4, cx + 37, cy + 10), fill=body_color, width=1)
            draw.rectangle((cx, cy + 11, cx + 2, cy + 14), fill='#fef08a')
            draw.rectangle((cx + 70, cy + 10, cx + 72, cy + 13), fill='#ef4444')
        elif body_type == 'suv':
            body_poly = [
                (cx, cy + 13), (cx + 16, cy + 13), (cx + 23, cy),
                (cx + 58, cy), (cx + 68, cy + 8), (cx + 72, cy + 11),
                (cx + 72, cy + 17), (cx, cy + 17)
            ]
            draw.polygon(body_poly, fill=body_color, outline='#0f172a')
            draw.line((cx + 24, cy - 2, cx + 58, cy - 2), fill='#27272a', width=1)
            draw.polygon([(cx + 24, cy + 2), (cx + 56, cy + 2), (cx + 64, cy + 9), (cx + 20, cy + 9)], fill='#2b3d4f')
            draw.line((cx + 40, cy + 2, cx + 40, cy + 9), fill=body_color, width=1)
            draw.rectangle((cx, cy + 12, cx + 3, cy + 15), fill='#fef08a')
            draw.rectangle((cx + 70, cy + 11, cx + 72, cy + 14), fill='#ef4444')
        elif body_type == 'hatch':
            body_poly = [
                (cx, cy + 13), (cx + 15, cy + 13), (cx + 24, cy + 3),
                (cx + 50, cy + 3), (cx + 62, cy + 11), (cx + 65, cy + 16),
                (cx, cy + 16)
            ]
            draw.polygon(body_poly, fill=body_color, outline='#0f172a')
            draw.polygon([(cx + 26, cy + 5), (cx + 49, cy + 5), (cx + 58, cy + 11), (cx + 22, cy + 11)], fill='#385268')
            draw.line((cx + 38, cy + 5, cx + 38, cy + 11), fill=body_color, width=1)
            draw.rectangle((cx, cy + 12, cx + 2, cy + 14), fill='#fef08a')
            draw.rectangle((cx + 63, cy + 11, cx + 65, cy + 13), fill='#ef4444')

    draw_car(30, Y_ROAD + 6, 'lada', '#e2e8f0')
    draw_car(120, Y_ROAD + 4, 'gazel', '#f8fafc')
    draw_car(230, Y_ROAD + 8, 'suv', '#334155')
    draw_car(335, Y_ROAD + 6, 'hatch', '#991b1b')

    return image, sources
