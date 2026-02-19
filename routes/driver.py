"""
Driver API routes for Umuve.
Provides earnings, payouts, profile, and stats for authenticated drivers.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import func

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, Contractor, Job, Payment, utcnow
from auth_routes import require_auth

driver_bp = Blueprint("driver", __name__, url_prefix="/api/driver")

PLATFORM_COMMISSION_RATE = 0.20  # 20% platform commission, 80% to driver


def _get_contractor_or_404(user_id):
    """Look up the Contractor record for the authenticated user.

    Returns (contractor, None) on success or (None, error_response) if not found.
    """
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found"}), 404)

    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return None, (jsonify({"error": "Driver profile not found"}), 404)

    return contractor, None


# ---------------------------------------------------------------------------
# GET /api/driver/earnings
# ---------------------------------------------------------------------------
@driver_bp.route("/earnings", methods=["GET"])
@require_auth
def earnings(user_id):
    """Return an earnings summary for the authenticated driver."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    try:
        # All completed jobs for this driver
        completed_jobs = (
            Job.query
            .filter_by(driver_id=contractor.id, status="completed")
            .all()
        )

        total_earned = 0.0
        total_jobs = len(completed_jobs)

        weekly_map = defaultdict(lambda: {"amount": 0.0, "jobs": 0})
        monthly_map = defaultdict(lambda: {"amount": 0.0, "jobs": 0})

        for job in completed_jobs:
            driver_payout = round(job.total_price * (1 - PLATFORM_COMMISSION_RATE), 2)
            total_earned += driver_payout

            completed_dt = job.completed_at or job.updated_at or job.created_at
            if completed_dt:
                # Weekly bucket (ISO week start = Monday)
                week_start = completed_dt - timedelta(days=completed_dt.weekday())
                week_key = week_start.strftime("%Y-%m-%d")
                weekly_map[week_key]["amount"] += driver_payout
                weekly_map[week_key]["jobs"] += 1

                # Monthly bucket
                month_key = completed_dt.strftime("%Y-%m")
                monthly_map[month_key]["amount"] += driver_payout
                monthly_map[month_key]["jobs"] += 1

        total_earned = round(total_earned, 2)
        avg_per_job = round(total_earned / total_jobs, 2) if total_jobs > 0 else 0.0

        # Pending payout: driver_payout_amount from payments where payout_status is pending
        pending_payout_result = (
            db.session.query(func.coalesce(func.sum(Payment.driver_payout_amount), 0.0))
            .join(Job, Job.id == Payment.job_id)
            .filter(
                Job.driver_id == contractor.id,
                Job.status == "completed",
                Payment.payment_status == "succeeded",
                Payment.payout_status == "pending",
            )
            .scalar()
        )
        pending_payout = round(float(pending_payout_result), 2)

        # Last payout date: most recent payment where payout_status is 'paid'
        last_paid_payment = (
            Payment.query
            .join(Job, Job.id == Payment.job_id)
            .filter(
                Job.driver_id == contractor.id,
                Payment.payout_status == "paid",
            )
            .order_by(Payment.updated_at.desc())
            .first()
        )
        last_payout_date = None
        if last_paid_payment and last_paid_payment.updated_at:
            last_payout_date = last_paid_payment.updated_at.isoformat()

        # Build sorted weekly list (most recent first)
        weekly = sorted(
            [{"week": k, "amount": round(v["amount"], 2), "jobs": v["jobs"]} for k, v in weekly_map.items()],
            key=lambda x: x["week"],
            reverse=True,
        )

        # Build sorted monthly list (most recent first)
        monthly = sorted(
            [{"month": k, "amount": round(v["amount"], 2), "jobs": v["jobs"]} for k, v in monthly_map.items()],
            key=lambda x: x["month"],
            reverse=True,
        )

        return jsonify({
            "success": True,
            "earnings": {
                "total_earned": total_earned,
                "total_jobs": total_jobs,
                "avg_per_job": avg_per_job,
                "pending_payout": pending_payout,
                "last_payout_date": last_payout_date,
                "weekly": weekly,
                "monthly": monthly,
            },
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/driver/earnings/history
# ---------------------------------------------------------------------------
@driver_bp.route("/earnings/history", methods=["GET"])
@require_auth
def earnings_history(user_id):
    """Return a paginated list of completed jobs with earnings breakdown."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        pagination = (
            Job.query
            .filter_by(driver_id=contractor.id, status="completed")
            .order_by(Job.completed_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

        jobs = []
        for job in pagination.items:
            commission = round(job.total_price * PLATFORM_COMMISSION_RATE, 2)
            driver_payout = round(job.total_price - commission, 2)
            jobs.append({
                "id": job.id,
                "address": job.address,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "total_price": job.total_price,
                "commission": commission,
                "driver_payout": driver_payout,
                "status": job.status,
            })

        return jsonify({
            "success": True,
            "jobs": jobs,
            "total": pagination.total,
            "page": pagination.page,
            "per_page": per_page,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/driver/profile
# ---------------------------------------------------------------------------
@driver_bp.route("/profile", methods=["GET"])
@require_auth
def get_profile(user_id):
    """Return the driver's contractor profile."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    try:
        user = contractor.user

        profile = {
            "id": contractor.id,
            "name": user.name if user else None,
            "email": user.email if user else None,
            "phone": user.phone if user else None,
            "vehicle_type": contractor.truck_type,
            "rating": contractor.avg_rating,
            "total_jobs": contractor.total_jobs,
            "status": contractor.approval_status,
            "created_at": contractor.created_at.isoformat() if contractor.created_at else None,
        }

        return jsonify({"success": True, "profile": profile}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/driver/profile
# ---------------------------------------------------------------------------
@driver_bp.route("/profile", methods=["PUT"])
@require_auth
def update_profile(user_id):
    """Update the driver's profile fields (name, phone, vehicle_type)."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    try:
        data = request.get_json() or {}
        user = contractor.user

        if "name" in data and user:
            user.name = data["name"]
            user.updated_at = utcnow()

        if "phone" in data and user:
            user.phone = data["phone"]
            user.updated_at = utcnow()

        if "vehicle_type" in data:
            contractor.truck_type = data["vehicle_type"]
            contractor.updated_at = utcnow()

        db.session.commit()

        profile = {
            "id": contractor.id,
            "name": user.name if user else None,
            "email": user.email if user else None,
            "phone": user.phone if user else None,
            "vehicle_type": contractor.truck_type,
            "rating": contractor.avg_rating,
            "total_jobs": contractor.total_jobs,
            "status": contractor.approval_status,
            "created_at": contractor.created_at.isoformat() if contractor.created_at else None,
        }

        return jsonify({"success": True, "profile": profile}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/driver/stats
# ---------------------------------------------------------------------------
@driver_bp.route("/stats", methods=["GET"])
@require_auth
def stats(user_id):
    """Return driver performance stats."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    try:
        now = utcnow()

        # Total jobs assigned to this driver (any status)
        total_jobs = Job.query.filter_by(driver_id=contractor.id).count()

        # Completed jobs
        completed_jobs = Job.query.filter_by(driver_id=contractor.id, status="completed").count()

        # Acceptance rate: completed / total (excluding cancelled by customer)
        # For a simple calculation: completed / total assigned
        acceptance_rate = round(completed_jobs / total_jobs, 2) if total_jobs > 0 else 0.0

        # Total earned
        all_completed = (
            Job.query
            .filter_by(driver_id=contractor.id, status="completed")
            .all()
        )
        total_earned = round(
            sum(j.total_price * (1 - PLATFORM_COMMISSION_RATE) for j in all_completed), 2
        )

        # This week earned (Monday through now)
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        this_week_jobs = (
            Job.query
            .filter(
                Job.driver_id == contractor.id,
                Job.status == "completed",
                Job.completed_at >= week_start,
            )
            .all()
        )
        this_week_earned = round(
            sum(j.total_price * (1 - PLATFORM_COMMISSION_RATE) for j in this_week_jobs), 2
        )

        # This month earned
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month_jobs = (
            Job.query
            .filter(
                Job.driver_id == contractor.id,
                Job.status == "completed",
                Job.completed_at >= month_start,
            )
            .all()
        )
        this_month_earned = round(
            sum(j.total_price * (1 - PLATFORM_COMMISSION_RATE) for j in this_month_jobs), 2
        )

        return jsonify({
            "success": True,
            "stats": {
                "total_jobs": total_jobs,
                "completed_jobs": completed_jobs,
                "rating": contractor.avg_rating,
                "acceptance_rate": acceptance_rate,
                "total_earned": total_earned,
                "this_week_earned": this_week_earned,
                "this_month_earned": this_month_earned,
            },
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
