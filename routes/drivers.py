"""
Driver / Contractor API routes for Umuve.
Handles contractor registration, availability, location, and job management.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from math import radians, cos, sin, asin, sqrt
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, Contractor, Job, Notification, OperatorInvite, Referral, generate_uuid, utcnow
from auth_routes import require_auth

drivers_bp = Blueprint("drivers", __name__, url_prefix="/api/drivers")

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0
DEFAULT_SEARCH_RADIUS_KM = 30.0


def _haversine(lat1, lng1, lat2, lng2):
    """Return distance in kilometres between two GPS points."""
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


@drivers_bp.route("/register", methods=["POST"])
@require_auth
def register_contractor(user_id):
    """Register the authenticated user as a contractor."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.contractor_profile:
        return jsonify({"error": "User is already registered as a contractor"}), 409

    data = request.get_json() or {}

    is_operator = bool(data.get("is_operator", False))
    invite_code = data.get("invite_code")

    contractor = Contractor(
        id=generate_uuid(),
        user_id=user.id,
        license_url=data.get("license_url"),
        insurance_url=data.get("insurance_url"),
        truck_photos=data.get("truck_photos", []),
        truck_type=data.get("truck_type"),
        truck_capacity=data.get("truck_capacity"),
        approval_status="pending",
        is_operator=is_operator,
    )

    if is_operator:
        user.role = "operator"
    else:
        user.role = "driver"

    # Handle invite code — link contractor to an operator's fleet
    if invite_code and not is_operator:
        invite = OperatorInvite.query.filter_by(
            invite_code=invite_code, is_active=True
        ).first()
        if invite:
            now = utcnow()
            # Ensure both datetimes are tz-aware for comparison
            invite_exp = invite.expires_at
            if invite_exp and invite_exp.tzinfo is None:
                from datetime import timezone as _tz
                invite_exp = invite_exp.replace(tzinfo=_tz.utc)
            expired = invite_exp and invite_exp < now
            maxed = invite.use_count >= invite.max_uses
            if not expired and not maxed:
                contractor.operator_id = invite.operator_id
                invite.use_count += 1
                if invite.use_count >= invite.max_uses:
                    invite.is_active = False

    db.session.add(contractor)
    db.session.commit()

    return jsonify({"success": True, "contractor": contractor.to_dict()}), 201


@drivers_bp.route("/profile", methods=["GET"])
@require_auth
def get_profile(user_id):
    """Return the contractor profile for the authenticated user."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    return jsonify({"success": True, "contractor": contractor.to_dict()}), 200


@drivers_bp.route("/availability", methods=["PUT"])
@require_auth
def update_availability(user_id):
    """Toggle online status and update availability schedule."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    data = request.get_json() or {}

    if "is_online" in data:
        contractor.is_online = bool(data["is_online"])
    if "availability_schedule" in data:
        contractor.availability_schedule = data["availability_schedule"]

    db.session.commit()
    return jsonify({"success": True, "contractor": contractor.to_dict()}), 200


@drivers_bp.route("/location", methods=["PUT"])
@require_auth
def update_location(user_id):
    """Update the contractor current GPS coordinates."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    data = request.get_json() or {}
    lat = data.get("lat")
    lng = data.get("lng")

    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    try:
        contractor.current_lat = float(lat)
        contractor.current_lng = float(lng)
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng must be numbers"}), 400

    db.session.commit()
    return jsonify({"success": True, "lat": contractor.current_lat, "lng": contractor.current_lng}), 200


@drivers_bp.route("/jobs/available", methods=["GET"])
@require_auth
def get_available_jobs(user_id):
    """Return pending jobs near the contractor current location."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    if contractor.approval_status != "approved":
        return jsonify({"error": "Contractor is not approved"}), 403

    radius_km = float(request.args.get("radius", DEFAULT_SEARCH_RADIUS_KM))

    # Include pending jobs + jobs already assigned to this contractor
    pending_jobs = Job.query.filter(
        db.or_(
            Job.status.in_(["pending", "confirmed"]),
            db.and_(
                Job.driver_id == contractor.id,
                Job.status.in_(["assigned", "accepted", "en_route", "arrived", "started"]),
            ),
        )
    ).all()

    nearby = []
    for job in pending_jobs:
        if job.lat is not None and job.lng is not None and contractor.current_lat is not None and contractor.current_lng is not None:
            dist = _haversine(contractor.current_lat, contractor.current_lng, job.lat, job.lng)
            if dist <= radius_km:
                job_data = job.to_dict()
                job_data["distance_km"] = round(dist, 2)
                nearby.append(job_data)
        else:
            job_data = job.to_dict()
            job_data["distance_km"] = None
            nearby.append(job_data)

    nearby.sort(key=lambda j: j["distance_km"] if j["distance_km"] is not None else float("inf"))

    return jsonify({"success": True, "jobs": nearby}), 200


@drivers_bp.route("/jobs/<job_id>/accept", methods=["POST"])
@require_auth
def accept_job(user_id, job_id):
    """Accept a pending/confirmed/assigned job."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    if contractor.approval_status != "approved":
        return jsonify({"error": "Contractor is not approved"}), 403

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.status not in ("pending", "confirmed", "assigned"):
        return jsonify({"error": "Job cannot be accepted (current status: {})".format(job.status)}), 409

    job.driver_id = contractor.id
    job.status = "accepted"
    job.updated_at = utcnow()

    notification = Notification(
        id=generate_uuid(),
        user_id=job.customer_id,
        type="job_update",
        title="Driver Assigned",
        body="A driver has accepted your job.",
        data={"job_id": job.id, "status": "accepted"},
    )
    db.session.add(notification)
    db.session.commit()

    # Send APNs push to customer
    try:
        from notifications import send_push_notification
        send_push_notification(
            job.customer_id,
            "Driver Assigned",
            "A driver has been assigned to your job!",
            {"job_id": job.id, "type": "job_update", "status": "accepted"}
        )
    except Exception as e:
        logger.exception("Failed to send push to customer for job %s: %s", job.id, e)

    # Broadcast via SocketIO
    from socket_events import broadcast_job_accepted, socketio
    broadcast_job_accepted(job.id, contractor.id)

    # Also notify the customer's job room
    socketio.emit("job:driver-assigned", {
        "job_id": job.id,
        "driver": {
            "id": contractor.id,
            "name": contractor.user.name if contractor.user else None,
            "truck_type": contractor.truck_type,
            "avg_rating": contractor.avg_rating,
            "total_jobs": contractor.total_jobs,
        },
    }, room=job.id)

    return jsonify({"success": True, "job": job.to_dict()}), 200


@drivers_bp.route("/jobs/<job_id>/decline", methods=["POST"])
@require_auth
def decline_job(user_id, job_id):
    """Decline an assigned job (only if assigned to this driver)."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.driver_id != contractor.id:
        return jsonify({"error": "Job is not assigned to you"}), 403

    if job.status not in ("assigned", "accepted"):
        return jsonify({"error": "Cannot decline job in status: {}".format(job.status)}), 409

    # Unassign driver, revert to confirmed
    job.driver_id = None
    job.status = "confirmed"
    job.updated_at = utcnow()
    db.session.commit()

    # Re-run auto-assignment to find another driver
    from routes.payments import _auto_assign_driver
    _auto_assign_driver(job)
    db.session.commit()

    from socket_events import broadcast_job_status
    broadcast_job_status(job.id, job.status)

    return jsonify({"success": True, "job": job.to_dict()}), 200


VALID_STATUS_TRANSITIONS = {
    "assigned": ["accepted", "cancelled"],
    "accepted": ["en_route", "cancelled"],
    "en_route": ["arrived", "cancelled"],
    "arrived": ["started", "cancelled"],
    "started": ["completed"],
}


@drivers_bp.route("/jobs/<job_id>/status", methods=["PUT"])
@require_auth
def update_job_status(user_id, job_id):
    """Advance the job through its lifecycle."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.driver_id != contractor.id:
        return jsonify({"error": "You are not assigned to this job"}), 403

    data = request.get_json() or {}
    new_status = data.get("status")

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    allowed = VALID_STATUS_TRANSITIONS.get(job.status, [])
    if new_status not in allowed:
        return jsonify({
            "error": "Cannot transition from {} to {}".format(job.status, new_status),
            "allowed": allowed,
        }), 409

    job.status = new_status
    job.updated_at = utcnow()

    if new_status == "started":
        job.started_at = utcnow()
    elif new_status == "completed":
        job.completed_at = utcnow()
        contractor.total_jobs = (contractor.total_jobs or 0) + 1

        # Warn if proof photos have not been submitted
        has_before = bool(job.before_photos)
        has_after = bool(job.after_photos)
        if not has_before or not has_after:
            missing = []
            if not has_before:
                missing.append("before_photos")
            if not has_after:
                missing.append("after_photos")
            logger.warning(
                "Job %s completed without proof photos (missing: %s). "
                "Driver: %s",
                job.id, ", ".join(missing), contractor.id,
            )

        # --- Referral completion: check if this customer was referred ---
        try:
            referral = Referral.query.filter_by(
                referee_id=job.customer_id,
                status="signed_up",
            ).first()
            if referral:
                referral.status = "completed"
                referral.completed_at = utcnow()
                logger.info(
                    "Referral %s completed: referee %s first job %s done",
                    referral.id, job.customer_id, job.id,
                )
        except Exception as e:
            logger.warning("Failed to update referral on job completion: %s", e)

    if data.get("before_photos"):
        job.before_photos = data["before_photos"]
    if data.get("after_photos"):
        job.after_photos = data["after_photos"]

    notification = Notification(
        id=generate_uuid(),
        user_id=job.customer_id,
        type="job_update",
        title="Job {}".format(new_status.replace("_", " ").title()),
        body="Your job status has been updated to {}.".format(new_status),
        data={"job_id": job.id, "status": new_status},
    )
    db.session.add(notification)
    db.session.commit()

    # --- Email / SMS / Push notifications for key status changes ---
    driver_name = contractor.user.name if contractor.user else None
    try:
        from notifications import (
            send_driver_en_route_email, send_driver_en_route_sms,
            send_job_completed_email, send_push_notification,
        )
        customer = db.session.get(User, job.customer_id)

        if new_status == "en_route":
            # Email + SMS customer, push to customer
            if customer:
                if customer.email:
                    send_driver_en_route_email(customer.email, customer.name, driver_name, job.address)
                if customer.phone:
                    send_driver_en_route_sms(customer.phone, driver_name, job.address)
                send_push_notification(
                    customer.id, "Your Driver Is On The Way!",
                    "Your driver is on the way!",
                    {"job_id": job.id, "status": "en_route", "category": "job_en_route"},
                )

        elif new_status == "arrived":
            if customer:
                send_push_notification(
                    customer.id, "Driver Has Arrived",
                    "Your driver has arrived at the location.",
                    {"job_id": job.id, "status": "arrived", "category": "job_arrived"},
                )

        elif new_status == "started":
            if customer:
                send_push_notification(
                    customer.id, "Job In Progress",
                    "Your driver has started the job.",
                    {"job_id": job.id, "status": "started", "category": "job_started"},
                )

        elif new_status == "completed":
            # Email + push to customer
            if customer:
                if customer.email:
                    send_job_completed_email(customer.email, customer.name, job.id, job.address)
                send_push_notification(
                    customer.id, "Pickup Complete!",
                    "Pickup complete! Rate your experience",
                    {"job_id": job.id, "status": "completed", "category": "job_completed"},
                )
            # Push to operator if job was delegated
            if job.operator_id:
                from models import Contractor as _Contractor
                op = db.session.get(_Contractor, job.operator_id)
                if op:
                    send_push_notification(
                        op.user_id, "Job Completed",
                        "Job {} completed by {}".format(
                            str(job.id)[:8], driver_name or "driver"
                        ),
                        {"job_id": job.id, "driver_id": contractor.id},
                    )
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).exception("Notification failed for job %s: %s", job.id, e)

    # Broadcast via SocketIO
    from socket_events import broadcast_job_status
    broadcast_job_status(job.id, new_status)

    return jsonify({"success": True, "job": job.to_dict()}), 200


@drivers_bp.route("/jobs/<job_id>/proof", methods=["POST"])
@require_auth
def submit_job_proof(user_id, job_id):
    """Submit before/after proof photos for a job.

    Accepts JSON body with:
        - before_photos: list of photo URLs
        - after_photos: list of photo URLs

    Only works on jobs with status 'started' or 'completed'.
    Sets proof_submitted_at to the current time.
    """
    import logging
    logger = logging.getLogger(__name__)

    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.driver_id != contractor.id:
        return jsonify({"error": "You are not assigned to this job"}), 403

    if job.status not in ("started", "completed"):
        return jsonify({
            "error": "Proof can only be submitted for jobs with status 'started' or 'completed' (current: {})".format(job.status),
        }), 409

    data = request.get_json() or {}

    before_photos = data.get("before_photos")
    after_photos = data.get("after_photos")

    if not before_photos and not after_photos:
        return jsonify({"error": "At least one of before_photos or after_photos is required"}), 400

    if before_photos is not None:
        if not isinstance(before_photos, list):
            return jsonify({"error": "before_photos must be a list of URLs"}), 400
        job.before_photos = before_photos

    if after_photos is not None:
        if not isinstance(after_photos, list):
            return jsonify({"error": "after_photos must be a list of URLs"}), 400
        job.after_photos = after_photos

    job.proof_submitted_at = utcnow()
    job.updated_at = utcnow()

    db.session.commit()

    logger.info("Proof photos submitted for job %s by contractor %s", job.id, contractor.id)

    return jsonify({"success": True, "job": job.to_dict()}), 200


@drivers_bp.route("/jobs/<job_id>/volume", methods=["POST"])
@require_auth
def propose_volume_adjustment(user_id, job_id):
    """Driver proposes a volume adjustment after arriving on-site."""
    from routes.booking import calculate_estimate
    from notifications import send_push_notification
    from socket_events import socketio
    import stripe

    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.status != "arrived":
        return jsonify({"error": "Job must be in 'arrived' status to propose volume adjustment"}), 400

    if job.driver_id != contractor.id:
        return jsonify({"error": "Only the assigned driver can propose volume adjustment"}), 403

    data = request.get_json() or {}
    actual_volume = data.get("actual_volume")

    if not actual_volume or not isinstance(actual_volume, (int, float)):
        return jsonify({"error": "actual_volume (number) is required"}), 400

    # Map volume to item quantity using Phase 2 tier mapping
    if actual_volume <= 4:
        quantity = 2  # quarter
    elif actual_volume <= 8:
        quantity = 5  # half
    elif actual_volume <= 12:
        quantity = 10  # threeQuarter
    else:
        quantity = 16  # full

    # Calculate new price
    try:
        items = [{"category": "general", "quantity": quantity}]
        result = calculate_estimate(items, scheduled_date=None, lat=None, lng=None)
        new_price = result["grand_total"]
    except Exception as e:
        logger.exception("Failed to calculate new price for volume adjustment")
        return jsonify({"error": "Failed to calculate new price"}), 500

    # Auto-approve if price decreased or stayed the same
    if new_price <= job.total_price:
        job.total_price = new_price
        job.volume_estimate = actual_volume
        job.updated_at = utcnow()

        # Update Stripe PaymentIntent if it exists
        try:
            if job.payment and job.payment.stripe_payment_intent_id:
                stripe.PaymentIntent.modify(
                    job.payment.stripe_payment_intent_id,
                    amount=int(new_price * 100)
                )
                job.payment.amount = new_price
                job.payment.commission = new_price * 0.20
                job.payment.driver_payout_amount = new_price * 0.80
        except Exception as e:
            logger.warning("Failed to update Stripe PaymentIntent for auto-approved volume adjustment: %s", e)

        db.session.commit()

        # Emit socket event
        try:
            socketio.emit("volume:approved", {"job_id": job_id}, room=f"driver:{contractor.id}")
        except Exception as e:
            logger.warning("Failed to emit volume:approved socket event: %s", e)

        logger.info("Volume adjustment auto-approved for job %s (price decreased: $%.2f -> $%.2f)",
                   job_id, job.total_price, new_price)

        return jsonify({
            "success": True,
            "auto_approved": True,
            "new_price": new_price
        }), 200

    # Price increased - require customer approval
    job.volume_adjustment_proposed = True
    job.adjusted_volume = actual_volume
    job.adjusted_price = new_price
    job.updated_at = utcnow()
    db.session.commit()

    # Send push notification with category for actionable notification
    try:
        send_push_notification(
            job.customer_id,
            "Price Adjustment Required",
            f"Volume increased. New price: ${new_price:.2f} (was ${job.total_price:.2f})",
            data={
                "job_id": job_id,
                "new_price": str(new_price),
                "original_price": str(job.total_price),
                "type": "volume_adjustment"
            },
            category="VOLUME_ADJUSTMENT"
        )
    except Exception as e:
        logger.warning("Failed to send volume adjustment push notification: %s", e)

    # Emit socket event
    try:
        socketio.emit("volume:proposed", {"job_id": job_id, "new_price": new_price}, room=f"driver:{contractor.id}")
    except Exception as e:
        logger.warning("Failed to emit volume:proposed socket event: %s", e)

    logger.info("Volume adjustment proposed for job %s: $%.2f -> $%.2f", job_id, job.total_price, new_price)

    return jsonify({
        "success": True,
        "new_price": new_price,
        "original_price": job.total_price
    }), 200
