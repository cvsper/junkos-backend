"""
Operator API routes for Umuve.
Fleet managers who receive jobs from admin and delegate them to their contractors.
"""

import secrets
from flask import Blueprint, request, jsonify
from functools import wraps
from datetime import datetime, timezone, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    db, User, Contractor, Job, Payment, Notification, OperatorInvite,
    generate_uuid, utcnow,
)
from auth_routes import require_auth

operator_bp = Blueprint("operator", __name__, url_prefix="/api/operator")


def require_operator(f):
    """Wrap require_auth and check that the user is an operator."""
    @wraps(f)
    @require_auth
    def wrapper(user_id, *args, **kwargs):
        user = db.session.get(User, user_id)
        if not user or user.role != "operator":
            return jsonify({"error": "Operator access required"}), 403
        contractor = Contractor.query.filter_by(user_id=user_id).first()
        if not contractor or not contractor.is_operator:
            return jsonify({"error": "Operator access required"}), 403
        return f(user_id=user_id, operator=contractor, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@operator_bp.route("/dashboard", methods=["GET"])
@require_operator
def dashboard(user_id, operator):
    """Operator dashboard stats."""
    now = utcnow()
    thirty_days_ago = now - timedelta(days=30)

    fleet = Contractor.query.filter_by(operator_id=operator.id).all()
    fleet_ids = [c.id for c in fleet]
    fleet_size = len(fleet)
    online_count = sum(1 for c in fleet if c.is_online)

    pending_delegation = Job.query.filter_by(
        operator_id=operator.id, status="delegating"
    ).count()

    # 30d earnings from commission on fleet jobs
    earnings_30d = 0.0
    if fleet_ids:
        payments = (
            Payment.query
            .join(Job, Payment.job_id == Job.id)
            .filter(
                Job.operator_id == operator.id,
                Job.driver_id.in_(fleet_ids),
                Payment.payment_status == "succeeded",
                Payment.created_at >= thirty_days_ago,
            )
            .all()
        )
        earnings_30d = sum(p.operator_payout_amount or 0.0 for p in payments)

    return jsonify({
        "success": True,
        "dashboard": {
            "fleet_size": fleet_size,
            "online_count": online_count,
            "pending_delegation": pending_delegation,
            "earnings_30d": round(earnings_30d, 2),
        },
    }), 200


# ---------------------------------------------------------------------------
# Fleet Management
# ---------------------------------------------------------------------------

@operator_bp.route("/fleet", methods=["GET"])
@require_operator
def list_fleet(user_id, operator):
    """List fleet contractors."""
    fleet = Contractor.query.filter_by(operator_id=operator.id).all()

    contractors = []
    for c in fleet:
        contractors.append({
            "id": c.id,
            "name": c.user.name if c.user else None,
            "email": c.user.email if c.user else None,
            "truck_type": c.truck_type,
            "is_online": c.is_online,
            "avg_rating": c.avg_rating,
            "total_jobs": c.total_jobs,
            "approval_status": c.approval_status,
        })

    return jsonify({"success": True, "contractors": contractors}), 200


# ---------------------------------------------------------------------------
# Invite Codes
# ---------------------------------------------------------------------------

@operator_bp.route("/invites", methods=["POST"])
@require_operator
def create_invite(user_id, operator):
    """Create an invite code for a new fleet contractor."""
    data = request.get_json() or {}

    code = secrets.token_urlsafe(6)[:8].upper()
    invite = OperatorInvite(
        id=generate_uuid(),
        operator_id=operator.id,
        invite_code=code,
        email=data.get("email"),
        max_uses=int(data.get("max_uses", 1)),
        is_active=True,
    )

    expires_days = data.get("expires_days")
    if expires_days:
        invite.expires_at = utcnow() + timedelta(days=int(expires_days))

    db.session.add(invite)
    db.session.commit()

    return jsonify({"success": True, "invite": invite.to_dict()}), 201


@operator_bp.route("/invites", methods=["GET"])
@require_operator
def list_invites(user_id, operator):
    """List active invite codes."""
    invites = OperatorInvite.query.filter_by(
        operator_id=operator.id, is_active=True
    ).order_by(OperatorInvite.created_at.desc()).all()

    return jsonify({
        "success": True,
        "invites": [i.to_dict() for i in invites],
    }), 200


@operator_bp.route("/invites/<invite_id>", methods=["DELETE"])
@require_operator
def revoke_invite(user_id, operator, invite_id):
    """Revoke an invite code."""
    invite = db.session.get(OperatorInvite, invite_id)
    if not invite or invite.operator_id != operator.id:
        return jsonify({"error": "Invite not found"}), 404

    invite.is_active = False
    db.session.commit()

    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@operator_bp.route("/jobs", methods=["GET"])
@require_operator
def list_jobs(user_id, operator):
    """List jobs for this operator, filterable by status group."""
    status_filter = request.args.get("filter", "all")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Job.query.filter_by(operator_id=operator.id)

    if status_filter == "delegating":
        query = query.filter_by(status="delegating")
    elif status_filter == "active":
        query = query.filter(Job.status.in_(["assigned", "accepted", "en_route", "arrived", "started"]))
    elif status_filter == "completed":
        query = query.filter_by(status="completed")

    pagination = query.order_by(Job.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    jobs = []
    for j in pagination.items:
        job_data = j.to_dict()
        # Include driver name if assigned
        if j.driver_id and j.driver:
            job_data["driver_name"] = j.driver.user.name if j.driver.user else None
        else:
            job_data["driver_name"] = None
        # Include customer name
        if j.customer:
            job_data["customer_name"] = j.customer.name
            job_data["customer_email"] = j.customer.email
        jobs.append(job_data)

    return jsonify({
        "success": True,
        "jobs": jobs,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


@operator_bp.route("/jobs/<job_id>/delegate", methods=["PUT"])
@require_operator
def delegate_job(user_id, operator, job_id):
    """Delegate a job to a fleet contractor."""
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.operator_id != operator.id:
        return jsonify({"error": "Job does not belong to your fleet"}), 403

    if job.status != "delegating":
        return jsonify({"error": "Job is not in delegating status"}), 409

    data = request.get_json() or {}
    contractor_id = data.get("contractor_id")
    if not contractor_id:
        return jsonify({"error": "contractor_id is required"}), 400

    contractor = db.session.get(Contractor, contractor_id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    if contractor.operator_id != operator.id:
        return jsonify({"error": "Contractor is not in your fleet"}), 403

    if contractor.approval_status != "approved":
        return jsonify({"error": "Contractor is not approved"}), 403

    job.driver_id = contractor.id
    job.status = "assigned"
    job.delegated_at = utcnow()
    job.updated_at = utcnow()

    # Notify the fleet contractor
    notification = Notification(
        id=generate_uuid(),
        user_id=contractor.user_id,
        type="job_assigned",
        title="New Job Assigned",
        body="Your operator has assigned you a job at {}.".format(job.address or "an address"),
        data={"job_id": job.id, "address": job.address, "total_price": job.total_price},
    )
    db.session.add(notification)

    # Notify customer
    notification_cust = Notification(
        id=generate_uuid(),
        user_id=job.customer_id,
        type="job_update",
        title="Driver Assigned",
        body="A driver has been assigned to your job.",
        data={"job_id": job.id, "status": "assigned"},
    )
    db.session.add(notification_cust)
    db.session.commit()

    # --- Email / SMS / Push notifications ---
    driver_name = contractor.user.name if contractor.user else None
    try:
        from notifications import (
            send_driver_assigned_email, send_driver_assigned_sms, send_push_notification,
        )
        customer = db.session.get(User, job.customer_id)
        if customer:
            if customer.email:
                send_driver_assigned_email(customer.email, customer.name, driver_name, job.address)
            if customer.phone:
                send_driver_assigned_sms(customer.phone, driver_name, job.address)
        # Push to driver: new job assigned
        send_push_notification(
            contractor.user_id, "New Job Assigned",
            "New job assigned: {}".format(job.address or "an address"),
            {"job_id": job.id},
        )
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).exception("Notification failed for job %s: %s", job.id, e)

    # Broadcast via SocketIO
    from socket_events import broadcast_job_status, socketio
    broadcast_job_status(job.id, "assigned", {"driver_id": contractor.id})

    socketio.emit("job:assigned", {
        "job_id": job.id,
        "contractor_id": contractor.id,
        "contractor_name": contractor.user.name if contractor.user else None,
    }, room="driver:{}".format(contractor.id))

    return jsonify({"success": True, "job": job.to_dict()}), 200


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@operator_bp.route("/notifications", methods=["GET"])
@require_operator
def list_notifications(user_id, operator):
    """List unread notifications for this operator (most recent first)."""
    limit = request.args.get("limit", 20, type=int)
    include_read = request.args.get("include_read", "false").lower() == "true"

    query = Notification.query.filter_by(user_id=user_id)
    if not include_read:
        query = query.filter_by(is_read=False)

    notifications = (
        query.order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )

    unread_count = Notification.query.filter_by(user_id=user_id, is_read=False).count()

    return jsonify({
        "success": True,
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": unread_count,
    }), 200


@operator_bp.route("/notifications/<notification_id>/read", methods=["PUT"])
@require_operator
def mark_notification_read(user_id, operator, notification_id):
    """Mark a single notification as read."""
    notification = db.session.get(Notification, notification_id)
    if not notification or notification.user_id != user_id:
        return jsonify({"error": "Notification not found"}), 404

    notification.is_read = True
    db.session.commit()

    return jsonify({"success": True}), 200


@operator_bp.route("/notifications/read-all", methods=["PUT"])
@require_operator
def mark_all_notifications_read(user_id, operator):
    """Mark all notifications for this operator as read."""
    Notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})
    db.session.commit()

    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------

@operator_bp.route("/earnings", methods=["GET"])
@require_operator
def earnings(user_id, operator):
    """Operator commission earnings."""
    now = utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    fleet = Contractor.query.filter_by(operator_id=operator.id).all()
    fleet_ids = [c.id for c in fleet]

    if not fleet_ids:
        return jsonify({
            "success": True,
            "earnings": {
                "total": 0.0,
                "earnings_30d": 0.0,
                "earnings_7d": 0.0,
                "per_contractor": [],
            },
        }), 200

    all_payments = (
        Payment.query
        .join(Job, Payment.job_id == Job.id)
        .filter(
            Job.operator_id == operator.id,
            Job.driver_id.in_(fleet_ids),
            Payment.payment_status == "succeeded",
        )
        .all()
    )

    total = sum(p.operator_payout_amount or 0.0 for p in all_payments)
    e_30d = sum(
        p.operator_payout_amount or 0.0 for p in all_payments
        if p.created_at and p.created_at >= thirty_days_ago
    )
    e_7d = sum(
        p.operator_payout_amount or 0.0 for p in all_payments
        if p.created_at and p.created_at >= seven_days_ago
    )

    # Per-contractor breakdown
    contractor_map = {c.id: c for c in fleet}
    per_contractor = {}
    for p in all_payments:
        job = db.session.get(Job, p.job_id)
        if job and job.driver_id:
            if job.driver_id not in per_contractor:
                c = contractor_map.get(job.driver_id)
                per_contractor[job.driver_id] = {
                    "contractor_id": job.driver_id,
                    "name": c.user.name if c and c.user else None,
                    "commission": 0.0,
                    "jobs": 0,
                }
            per_contractor[job.driver_id]["commission"] += p.operator_payout_amount or 0.0
            per_contractor[job.driver_id]["jobs"] += 1

    return jsonify({
        "success": True,
        "earnings": {
            "total": round(total, 2),
            "earnings_30d": round(e_30d, 2),
            "earnings_7d": round(e_7d, 2),
            "per_contractor": list(per_contractor.values()),
        },
    }), 200


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@operator_bp.route("/analytics", methods=["GET"])
@require_operator
def analytics(user_id, operator):
    """Operator analytics: weekly earnings, daily jobs, per-contractor stats, delegation time."""
    from sqlalchemy import func, case

    now = utcnow()
    twelve_weeks_ago = now - timedelta(weeks=12)
    thirty_days_ago = now - timedelta(days=30)

    fleet = Contractor.query.filter_by(operator_id=operator.id).all()
    fleet_ids = [c.id for c in fleet]
    contractor_map = {c.id: c for c in fleet}

    # ---- earnings_by_week: last 12 weeks of commission ----
    earnings_by_week = []
    if fleet_ids:
        payments = (
            Payment.query
            .join(Job, Payment.job_id == Job.id)
            .filter(
                Job.operator_id == operator.id,
                Job.driver_id.in_(fleet_ids),
                Payment.payment_status == "succeeded",
                Payment.created_at >= twelve_weeks_ago,
            )
            .all()
        )
        # Bucket by ISO week
        week_buckets = {}
        for p in payments:
            if p.created_at:
                # Monday of that week
                week_start = (p.created_at - timedelta(days=p.created_at.weekday())).strftime("%Y-%m-%d")
                week_buckets[week_start] = week_buckets.get(week_start, 0.0) + (p.operator_payout_amount or 0.0)

        # Build ordered list for the last 12 weeks
        for i in range(11, -1, -1):
            d = now - timedelta(weeks=i)
            week_start = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
            earnings_by_week.append({
                "week_start": week_start,
                "amount": round(week_buckets.get(week_start, 0.0), 2),
            })
        # Deduplicate (keep last occurrence per week_start)
        seen = {}
        deduped = []
        for entry in earnings_by_week:
            seen[entry["week_start"]] = entry
        for entry in earnings_by_week:
            if entry["week_start"] in seen:
                deduped.append(seen.pop(entry["week_start"]))
        earnings_by_week = deduped

    # ---- jobs_by_day: last 30 days of delegated jobs ----
    jobs_by_day = []
    day_buckets = {}
    operator_jobs_30d = (
        Job.query
        .filter(
            Job.operator_id == operator.id,
            Job.created_at >= thirty_days_ago,
        )
        .all()
    )
    for j in operator_jobs_30d:
        if j.created_at:
            day_key = j.created_at.strftime("%Y-%m-%d")
            day_buckets[day_key] = day_buckets.get(day_key, 0) + 1

    for i in range(29, -1, -1):
        d = now - timedelta(days=i)
        day_key = d.strftime("%Y-%m-%d")
        jobs_by_day.append({
            "date": day_key,
            "count": day_buckets.get(day_key, 0),
        })

    # ---- per_contractor_jobs ----
    per_contractor_jobs = []
    if fleet_ids:
        for cid in fleet_ids:
            c = contractor_map[cid]
            job_count = Job.query.filter(
                Job.operator_id == operator.id,
                Job.driver_id == cid,
            ).count()
            commission = 0.0
            c_payments = (
                Payment.query
                .join(Job, Payment.job_id == Job.id)
                .filter(
                    Job.operator_id == operator.id,
                    Job.driver_id == cid,
                    Payment.payment_status == "succeeded",
                )
                .all()
            )
            commission = sum(p.operator_payout_amount or 0.0 for p in c_payments)
            per_contractor_jobs.append({
                "contractor_id": cid,
                "name": c.user.name if c.user else None,
                "jobs": job_count,
                "commission": round(commission, 2),
            })

    # ---- delegation_time_avg: avg minutes from delegating->assigned ----
    delegation_time_avg = None
    delegated_jobs = (
        Job.query
        .filter(
            Job.operator_id == operator.id,
            Job.delegated_at.isnot(None),
            Job.created_at.isnot(None),
        )
        .all()
    )
    if delegated_jobs:
        deltas = []
        for j in delegated_jobs:
            if j.delegated_at and j.created_at:
                diff = (j.delegated_at - j.created_at).total_seconds() / 60.0
                if diff >= 0:
                    deltas.append(diff)
        if deltas:
            delegation_time_avg = round(sum(deltas) / len(deltas), 1)

    return jsonify({
        "success": True,
        "analytics": {
            "earnings_by_week": earnings_by_week,
            "jobs_by_day": jobs_by_day,
            "per_contractor_jobs": per_contractor_jobs,
            "delegation_time_avg": delegation_time_avg,
        },
    }), 200
