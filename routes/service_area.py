"""
Service Area API routes for Umuve.

Public endpoints for querying the service area polygon and checking whether
a given address / coordinate pair falls within it.
"""

from flask import Blueprint, request, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geofencing import is_in_service_area, get_service_area_info, distance_to_nearest_boundary

service_area_bp = Blueprint("service_area", __name__, url_prefix="/api/service-area")


# ---------------------------------------------------------------------------
# GET /api/service-area  (public -- for map display)
# ---------------------------------------------------------------------------
@service_area_bp.route("", methods=["GET"])
def service_area_info():
    """Return the service area polygon, bounds, and center for frontend map display."""
    info = get_service_area_info()
    return jsonify({"success": True, "service_area": info}), 200


# ---------------------------------------------------------------------------
# POST /api/service-area/check  (public)
# ---------------------------------------------------------------------------
@service_area_bp.route("/check", methods=["POST"])
def check_service_area():
    """Check whether coordinates or an address fall within the service area.

    Accepts JSON body:
        { "lat": float, "lng": float }
      or
        { "address": str }  (address-only checks are not yet supported;
                              returns an error asking for coordinates)

    Returns:
        {
            "in_service_area": bool,
            "nearest_boundary_km": float,
            "message": str
        }
    """
    data = request.get_json() or {}

    lat = data.get("lat")
    lng = data.get("lng")

    # If only an address string was provided (no coordinates), we cannot
    # geocode it server-side yet.  Return a helpful message instead of
    # silently failing.
    if lat is None or lng is None:
        address = data.get("address")
        if address:
            return jsonify({
                "error": "Geocoded coordinates (lat/lng) are required. "
                         "Please geocode the address on the client and resend.",
            }), 400
        return jsonify({"error": "lat and lng are required"}), 400

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng must be valid numbers"}), 400

    in_area = is_in_service_area(lat, lng)
    nearest_km = distance_to_nearest_boundary(lat, lng)

    if in_area:
        message = "This address is within our service area."
    else:
        message = (
            "Address is outside our service area. "
            "We currently serve Miami-Dade, Broward, and Palm Beach counties."
        )

    return jsonify({
        "success": True,
        "in_service_area": in_area,
        "nearest_boundary_km": nearest_km,
        "message": message,
    }), 200
