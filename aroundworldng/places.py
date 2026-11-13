"""Geofabrik extracts: any country or subregion, without a planet-sized local dump.

The index is https://download.geofabrik.de/index-v1-nogeom.json (names, parents, PBF
urls). It is cached under data/geofabrik, which is not part of the mod the player drives.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import urllib.request

import tls


INDEX_URL = 'https://download.geofabrik.de/index-v1-nogeom.json'
USER_AGENT = 'EarthNG/0.4 (country setup)'
SLUG = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?\Z')


def cache_path(root):
    return Path(root) / 'data' / 'geofabrik' / 'index-v1-nogeom.json'


def parse_index(payload):
    """[{id, name, parent, pbf}] for every extract that publishes a PBF."""
    features = payload.get('features') if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError('Geofabrik index has no features')
    places = []
    for feature in features:
        prop = feature.get('properties') if isinstance(feature, dict) else None
        if not isinstance(prop, dict):
            continue
        place_id, name = prop.get('id'), prop.get('name')
        pbf = (prop.get('urls') or {}).get('pbf') if isinstance(prop.get('urls'), dict) else None
        if not isinstance(place_id, str) or not isinstance(name, str) or not isinstance(pbf, str):
            continue
        if not pbf.startswith('https://download.geofabrik.de/'):
            continue
        places.append({'id': place_id, 'name': name, 'parent': prop.get('parent') or '', 'pbf': pbf})
    if not places:
        raise ValueError('Geofabrik index has no PBF extracts')
    return places


def by_id(places):
    return {place['id']: place for place in places}


def load_cached(root):
    path = cache_path(root)
    if not path.exists():
        return None
    return parse_index(json.loads(path.read_text(encoding='utf-8')))


def fetch_index(root, emit=print):
    """Download the index and cache it. Returns the parsed places."""
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    emit(f'Geofabrik index: {INDEX_URL}')
    request = urllib.request.Request(INDEX_URL, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60, context=tls.context()) as response:
        payload = response.read()
    places = parse_index(json.loads(payload.decode('utf-8')))
    temporary = path.with_suffix('.json.part')
    temporary.write_bytes(payload)
    temporary.replace(path)
    emit(f'{len(places)} regions in {path}')
    return places


CUSTOM_REGIONS = [
    {
        'id': 'russia/saint-petersburg',
        'name': 'Saint Petersburg (Санкт-Петербург)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [29.70, 59.70, 30.75, 60.25],
    },
    {
        'id': 'russia/leningrad-oblast',
        'name': 'Leningrad Oblast (Ленинградская область и СПб)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [27.80, 58.50, 35.50, 61.30],
    },
    {
        'id': 'russia/moscow',
        'name': 'Moscow (Москва)',
        'parent': 'russia',
        'pbf_id': 'central-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf',
        'box': [36.80, 55.10, 38.00, 56.10],
    },
    {
        'id': 'russia/moscow-oblast',
        'name': 'Moscow Oblast (Московская область и Москва)',
        'parent': 'russia',
        'pbf_id': 'central-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf',
        'box': [35.10, 54.20, 40.20, 56.90],
    },
    {
        'id': 'russia/krasnodar',
        'name': 'Krasnodar Krai & Sochi (Краснодарский край и Сочи)',
        'parent': 'russia',
        'pbf_id': 'south-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/south-fed-district-latest.osm.pbf',
        'box': [36.50, 43.35, 41.80, 46.90],
    },
    {
        'id': 'russia/tatarstan',
        'name': 'Tatarstan / Kazan (Республика Татарстан, Казань)',
        'parent': 'russia',
        'pbf_id': 'volga-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/volga-fed-district-latest.osm.pbf',
        'box': [47.20, 53.90, 54.40, 56.70],
    },
    {
        'id': 'russia/sverdlovsk',
        'name': 'Sverdlovsk Oblast / Yekaterinburg (Екатеринбург)',
        'parent': 'russia',
        'pbf_id': 'ural-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/ural-fed-district-latest.osm.pbf',
        'box': [57.20, 56.00, 66.20, 62.00],
    },
    {
        'id': 'russia/novosibirsk',
        'name': 'Novosibirsk Oblast (Новосибирская область)',
        'parent': 'russia',
        'pbf_id': 'siberian-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/siberian-fed-district-latest.osm.pbf',
        'box': [75.30, 53.70, 85.00, 57.20],
    },
    {
        'id': 'russia/nizhny-novgorod',
        'name': 'Nizhny Novgorod Oblast (Нижегородская область)',
        'parent': 'russia',
        'pbf_id': 'volga-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/volga-fed-district-latest.osm.pbf',
        'box': [41.80, 54.40, 47.80, 57.80],
    },
    {
        'id': 'russia/samara',
        'name': 'Samara Oblast (Самарская область)',
        'parent': 'russia',
        'pbf_id': 'volga-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/volga-fed-district-latest.osm.pbf',
        'box': [47.90, 52.00, 52.60, 54.80],
    },
    {
        'id': 'russia/rostov',
        'name': 'Rostov Oblast (Ростовская область)',
        'parent': 'russia',
        'pbf_id': 'south-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/south-fed-district-latest.osm.pbf',
        'box': [38.10, 45.80, 44.40, 50.30],
    },
    {
        'id': 'russia/kaliningrad-region',
        'name': 'Kaliningrad Oblast (Калининградская область)',
        'parent': 'russia',
        'pbf_id': 'kaliningrad',
        'pbf': 'https://download.geofabrik.de/russia/kaliningrad-latest.osm.pbf',
        'box': [19.60, 54.30, 22.90, 55.35],
    },
    {
        'id': 'russia/crimea',
        'name': 'Crimea / Sevastopol (Крым и Севастополь)',
        'parent': 'russia',
        'pbf_id': 'crimean-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/crimean-fed-district-latest.osm.pbf',
        'box': [32.40, 44.35, 36.70, 46.30],
    },
    {
        'id': 'russia/primorsky',
        'name': 'Primorsky Krai / Vladivostok (Владивосток)',
        'parent': 'russia',
        'pbf_id': 'far-eastern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/far-eastern-fed-district-latest.osm.pbf',
        'box': [130.40, 42.30, 139.10, 48.50],
    },
    {
        'id': 'russia/karelia',
        'name': 'Republic of Karelia (Карелия, Петрозаводск)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [29.50, 60.80, 38.00, 66.70],
    },
    {
        'id': 'russia/irkutsk',
        'name': 'Irkutsk Oblast / Baikal (Иркутск, Байкал)',
        'parent': 'russia',
        'pbf_id': 'siberian-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/siberian-fed-district-latest.osm.pbf',
        'box': [95.50, 51.20, 109.50, 64.50],
    },
    {
        'id': 'russia/murmansk',
        'name': 'Murmansk Oblast (Мурманская область)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [28.50, 66.00, 41.50, 69.90],
    },
    {
        'id': 'russia/arkhangelsk',
        'name': 'Arkhangelsk Oblast (Архангельская обл., материк)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [36.50, 60.80, 50.50, 66.80],
    },
    {
        'id': 'russia/pskov',
        'name': 'Pskov Oblast (Псковская область)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [27.30, 55.50, 31.50, 59.00],
    },
    {
        'id': 'russia/novgorod',
        'name': 'Novgorod Oblast (Новгородская область)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [29.50, 57.00, 36.00, 59.50],
    },
    {
        'id': 'russia/vologda',
        'name': 'Vologda Oblast (Вологодская область)',
        'parent': 'russia',
        'pbf_id': 'northwestern-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf',
        'box': [34.50, 58.50, 47.00, 61.50],
    },
    {
        'id': 'russia/voronezh',
        'name': 'Voronezh Oblast (Воронежская область)',
        'parent': 'russia',
        'pbf_id': 'central-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf',
        'box': [38.10, 49.50, 43.10, 52.10],
    },
    {
        'id': 'russia/volgograd',
        'name': 'Volgograd Oblast (Волгоградская область)',
        'parent': 'russia',
        'pbf_id': 'south-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/south-fed-district-latest.osm.pbf',
        'box': [41.10, 47.70, 47.50, 51.30],
    },
    {
        'id': 'russia/bashkortostan',
        'name': 'Bashkortostan / Ufa (Башкортостан, Уфа)',
        'parent': 'russia',
        'pbf_id': 'volga-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/volga-fed-district-latest.osm.pbf',
        'box': [53.10, 51.50, 60.00, 56.60],
    },
    {
        'id': 'russia/perm',
        'name': 'Perm Krai (Пермский край)',
        'parent': 'russia',
        'pbf_id': 'volga-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/volga-fed-district-latest.osm.pbf',
        'box': [51.80, 56.10, 59.70, 61.70],
    },
    {
        'id': 'russia/chelyabinsk',
        'name': 'Chelyabinsk Oblast (Челябинская область)',
        'parent': 'russia',
        'pbf_id': 'ural-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/ural-fed-district-latest.osm.pbf',
        'box': [57.00, 52.00, 63.50, 56.40],
    },
    {
        'id': 'russia/tyumen',
        'name': 'Tyumen Oblast (Тюменская область)',
        'parent': 'russia',
        'pbf_id': 'ural-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/ural-fed-district-latest.osm.pbf',
        'box': [65.00, 55.00, 72.00, 60.00],
    },
    {
        'id': 'russia/krasnoyarsk',
        'name': 'Krasnoyarsk Krai (Красноярский край, Юг/Центр)',
        'parent': 'russia',
        'pbf_id': 'siberian-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/siberian-fed-district-latest.osm.pbf',
        'box': [88.00, 52.00, 96.00, 58.50],
    },
    {
        'id': 'russia/stavropol',
        'name': 'Stavropol Krai / KMV (Ставропольский край, КМВ)',
        'parent': 'russia',
        'pbf_id': 'north-caucasus-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/north-caucasus-fed-district-latest.osm.pbf',
        'box': [40.80, 43.60, 45.80, 46.20],
    },
    {
        'id': 'russia/yaroslavl',
        'name': 'Yaroslavl Oblast (Ярославская область)',
        'parent': 'russia',
        'pbf_id': 'central-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf',
        'box': [37.20, 56.80, 41.20, 58.80],
    },
    {
        'id': 'russia/tver',
        'name': 'Tver Oblast (Тверская область)',
        'parent': 'russia',
        'pbf_id': 'central-fed-district',
        'pbf': 'https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf',
        'box': [30.80, 55.80, 38.00, 58.90],
    },
]


def load_index(root, refresh=False, emit=print):
    try:
        cached = load_cached(root)
    except (OSError, ValueError) as exc:
        cached = None
        emit(f'Could not read cached region list: {exc}. Fetching a new copy.')
    if cached and not refresh:
        places = list(cached)
    else:
        try:
            places = list(fetch_index(root, emit))
        except (OSError, ValueError):
            if cached:
                emit('Could not refresh region list; using the cached copy.')
                places = list(cached)
            else:
                raise

    # Merge custom exact regions (Saint Petersburg, Leningrad Oblast, Moscow, etc.)
    existing_ids = {p['id'] for p in places}
    for cr in CUSTOM_REGIONS:
        if cr['id'] not in existing_ids:
            places.append(dict(cr))
    return places


def slug(place_id):
    """Country id for the zip. Slashes in Geofabrik ids become hyphens."""
    text = place_id.strip().lower().replace('/', '-').replace('_', '-')
    text = re.sub(r'[^a-z0-9-]+', '-', text)
    text = re.sub(r'-{2,}', '-', text).strip('-')
    if not SLUG.fullmatch(text or ''):
        raise ValueError(f'cannot name a pack from {place_id!r}')
    return text


def search(places, query, limit=None):
    """Case-insensitive match on name and id. Empty query returns every extract, by name."""
    needle = (query or '').strip().casefold()
    ranked = sorted(places, key=lambda place: (place['name'].casefold(), place['id']))
    if needle:
        ranked = [place for place in ranked if needle in place['name'].casefold() or needle in place['id'].casefold()]
    return ranked[:limit] if limit else ranked


def parent_name(place, places_by_id):
    parent = places_by_id.get(place.get('parent') or '')
    return parent['name'] if parent else (place.get('parent') or '')


def load_boundaries(root, refresh=False):
    """Separate, optional geometry cache: the region list remains usable offline."""
    path = Path(root) / 'data' / 'geofabrik' / 'index-v1.json'
    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding='utf-8'))
    else:
        request = urllib.request.Request('https://download.geofabrik.de/index-v1.json',
                                         headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60, context=tls.context()) as response:
            data = response.read()
        payload = json.loads(data)
        parse_index(payload)  # validate before replacing the cache
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.json.part')
        temporary.write_bytes(data)
        temporary.replace(path)
    from shapely.geometry import shape, box as make_box
    result = {}
    for feature in payload['features']:
        prop = feature.get('properties') or {}
        if feature.get('geometry') and prop.get('id'):
            geometry = shape(feature['geometry'])
            if not geometry.is_empty and geometry.is_valid:
                result[prop['id']] = geometry

    # Add exact geometries for custom regions (Saint Petersburg, Leningrad Oblast, Moscow, etc.)
    for cr in CUSTOM_REGIONS:
        result[cr['id']] = make_box(*cr['box'])

    # Clamp Arctic islands / polar glaciers from Russian Federal Districts:
    # 1. Northwestern Federal District: clamp to 69.9°N (excludes Novaya Zemlya 70-77°N and Franz Josef Land 80-82.5°N)
    if 'northwestern-fed-district' in result:
        try:
            result['northwestern-fed-district'] = result['northwestern-fed-district'].intersection(make_box(-180, -90, 180, 69.9))
        except Exception:
            pass

    # 2. Siberian, Ural and Far Eastern Federal Districts: clamp to 72-73°N (excludes uninhabited Arctic ice caps)
    for dist_id, max_lat in [('siberian-fed-district', 73.0), ('ural-fed-district', 72.0), ('far-eastern-fed-district', 72.0)]:
        if dist_id in result:
            try:
                result[dist_id] = result[dist_id].intersection(make_box(-180, -90, 180, max_lat))
            except Exception:
                pass

    return result


def smallest_covering(boundaries, box, available):
    """Choose a complete source for the rectangle, including holes/border crossings."""
    from shapely.geometry import box as rectangle
    area = rectangle(*box)
    candidates = ((geometry.area, key) for key, geometry in boundaries.items()
                  if key in available and geometry.covers(area))
    return min(candidates, default=(None, None))[1]
