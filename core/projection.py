"""
Projection utilities:
- Yandex Maps (EPSG:3395 Elliptical Mercator) tile math
- Local metric coordinate frame for BeamNG.drive (X = East, Y = North, Z = Up)
"""

import math
from typing import Tuple

# WGS 84 ellipsoid constants
WGS84_A = 6378137.0                 # Semi-major axis (meters)
WGS84_E = 0.0818191908426           # First eccentricity
WGS84_E2 = WGS84_E * WGS84_E        # Eccentricity squared


def lat_lon_to_meters(lat: float, lon: float, origin_lat: float, origin_lon: float) -> Tuple[float, float]:
    """
    Converts (lat, lon) in degrees to local Cartesian coordinates (X, Y) in meters,
    where origin_lat, origin_lon is (0, 0).
    X points East, Y points North (standard BeamNG coordinate system).
    """
    origin_lat_rad = math.radians(origin_lat)
    lat_rad = math.radians(lat)
    
    # Earth radius of curvature in the prime vertical & meridian
    d_lat = lat - origin_lat
    d_lon = lon - origin_lon
    
    # Meters per degree latitude and longitude at origin
    meters_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * origin_lat_rad) + 1.175 * math.cos(4 * origin_lat_rad)
    meters_per_deg_lon = 111412.84 * math.cos(origin_lat_rad) - 93.5 * math.cos(3 * origin_lat_rad)
    
    x = d_lon * meters_per_deg_lon
    y = d_lat * meters_per_deg_lat
    return x, y


def meters_to_lat_lon(x: float, y: float, origin_lat: float, origin_lon: float) -> Tuple[float, float]:
    """
    Converts local Cartesian coordinates (X, Y) in meters back to (lat, lon).
    """
    origin_lat_rad = math.radians(origin_lat)
    meters_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * origin_lat_rad) + 1.175 * math.cos(4 * origin_lat_rad)
    meters_per_deg_lon = 111412.84 * math.cos(origin_lat_rad) - 93.5 * math.cos(3 * origin_lat_rad)
    
    d_lat = y / meters_per_deg_lat
    d_lon = x / meters_per_deg_lon
    return origin_lat + d_lat, origin_lon + d_lon


def lat_lon_to_yandex_pixel(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """
    Converts (lat, lon) to continuous pixel coordinates in Yandex Elliptical Mercator projection at given zoom.
    """
    lat = max(min(lat, 89.5), -89.5)
    lat_rad = math.radians(lat)
    
    sin_lat = math.sin(lat_rad)
    beta = WGS84_E * sin_lat
    c = ((1.0 - beta) / (1.0 + beta)) ** (WGS84_E / 2.0)
    
    y = 0.5 - math.log(max(math.tan(math.pi / 4.0 + lat_rad / 2.0) * c, 1e-12)) / (2.0 * math.pi)
    x = (lon + 180.0) / 360.0
    
    scale = (1 << zoom) * 256.0
    return x * scale, y * scale


def yandex_pixel_to_lat_lon(px: float, py: float, zoom: int) -> Tuple[float, float]:
    """
    Converts continuous pixel coordinates at given zoom in Yandex projection back to (lat, lon).
    Uses Newton-Raphson iteration for the inverse elliptical Mercator.
    """
    scale = (1 << zoom) * 256.0
    x = px / scale
    y = py / scale
    
    lon = x * 360.0 - 180.0
    mercator_y = (0.5 - y) * 2.0 * math.pi
    
    # Solve for lat using Newton-Raphson
    lat_rad = 2.0 * math.atan(math.exp(mercator_y)) - math.pi / 2.0
    for _ in range(8):
        sin_lat = math.sin(lat_rad)
        beta = WGS84_E * sin_lat
        c = ((1.0 - beta) / (1.0 + beta)) ** (WGS84_E / 2.0)
        f = 2.0 * math.atan(math.exp(mercator_y) / c) - math.pi / 2.0 - lat_rad
        df = -1.0 - (WGS84_E2 * math.cos(lat_rad)) / (1.0 - WGS84_E2 * sin_lat * sin_lat)
        delta = f / df
        lat_rad -= delta
        if abs(delta) < 1e-10:
            break
            
    lat = math.degrees(lat_rad)
    return lat, lon


def lat_lon_to_yandex_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """
    Returns (tile_x, tile_y) for Yandex tile grid at given zoom.
    """
    px, py = lat_lon_to_yandex_pixel(lat, lon, zoom)
    return int(px // 256), int(py // 256)
