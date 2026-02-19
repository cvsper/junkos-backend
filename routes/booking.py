"""
Booking API routes for Umuve.
Customer booking flow: estimate, create job, and check status.

Pricing engine v2 -- tiered item categories with size variants, volume
discounts (4 tiers), time-based surge, zone-based surge, and a minimum
job price of $89.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone, date as date_type, timedelta
from math import radians, cos, sin, asin, sqrt

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    db, User, Job, Payment, PricingRule, PricingConfig, SurgeZone, Contractor,
    Notification, PromoCode, generate_uuid, utcnow, generate_referral_code,
)
from auth_routes import require_auth, optional_auth
from extensions import limiter
from geofencing import is_in_service_area

booking_bp = Blueprint("booking", __name__, url_prefix="/api/booking")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_PRICE = 0.0            # Removed flat base -- pricing is fully item-driven
SERVICE_FEE_RATE = 0.08     # 8 % of subtotal
MINIMUM_JOB_PRICE = 89.00   # Floor price for any job

# ---------------------------------------------------------------------------
# Default category prices (size-dependent where applicable).
# Keyed by category -> size -> price.  A flat-rate category uses "default".
# Admin PricingRules in the DB override these when present.
# ---------------------------------------------------------------------------
CATEGORY_PRICES = {
    "furniture": {
        "small":   45.00,
        "medium":  65.00,
        "large":   85.00,
        "default": 65.00,
    },
    "appliances": {
        "small":   60.00,
        "medium":  90.00,
        "large":  120.00,
        "default": 90.00,
    },
    "electronics": {
        "small":   25.00,
        "medium":  35.00,
        "large":   50.00,
        "default": 35.00,
    },
    "yard_waste": {
        "default": 35.00,   # per cubic yard
    },
    "construction": {
        "default": 55.00,   # per cubic yard
    },
    "general": {
        "default": 30.00,
    },
    "mattress": {
        "default": 50.00,
    },
    "hot_tub": {
        "small":  250.00,
        "medium": 325.00,
        "large":  400.00,
        "default": 325.00,
    },
    "other": {
        "default": 30.00,
    },
}

# Legacy flat-price mapping (used as ultimate fallback)
FALLBACK_PRICES = {cat: sizes["default"] for cat, sizes in CATEGORY_PRICES.items()}

# ---------------------------------------------------------------------------
# Volume discount tiers
# ---------------------------------------------------------------------------
VOLUME_DISCOUNT_TIERS = [
    # (min_qty, max_qty, discount_rate)
    (1,  3,  0.00),
    (4,  7,  0.10),
    (8,  15, 0.15),
    (16, None, 0.20),
]

# ---------------------------------------------------------------------------
# Time-based surge configuration (additive percentages)
# ---------------------------------------------------------------------------
SAME_DAY_SURGE  = 0.25   # +25 %
NEXT_DAY_SURGE  = 0.10   # +10 %
WEEKEND_SURGE   = 0.15   # +15 %

EARTH_RADIUS_KM = 6371.0
NEARBY_CONTRACTOR_RADIUS_KM = 50.0

# Duration estimation constants
MINUTES_PER_ITEM = 8
BASE_DURATION_MINUTES = 30

# Truck size thresholds
TRUCK_SIZE_THRESHOLDS = [
    (1,  5,  "Standard Pickup"),
    (6,  12, "Large Truck"),
    (13, None, "Extra-Large Truck / Multiple Loads"),
]


# ============================================================================
# Admin-overridable config loader
# ============================================================================
def _load_config(key, default):
    """Load a pricing config value from the DB, falling back to *default*."""
    try:
        row = db.session.get(PricingConfig, key)
        if row is not None and row.value is not None:
            return row.value
    except Exception:
        pass  # DB not ready or table missing -- use default
    return default


def _get_minimum_job_price():
    return float(_load_config("minimum_job_price", MINIMUM_JOB_PRICE))


def _get_volume_discount_tiers():
    """Return volume discount tiers, preferring DB override."""
    raw = _load_config("volume_discount_tiers", None)
    if raw and isinstance(raw, list):
        return [(t["min_qty"], t.get("max_qty"), t["discount_rate"]) for t in raw]
    return VOLUME_DISCOUNT_TIERS


def _get_time_surge_rates():
    """Return (same_day, next_day, weekend) surge rates."""
    same_day = float(_load_config("same_day_surge", SAME_DAY_SURGE))
    next_day = float(_load_config("next_day_surge", NEXT_DAY_SURGE))
    weekend = float(_load_config("weekend_surge", WEEKEND_SURGE))
    return same_day, next_day, weekend


def _get_service_fee_rate():
    return float(_load_config("service_fee_rate", SERVICE_FEE_RATE))


# ============================================================================
# Helpers -- item pricing
# ============================================================================
def _get_item_price(category, size=None):
    """Return the unit price for a (category, size) pair.

    Resolution order:
      1. Active PricingRule in the database whose ``item_type`` matches
         ``<category>:<size>`` (size-specific) or ``<category>`` (flat).
      2. Hardcoded CATEGORY_PRICES dict (size-aware).
      3. FALLBACK_PRICES flat default.
    """
    cat_lower = (category or "other").lower()
    size_lower = (size or "").lower().strip()

    # --- Try DB rule (size-specific first, then flat category) ---
    if size_lower:
        sized_key = "{}:{}".format(cat_lower, size_lower)
        rule = PricingRule.query.filter(
            PricingRule.item_type == sized_key,
            PricingRule.is_active == True,
        ).first()
        if rule:
            return rule.base_price

    rule = PricingRule.query.filter(
        PricingRule.item_type == cat_lower,
        PricingRule.is_active == True,
    ).first()
    if rule:
        return rule.base_price

    # --- Hardcoded tier ---
    cat_prices = CATEGORY_PRICES.get(cat_lower)
    if cat_prices:
        if size_lower and size_lower in cat_prices:
            return cat_prices[size_lower]
        return cat_prices.get("default", 30.00)

    return FALLBACK_PRICES.get(cat_lower, FALLBACK_PRICES["other"])


# ============================================================================
# Helpers -- volume discount
# ============================================================================
def _volume_discount_rate(total_quantity):
    """Return the discount rate based on total item quantity.

    Reads from admin-overridable config first, then falls back to defaults.
    """
    tiers = _get_volume_discount_tiers()
    for lo, hi, rate in tiers:
        if hi is None and total_quantity >= lo:
            return rate
        if hi is not None and lo <= total_quantity <= hi:
            return rate
    return 0.0


def _volume_discount_label(total_quantity):
    """Human-readable label for the discount tier that applies."""
    rate = _volume_discount_rate(total_quantity)
    if rate <= 0:
        return None
    pct = int(rate * 100)
    return "{}% volume discount ({} items)".format(pct, total_quantity)


# ============================================================================
# Helpers -- zone-based surge (existing behaviour)
# ============================================================================
def _active_surge_multiplier(lat=None, lng=None):
    """Return the highest active surge multiplier that applies right now."""
    now = datetime.now(timezone.utc)
    current_day = now.weekday()
    current_time = now.strftime("%H:%M")

    zones = SurgeZone.query.filter_by(is_active=True).all()
    max_surge = 1.0

    for zone in zones:
        if zone.days_of_week and current_day not in zone.days_of_week:
            continue
        if zone.start_time and current_time < zone.start_time:
            continue
        if zone.end_time and current_time > zone.end_time:
            continue
        if zone.surge_multiplier > max_surge:
            max_surge = zone.surge_multiplier

    return max_surge


# ============================================================================
# Helpers -- time-based surge (new)
# ============================================================================
def _time_based_surge(scheduled_date_str):
    """Compute additive surge percentage and a human-readable reason list
    based on the *scheduled pickup date* relative to today (UTC).

    Returns ``(surge_pct, [reason_strings])``.
    """
    if not scheduled_date_str:
        return 0.0, []

    try:
        if isinstance(scheduled_date_str, str):
            sched = datetime.strptime(scheduled_date_str[:10], "%Y-%m-%d").date()
        elif isinstance(scheduled_date_str, datetime):
            sched = scheduled_date_str.date()
        elif isinstance(scheduled_date_str, date_type):
            sched = scheduled_date_str
        else:
            return 0.0, []
    except (ValueError, TypeError):
        return 0.0, []

    today = datetime.now(timezone.utc).date()
    delta_days = (sched - today).days

    same_day_rate, next_day_rate, weekend_rate = _get_time_surge_rates()

    surge = 0.0
    reasons = []

    # Same-day
    if delta_days <= 0:
        surge += same_day_rate
        reasons.append("Same-day pickup (+{}%)".format(int(same_day_rate * 100)))
    # Next-day
    elif delta_days == 1:
        surge += next_day_rate
        reasons.append("Next-day pickup (+{}%)".format(int(next_day_rate * 100)))

    # Weekend (Saturday=5, Sunday=6)
    if sched.weekday() in (5, 6):
        surge += weekend_rate
        reasons.append("Weekend pickup (+{}%)".format(int(weekend_rate * 100)))

    return surge, reasons


# ============================================================================
# Helpers -- duration & truck size
# ============================================================================
def _estimate_duration(total_quantity):
    """Estimate job duration in minutes."""
    return BASE_DURATION_MINUTES + (total_quantity * MINUTES_PER_ITEM)


def _estimate_truck_size(total_quantity):
    """Return a truck-size label based on item count."""
    for lo, hi, label in TRUCK_SIZE_THRESHOLDS:
        if hi is None and total_quantity >= lo:
            return label
        if hi is not None and lo <= total_quantity <= hi:
            return label
    return "Standard Pickup"


# ============================================================================
# Core pricing function  (shared by estimate + booking endpoints)
# ============================================================================
def calculate_estimate(items, scheduled_date=None, lat=None, lng=None):
    """Compute the full pricing breakdown.

    Parameters
    ----------
    items : list[dict]
        Each dict: ``{ category, quantity, size? }``
    scheduled_date : str | datetime | None
        ISO date string or datetime for time-based surge.
    lat, lng : float | None
        Customer location for zone-based surge.

    Returns
    -------
    dict with detailed pricing breakdown.
    """
    item_total = 0.0
    total_quantity = 0
    item_breakdown = []

    for entry in items:
        category = entry.get("category") or "other"
        quantity = int(entry.get("quantity", 1))
        size = entry.get("size")  # optional
        if quantity <= 0:
            continue

        unit_price = _get_item_price(category, size)
        line_total = unit_price * quantity
        item_total += line_total
        total_quantity += quantity

        line = {
            "category": category,
            "quantity": quantity,
            "unit_price": round(unit_price, 2),
            "line_total": round(line_total, 2),
        }
        if size:
            line["size"] = size
        item_breakdown.append(line)

    # --- Volume discount ---
    discount_rate = _volume_discount_rate(total_quantity)
    volume_discount = round(item_total * discount_rate, 2)
    volume_discount_label = _volume_discount_label(total_quantity)

    items_subtotal = round(item_total - volume_discount, 2)

    # --- Zone-based surge multiplier ---
    zone_surge = _active_surge_multiplier(lat, lng)

    # --- Time-based surge ---
    time_surge_pct, surge_reasons = _time_based_surge(scheduled_date)

    # Combined: zone multiplier is multiplicative, time surge is additive on top
    combined_multiplier = zone_surge * (1.0 + time_surge_pct)

    surged_subtotal = round(items_subtotal * combined_multiplier, 2)
    surge_amount = round(surged_subtotal - items_subtotal, 2)

    if zone_surge > 1.0:
        surge_reasons.insert(0, "High-demand zone (x{})".format(round(zone_surge, 2)))

    # --- Service fee (admin-overridable) ---
    fee_rate = _get_service_fee_rate()
    service_fee = round(surged_subtotal * fee_rate, 2)

    # --- Total (with minimum floor, admin-overridable) ---
    min_price = _get_minimum_job_price()
    raw_total = round(surged_subtotal + service_fee, 2)
    total = max(raw_total, min_price)
    minimum_applied = total > raw_total

    # --- Duration & truck size ---
    estimated_duration = _estimate_duration(total_quantity)
    truck_size = _estimate_truck_size(total_quantity)

    return {
        "items_subtotal": round(item_total, 2),
        "items": item_breakdown,
        "volume_discount": volume_discount,
        "volume_discount_rate": discount_rate,
        "volume_discount_label": volume_discount_label,
        "surge_multiplier": round(combined_multiplier, 4),
        "surge_amount": surge_amount,
        "surge_reasons": surge_reasons,
        "base_price": round(items_subtotal, 2),
        "service_fee": service_fee,
        "total": total,
        "minimum_applied": minimum_applied,
        "minimum_job_price": min_price,
        "estimated_duration": estimated_duration,
        "truck_size": truck_size,
        "total_quantity": total_quantity,
    }


def _haversine(lat1, lng1, lat2, lng2):
    """Return distance in kilometres between two GPS points."""
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


# ---------------------------------------------------------------------------
# POST /api/booking/estimate  (public -- no auth required)
# ---------------------------------------------------------------------------
@booking_bp.route("/estimate", methods=["POST"])
def estimate():
    """
    Calculate a price estimate for the customer booking flow.

    Body JSON:
        items: [ { category: str, quantity: int, size?: str }, ... ]
        address: { lat: float, lng: float }
        scheduledDate: str (ISO date for time-based surge)
        scheduled_date: str (alias)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    items = data.get("items")
    if not items or not isinstance(items, list):
        return jsonify({"error": "items array is required"}), 400

    address = data.get("address") or {}
    lat = address.get("lat")
    lng = address.get("lng")

    scheduled_date = data.get("scheduledDate") or data.get("scheduled_date")

    result = calculate_estimate(items, scheduled_date=scheduled_date, lat=lat, lng=lng)

    if result["total_quantity"] == 0:
        return jsonify({"error": "At least one item with a valid category is required"}), 400

    return jsonify({
        "success": True,
        "estimate": result,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/booking  (auth required)
# ---------------------------------------------------------------------------
@booking_bp.route("", methods=["POST"])
@optional_auth
def create_booking(user_id):
    """
    Create a new job / booking.

    Body JSON:
        address: str
        lat: float
        lng: float
        items: list  [{ category, quantity, size? }]
        photos: list (optional, URLs from upload endpoint)
        scheduled_date: str (ISO date)
        scheduled_time: str (HH:MM)
        notes: str (optional)
        estimated_price: float
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # --- Validate required fields (accept both camelCase and snake_case) ---
    address = data.get("address")
    if isinstance(address, dict):
        # Frontend sends address as object — flatten to string
        lat = address.get("lat") or data.get("lat")
        lng = address.get("lng") or data.get("lng")
        address = address.get("street") or address.get("formatted") or ", ".join(
            v for v in [address.get("street"), address.get("city"),
                        address.get("state"), address.get("zip")] if v
        )
    else:
        lat = data.get("lat")
        lng = data.get("lng")

    if not address:
        return jsonify({"error": "address is required"}), 400

    # --- Service area geofence check ---
    if lat is not None and lng is not None:
        try:
            if not is_in_service_area(float(lat), float(lng)):
                return jsonify({
                    "error": "Address is outside our service area. "
                             "We currently serve Miami-Dade, Broward, and Palm Beach counties."
                }), 400
        except (TypeError, ValueError):
            pass  # Invalid coords -- skip check, let downstream handle it

    items = data.get("items")
    if not items or not isinstance(items, list):
        return jsonify({"error": "items array is required"}), 400

    estimated_price = data.get("estimated_price") or data.get("estimatedPrice")
    if estimated_price is None:
        return jsonify({"error": "estimated_price is required"}), 400

    try:
        estimated_price = float(estimated_price)
    except (TypeError, ValueError):
        return jsonify({"error": "estimated_price must be a number"}), 400

    # Parse scheduled datetime (accept camelCase from web frontend)
    scheduled_at = None
    scheduled_date = data.get("scheduled_date") or data.get("scheduledDate")
    scheduled_time = data.get("scheduled_time") or data.get("scheduledTimeSlot") or "09:00"
    # Convert time slot ranges (e.g. "8-10") to HH:MM start time
    if scheduled_time and "-" in scheduled_time and ":" not in scheduled_time:
        try:
            start_hour = int(scheduled_time.split("-")[0])
            scheduled_time = "{:02d}:00".format(start_hour)
        except (ValueError, IndexError):
            scheduled_time = "09:00"
    if scheduled_date:
        try:
            scheduled_at = datetime.strptime(
                "{} {}".format(scheduled_date, scheduled_time), "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid scheduled_date or scheduled_time format"}), 400

    photos = data.get("photos", [])
    notes = data.get("notes", "")

    # --- Re-calculate pricing with the v2 engine ---
    est = calculate_estimate(items, scheduled_date=scheduled_date, lat=lat, lng=lng)

    total = est["total"]
    service_fee = est["service_fee"]
    surge_multiplier = est["surge_multiplier"]
    item_total = est["items_subtotal"]

    # --- Apply promo code if provided ---
    promo_code_str = data.get("promo_code", "").strip()
    promo_code_id = None
    discount_amount = 0.0

    if promo_code_str:
        from routes.promos import validate_promo_code
        promo, discount, promo_error = validate_promo_code(promo_code_str, total)
        if promo_error:
            return jsonify({"error": promo_error}), 400
        promo_code_id = promo.id
        discount_amount = discount
        total = round(total - discount, 2)
        # Increment use count
        promo.use_count = (promo.use_count or 0) + 1

    # --- Resolve customer (auth user or guest) ---
    if not user_id:
        guest_email = (data.get("customerEmail") or "").strip().lower()
        guest_name = (data.get("customerName") or "").strip()
        guest_phone = (data.get("customerPhone") or "").strip()

        if not guest_email:
            return jsonify({"error": "Email is required for guest checkout"}), 400

        # Find existing user by email, or create a guest record
        existing = User.query.filter_by(email=guest_email).first()
        if existing:
            user_id = existing.id
            # Update name/phone if not already set
            if guest_name and not existing.name:
                existing.name = guest_name
            if guest_phone and not existing.phone:
                existing.phone = guest_phone
        else:
            guest_user = User(
                id=generate_uuid(),
                email=guest_email,
                name=guest_name or None,
                phone=guest_phone or None,
                role="customer",
            )
            db.session.add(guest_user)
            db.session.flush()
            user_id = guest_user.id

    # --- Create Job ---
    job = Job(
        id=generate_uuid(),
        customer_id=user_id,
        status="pending",
        address=address,
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
        items=items,
        photos=photos,
        scheduled_at=scheduled_at,
        base_price=est["base_price"],
        item_total=round(item_total, 2),
        service_fee=service_fee,
        surge_multiplier=surge_multiplier,
        total_price=total,
        promo_code_id=promo_code_id,
        discount_amount=discount_amount,
        notes=notes,
        confirmation_code=generate_referral_code(),
    )
    db.session.add(job)

    # --- Create Payment record ---
    payment = Payment(
        id=generate_uuid(),
        job_id=job.id,
        amount=total,
        service_fee=service_fee,
        payment_status="pending",
    )
    db.session.add(payment)

    # --- Notify nearby online contractors ---
    _notify_nearby_contractors(job)

    db.session.commit()

    return jsonify({
        "success": True,
        "job": job.to_dict(),
        "payment": payment.to_dict(),
    }), 201


# ---------------------------------------------------------------------------
# GET /api/booking/<job_id>  (public for now -- status check)
# ---------------------------------------------------------------------------
@booking_bp.route("/<job_id>", methods=["GET"])
def get_booking_status(job_id):
    """Return full booking status including payment and rating info."""
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Booking not found"}), 404

    result = job.to_dict()

    if job.payment:
        result["payment"] = job.payment.to_dict()
    else:
        result["payment"] = None

    if job.rating:
        result["rating"] = job.rating.to_dict()
    else:
        result["rating"] = None

    return jsonify({"success": True, "booking": result}), 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _notify_nearby_contractors(job):
    """Create Notification records for nearby online contractors.

    Also sends APNs push notifications and Socket.IO events to nearby drivers.
    """
    # Lazy imports to avoid circular dependencies
    from socket_events import notify_nearby_drivers
    from notifications import send_push_notification

    if job.lat is None or job.lng is None:
        # No location -- notify all online contractors
        contractors = Contractor.query.filter_by(
            is_online=True, approval_status="approved"
        ).all()
    else:
        contractors = Contractor.query.filter_by(
            is_online=True, approval_status="approved"
        ).all()
        contractors = [
            c for c in contractors
            if c.current_lat is not None
            and c.current_lng is not None
            and _haversine(job.lat, job.lng, c.current_lat, c.current_lng)
            <= NEARBY_CONTRACTOR_RADIUS_KM
        ]

    # Broadcast Socket.IO event to all nearby drivers (once)
    notify_nearby_drivers(job)

    for contractor in contractors:
        # Create Notification DB record (in-app notification history)
        notification = Notification(
            id=generate_uuid(),
            user_id=contractor.user_id,
            type="new_job",
            title="New Job Available",
            body="A new junk removal job is available near you.",
            data={"job_id": job.id, "address": job.address},
        )
        db.session.add(notification)

        # Send APNs push notification
        try:
            send_push_notification(
                contractor.user_id,
                "New Job Nearby",
                "{} - ${}".format(job.address, int(job.total_price) if job.total_price else 0),
                {"job_id": job.id, "type": "new_job", "address": job.address}
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(
                "Failed to send push notification for job %s to contractor %s: %s",
                job.id, contractor.id, e
            )
