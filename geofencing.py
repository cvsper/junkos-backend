"""
Geofencing utilities for Umuve.

Defines the South Florida service area (Miami-Dade, Broward, Palm Beach counties)
and provides functions to check whether coordinates fall within it.
"""

from math import radians, cos, sin, asin, sqrt

# ---------------------------------------------------------------------------
# Service area definition -- South Florida tri-county area
# ---------------------------------------------------------------------------

# Quick bounding box for fast rejection before the more expensive polygon check.
SERVICE_AREA_BOUNDS = {
    "north": 26.97,   # northern Palm Beach County
    "south": 25.30,   # southern Miami-Dade (Homestead / Florida City)
    "east": -79.85,   # Atlantic coastline
    "west": -80.85,   # western Everglades boundary
}

# Center of the service area (useful for frontend map default center).
SERVICE_AREA_CENTER = {
    "lat": 26.12,
    "lng": -80.35,
}

# Simplified polygon (12 vertices) tracing the approximate boundary of the
# Miami-Dade + Broward + Palm Beach tri-county service area.  The polygon
# follows the coastline on the east and the Everglades / western county
# borders on the west.  Vertices are listed counter-clockwise.
#
# Format: list of (lat, lng) tuples.
SERVICE_AREA_POLYGON = [
    (25.30, -80.40),   # 0  -- SW corner: south of Homestead
    (25.30, -80.15),   # 1  -- SE corner: south Miami-Dade coast
    (25.50, -80.10),   # 2  -- Biscayne Bay / Key Biscayne
    (25.80, -80.12),   # 3  -- Miami Beach area
    (26.05, -80.08),   # 4  -- Fort Lauderdale coast
    (26.35, -80.06),   # 5  -- Pompano / Deerfield Beach coast
    (26.55, -80.03),   # 6  -- Boca Raton coast
    (26.72, -80.03),   # 7  -- Boynton / Lake Worth coast
    (26.90, -80.04),   # 8  -- West Palm Beach coast
    (26.97, -80.10),   # 9  -- NE corner: northern Palm Beach coast
    (26.97, -80.55),   # 10 -- NW corner: western Palm Beach County
    (26.50, -80.65),   # 11 -- western Broward County (Everglades edge)
    (25.80, -80.70),   # 12 -- western Miami-Dade (Everglades edge)
    (25.30, -80.60),   # 13 -- SW: western Homestead / Florida City
    # polygon closes back to vertex 0
]

EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_in_service_area(lat, lng):
    """Return True if the given coordinates fall inside the service area.

    Performs a fast bounding-box check first, then a ray-casting
    point-in-polygon test against ``SERVICE_AREA_POLYGON``.
    """
    if lat is None or lng is None:
        return False

    lat = float(lat)
    lng = float(lng)

    # --- Fast bounding-box rejection ---
    bounds = SERVICE_AREA_BOUNDS
    if (lat < bounds["south"] or lat > bounds["north"]
            or lng < bounds["west"] or lng > bounds["east"]):
        return False

    # --- Ray-casting point-in-polygon ---
    return _point_in_polygon(lat, lng, SERVICE_AREA_POLYGON)


def distance_to_nearest_boundary(lat, lng):
    """Return the shortest distance in km from the point to the polygon boundary.

    Returns 0.0 if the point is on or outside the polygon.
    A positive value indicates the point is inside the polygon.
    """
    if lat is None or lng is None:
        return 0.0

    lat = float(lat)
    lng = float(lng)

    min_dist = float("inf")
    n = len(SERVICE_AREA_POLYGON)
    for i in range(n):
        p1 = SERVICE_AREA_POLYGON[i]
        p2 = SERVICE_AREA_POLYGON[(i + 1) % n]
        dist = _point_to_segment_distance(lat, lng, p1[0], p1[1], p2[0], p2[1])
        if dist < min_dist:
            min_dist = dist

    return round(min_dist, 2)


def get_service_area_info():
    """Return the full service-area definition for use by the frontend.

    Includes polygon vertices, bounding box, and center coordinates.
    """
    return {
        "polygon": [{"lat": p[0], "lng": p[1]} for p in SERVICE_AREA_POLYGON],
        "bounds": SERVICE_AREA_BOUNDS,
        "center": SERVICE_AREA_CENTER,
        "counties": ["Miami-Dade", "Broward", "Palm Beach"],
        "description": "South Florida tri-county area",
    }


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _point_in_polygon(lat, lng, polygon):
    """Ray-casting algorithm to test if a point is inside a polygon.

    ``polygon`` is a list of (lat, lng) tuples.  The polygon is
    implicitly closed (last vertex connects back to first).
    """
    n = len(polygon)
    inside = False

    px, py = lat, lng
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        # Check if the ray from (px, py) going in +y direction crosses this edge
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def _haversine(lat1, lng1, lat2, lng2):
    """Return the great-circle distance in km between two points."""
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def _point_to_segment_distance(px, py, ax, ay, bx, by):
    """Approximate distance in km from point (px, py) to segment (ax, ay)-(bx, by).

    Uses a simple projection onto the line segment and then haversine for
    the final distance calculation.
    """
    # Vector AB
    abx = bx - ax
    aby = by - ay
    # Vector AP
    apx = px - ax
    apy = py - ay

    ab_sq = abx * abx + aby * aby
    if ab_sq == 0:
        # Degenerate segment (A == B)
        return _haversine(px, py, ax, ay)

    # Parameter t of the projection of P onto line AB, clamped to [0, 1]
    t = (apx * abx + apy * aby) / ab_sq
    t = max(0.0, min(1.0, t))

    # Closest point on segment
    closest_lat = ax + t * abx
    closest_lng = ay + t * aby

    return _haversine(px, py, closest_lat, closest_lng)
