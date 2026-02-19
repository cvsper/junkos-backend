"""
Pricing API routes for Umuve.
Exposes the v2 pricing engine, pricing rules, surge zones, and category
catalogue for admin and frontend consumption.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, PricingRule, SurgeZone
from routes.booking import (
    calculate_estimate,
    CATEGORY_PRICES,
    VOLUME_DISCOUNT_TIERS,
    MINIMUM_JOB_PRICE,
    SAME_DAY_SURGE,
    NEXT_DAY_SURGE,
    WEEKEND_SURGE,
)

pricing_bp = Blueprint("pricing", __name__, url_prefix="/api/pricing")

COMMISSION_RATE = 0.20


@pricing_bp.route("/estimate", methods=["POST"])
def get_estimate():
    """
    Calculate a price estimate using the v2 pricing engine.

    Body JSON (v2 format -- preferred):
        items: [ { category: str, quantity: int, size?: str }, ... ]
        scheduledDate: str (ISO date)
        address: { lat: float, lng: float }

    Body JSON (legacy format -- still supported):
        items: list of str (item-type names)
        volume: float (cubic yards)
        lat: float
        lng: float

    Returns the full v2 breakdown.
    """
    data = request.get_json() or {}

    # --- Detect format: v2 (list of dicts) vs legacy (list of strings) ---
    raw_items = data.get("items", [])

    if raw_items and isinstance(raw_items[0], dict):
        # v2 format
        items = raw_items
    else:
        # Legacy format: list of item-type strings -> convert to v2
        items = [{"category": name, "quantity": 1} for name in raw_items]

    # Support legacy volume field by adding a "yard_waste" line
    volume = data.get("volume")
    if volume and float(volume) > 0:
        items.append({"category": "yard_waste", "quantity": int(float(volume))})

    address = data.get("address") or {}
    lat = address.get("lat") or data.get("lat")
    lng = address.get("lng") or data.get("lng")
    scheduled_date = data.get("scheduledDate") or data.get("scheduled_date")

    result = calculate_estimate(items, scheduled_date=scheduled_date, lat=lat, lng=lng)

    return jsonify({
        "success": True,
        "estimate": result,
    }), 200


@pricing_bp.route("/rules", methods=["GET"])
def get_rules():
    """Return all active pricing rules."""
    active_only = request.args.get("active", "true").lower() == "true"
    query = PricingRule.query
    if active_only:
        query = query.filter_by(is_active=True)
    rules = query.order_by(PricingRule.item_type).all()

    return jsonify({
        "success": True,
        "rules": [r.to_dict() for r in rules],
    }), 200


@pricing_bp.route("/surge", methods=["GET"])
def get_surge_zones():
    """Return all active surge zones."""
    zones = SurgeZone.query.filter_by(is_active=True).all()
    return jsonify({
        "success": True,
        "surge_zones": [z.to_dict() for z in zones],
    }), 200


@pricing_bp.route("/categories", methods=["GET"])
def get_categories():
    """Return the full category catalogue with default prices.

    Merges hardcoded defaults with any active PricingRule overrides from the
    database so the frontend always has a complete list.
    """
    # Start with hardcoded defaults
    categories = {}
    for cat, sizes in CATEGORY_PRICES.items():
        categories[cat] = dict(sizes)

    # Layer on DB overrides
    rules = PricingRule.query.filter_by(is_active=True).all()
    for rule in rules:
        key = rule.item_type  # e.g. "furniture" or "furniture:large"
        if ":" in key:
            cat, size = key.split(":", 1)
            if cat not in categories:
                categories[cat] = {"default": rule.base_price}
            categories[cat][size] = rule.base_price
        else:
            if key not in categories:
                categories[key] = {}
            categories[key]["default"] = rule.base_price

    return jsonify({
        "success": True,
        "categories": categories,
    }), 200


@pricing_bp.route("/config", methods=["GET"])
def get_pricing_config():
    """Return the full pricing configuration so the frontend / admin panel
    can display current tiers, surge rates, and minimum price."""
    return jsonify({
        "success": True,
        "config": {
            "minimum_job_price": MINIMUM_JOB_PRICE,
            "volume_discount_tiers": [
                {"min_qty": lo, "max_qty": hi, "discount_rate": rate}
                for lo, hi, rate in VOLUME_DISCOUNT_TIERS
            ],
            "time_surge": {
                "same_day": SAME_DAY_SURGE,
                "next_day": NEXT_DAY_SURGE,
                "weekend": WEEKEND_SURGE,
            },
            "commission_rate": COMMISSION_RATE,
        },
    }), 200
