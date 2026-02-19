"""
Recurring Booking API routes for Umuve.
Allows customers to set up recurring/scheduled junk removal pickups.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    db, User, Job, Payment, RecurringBooking,
    generate_uuid, utcnow,
)
from auth_routes import require_auth

recurring_bp = Blueprint("recurring", __name__, url_prefix="/api/recurring")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
VALID_FREQUENCIES = {"weekly", "biweekly", "monthly"}


def _compute_next_scheduled(frequency, day_of_week, day_of_month, preferred_time, after=None):
    """Compute the next scheduled datetime based on frequency settings.

    ``after`` is the reference point (defaults to now).  The returned datetime
    is always in the future relative to ``after``.
    """
    if after is None:
        after = datetime.now(timezone.utc)

    hour, minute = 9, 0
    if preferred_time:
        parts = preferred_time.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

    if frequency in ("weekly", "biweekly"):
        target_dow = day_of_week if day_of_week is not None else 0  # default Monday
        days_ahead = (target_dow - after.weekday()) % 7
        if days_ahead == 0:
            # Same weekday -- if time already passed, push to next occurrence
            candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= after:
                days_ahead = 7
        next_date = after + timedelta(days=days_ahead)
        next_dt = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if frequency == "biweekly" and next_dt <= after + timedelta(days=7):
            next_dt += timedelta(weeks=1)
        return next_dt

    if frequency == "monthly":
        target_day = day_of_month if day_of_month is not None else 1
        # Try current month first
        try:
            candidate = after.replace(day=target_day, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            # Day doesn't exist in current month (e.g. Feb 30) -- skip to next month
            candidate = (after + relativedelta(months=1)).replace(
                day=target_day, hour=hour, minute=minute, second=0, microsecond=0
            )
        if candidate <= after:
            candidate = (candidate + relativedelta(months=1)).replace(
                day=target_day, hour=hour, minute=minute, second=0, microsecond=0
            )
        return candidate

    # Fallback: 7 days from now
    return after + timedelta(days=7)


def _advance_next_scheduled(recurring):
    """Advance ``next_scheduled_at`` to the next occurrence after the current one."""
    current = recurring.next_scheduled_at or datetime.now(timezone.utc)
    recurring.next_scheduled_at = _compute_next_scheduled(
        recurring.frequency,
        recurring.day_of_week,
        recurring.day_of_month,
        recurring.preferred_time,
        after=current,
    )


def _require_admin(f):
    """Inline admin check wrapping require_auth."""
    from functools import wraps

    @wraps(f)
    @require_auth
    def wrapper(user_id, *args, **kwargs):
        user = db.session.get(User, user_id)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(user_id=user_id, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# POST /api/recurring  -- Create a recurring booking
# ---------------------------------------------------------------------------
@recurring_bp.route("", methods=["POST"])
@require_auth
def create_recurring(user_id):
    """Create a new recurring booking for the authenticated customer.

    Body JSON:
        frequency: str ("weekly" | "biweekly" | "monthly")
        day_of_week: int (0-6, required for weekly/biweekly)
        day_of_month: int (1-28, required for monthly)
        preferred_time: str ("HH:MM", default "09:00")
        address: str (required)
        lat: float (optional)
        lng: float (optional)
        items: list (optional)
        notes: str (optional)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # --- Validate frequency ---
    frequency = data.get("frequency")
    if frequency not in VALID_FREQUENCIES:
        return jsonify({"error": "frequency must be one of: weekly, biweekly, monthly"}), 400

    # --- Validate day fields ---
    day_of_week = data.get("day_of_week")
    day_of_month = data.get("day_of_month")

    if frequency in ("weekly", "biweekly"):
        if day_of_week is None:
            return jsonify({"error": "day_of_week is required for weekly/biweekly frequency"}), 400
        try:
            day_of_week = int(day_of_week)
        except (TypeError, ValueError):
            return jsonify({"error": "day_of_week must be an integer 0-6"}), 400
        if not (0 <= day_of_week <= 6):
            return jsonify({"error": "day_of_week must be between 0 (Monday) and 6 (Sunday)"}), 400

    if frequency == "monthly":
        if day_of_month is None:
            return jsonify({"error": "day_of_month is required for monthly frequency"}), 400
        try:
            day_of_month = int(day_of_month)
        except (TypeError, ValueError):
            return jsonify({"error": "day_of_month must be an integer 1-28"}), 400
        if not (1 <= day_of_month <= 28):
            return jsonify({"error": "day_of_month must be between 1 and 28"}), 400

    # --- Validate address ---
    address = data.get("address")
    if not address:
        return jsonify({"error": "address is required"}), 400

    preferred_time = data.get("preferred_time", "09:00")
    lat = data.get("lat")
    lng = data.get("lng")
    items = data.get("items", [])
    notes = data.get("notes", "")

    # Compute first next_scheduled_at
    next_scheduled_at = _compute_next_scheduled(
        frequency, day_of_week, day_of_month, preferred_time
    )

    recurring = RecurringBooking(
        id=generate_uuid(),
        customer_id=user_id,
        frequency=frequency,
        day_of_week=day_of_week if frequency in ("weekly", "biweekly") else None,
        day_of_month=day_of_month if frequency == "monthly" else None,
        preferred_time=preferred_time,
        address=address,
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
        items=items,
        notes=notes,
        is_active=True,
        next_scheduled_at=next_scheduled_at,
        total_bookings_created=0,
    )
    db.session.add(recurring)
    db.session.commit()

    return jsonify({"success": True, "recurring_booking": recurring.to_dict()}), 201


# ---------------------------------------------------------------------------
# GET /api/recurring  -- List user's recurring bookings
# ---------------------------------------------------------------------------
@recurring_bp.route("", methods=["GET"])
@require_auth
def list_recurring(user_id):
    """Return all recurring bookings for the authenticated user."""
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"

    query = RecurringBooking.query.filter_by(customer_id=user_id)
    if not include_inactive:
        query = query.filter_by(is_active=True)

    bookings = query.order_by(RecurringBooking.created_at.desc()).all()
    return jsonify({
        "success": True,
        "recurring_bookings": [b.to_dict() for b in bookings],
    }), 200


# ---------------------------------------------------------------------------
# GET /api/recurring/<id>  -- Get single recurring booking
# ---------------------------------------------------------------------------
@recurring_bp.route("/<recurring_id>", methods=["GET"])
@require_auth
def get_recurring(user_id, recurring_id):
    """Return a single recurring booking (must belong to user)."""
    recurring = db.session.get(RecurringBooking, recurring_id)
    if not recurring:
        return jsonify({"error": "Recurring booking not found"}), 404
    if recurring.customer_id != user_id:
        return jsonify({"error": "Not authorized"}), 403

    return jsonify({"success": True, "recurring_booking": recurring.to_dict()}), 200


# ---------------------------------------------------------------------------
# PUT /api/recurring/<id>  -- Update recurring booking
# ---------------------------------------------------------------------------
@recurring_bp.route("/<recurring_id>", methods=["PUT"])
@require_auth
def update_recurring(user_id, recurring_id):
    """Update a recurring booking's details.

    Updatable fields: frequency, day_of_week, day_of_month, preferred_time,
    address, lat, lng, items, notes, is_active.
    """
    recurring = db.session.get(RecurringBooking, recurring_id)
    if not recurring:
        return jsonify({"error": "Recurring booking not found"}), 404
    if recurring.customer_id != user_id:
        return jsonify({"error": "Not authorized"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    recalc_schedule = False

    # --- Frequency ---
    if "frequency" in data:
        if data["frequency"] not in VALID_FREQUENCIES:
            return jsonify({"error": "frequency must be one of: weekly, biweekly, monthly"}), 400
        recurring.frequency = data["frequency"]
        recalc_schedule = True

    # --- Day of week ---
    if "day_of_week" in data:
        dow = data["day_of_week"]
        if dow is not None:
            try:
                dow = int(dow)
            except (TypeError, ValueError):
                return jsonify({"error": "day_of_week must be an integer 0-6"}), 400
            if not (0 <= dow <= 6):
                return jsonify({"error": "day_of_week must be between 0 and 6"}), 400
        recurring.day_of_week = dow
        recalc_schedule = True

    # --- Day of month ---
    if "day_of_month" in data:
        dom = data["day_of_month"]
        if dom is not None:
            try:
                dom = int(dom)
            except (TypeError, ValueError):
                return jsonify({"error": "day_of_month must be an integer 1-28"}), 400
            if not (1 <= dom <= 28):
                return jsonify({"error": "day_of_month must be between 1 and 28"}), 400
        recurring.day_of_month = dom
        recalc_schedule = True

    # --- Preferred time ---
    if "preferred_time" in data:
        recurring.preferred_time = data["preferred_time"]
        recalc_schedule = True

    # --- Address / location ---
    if "address" in data:
        if not data["address"]:
            return jsonify({"error": "address cannot be empty"}), 400
        recurring.address = data["address"]
    if "lat" in data:
        recurring.lat = float(data["lat"]) if data["lat"] is not None else None
    if "lng" in data:
        recurring.lng = float(data["lng"]) if data["lng"] is not None else None

    # --- Items / notes ---
    if "items" in data:
        recurring.items = data["items"]
    if "notes" in data:
        recurring.notes = data["notes"]

    # --- Active status ---
    if "is_active" in data:
        recurring.is_active = bool(data["is_active"])
        if recurring.is_active:
            recalc_schedule = True

    # Recompute next_scheduled_at if schedule parameters changed
    if recalc_schedule and recurring.is_active:
        recurring.next_scheduled_at = _compute_next_scheduled(
            recurring.frequency,
            recurring.day_of_week,
            recurring.day_of_month,
            recurring.preferred_time,
        )

    db.session.commit()
    return jsonify({"success": True, "recurring_booking": recurring.to_dict()}), 200


# ---------------------------------------------------------------------------
# DELETE /api/recurring/<id>  -- Cancel (soft delete)
# ---------------------------------------------------------------------------
@recurring_bp.route("/<recurring_id>", methods=["DELETE"])
@require_auth
def delete_recurring(user_id, recurring_id):
    """Soft-delete a recurring booking by setting is_active=False."""
    recurring = db.session.get(RecurringBooking, recurring_id)
    if not recurring:
        return jsonify({"error": "Recurring booking not found"}), 404
    if recurring.customer_id != user_id:
        return jsonify({"error": "Not authorized"}), 403

    recurring.is_active = False
    db.session.commit()

    return jsonify({"success": True, "message": "Recurring booking cancelled"}), 200


# ---------------------------------------------------------------------------
# POST /api/recurring/generate-next  -- Admin/cron: generate jobs
# ---------------------------------------------------------------------------
@recurring_bp.route("/generate-next", methods=["POST"])
@_require_admin
def generate_next_jobs(user_id):
    """Generate Job records from all active recurring bookings that are due.

    Intended to be called by a cron job or scheduler.  For each active
    recurring booking whose ``next_scheduled_at <= now``, a new Job is created
    using the booking's stored details, and the schedule is advanced.
    """
    now = datetime.now(timezone.utc)

    due_bookings = RecurringBooking.query.filter(
        RecurringBooking.is_active == True,
        RecurringBooking.next_scheduled_at <= now,
    ).all()

    created_jobs = []

    for recurring in due_bookings:
        # Create a new Job mirroring the recurring booking's details
        job = Job(
            id=generate_uuid(),
            customer_id=recurring.customer_id,
            status="pending",
            address=recurring.address,
            lat=recurring.lat,
            lng=recurring.lng,
            items=recurring.items,
            scheduled_at=recurring.next_scheduled_at,
            notes="[Recurring] {}".format(recurring.notes or ""),
        )
        db.session.add(job)

        # Create a corresponding Payment record
        payment = Payment(
            id=generate_uuid(),
            job_id=job.id,
            amount=0.0,  # Will be calculated when job is accepted/priced
            payment_status="pending",
        )
        db.session.add(payment)

        # Advance schedule and increment counter
        recurring.total_bookings_created += 1
        _advance_next_scheduled(recurring)

        created_jobs.append(job.to_dict())

    db.session.commit()

    return jsonify({
        "success": True,
        "jobs_created": len(created_jobs),
        "jobs": created_jobs,
    }), 200
