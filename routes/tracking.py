"""
Customer-facing tracking API routes for Umuve.
Public endpoints for real-time job status and driver location tracking.
"""

from flask import Blueprint, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, Job, Contractor, User

tracking_bp = Blueprint("tracking", __name__, url_prefix="/api/tracking")


@tracking_bp.route("/<job_id>", methods=["GET"])
def get_tracking_info(job_id):
    """
    Public tracking endpoint for customers.
    Returns job status, driver info (if assigned), and driver location.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Booking not found"}), 404

    result = {
        "job_id": job.id,
        "status": job.status,
        "address": job.address,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "total_price": job.total_price,
        "items": job.items or [],
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }

    # Include driver info if assigned
    if job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor:
            result["driver"] = {
                "id": contractor.id,
                "name": contractor.user.name if contractor.user else None,
                "truck_type": contractor.truck_type,
                "avg_rating": contractor.avg_rating,
                "total_jobs": contractor.total_jobs,
                "lat": contractor.current_lat,
                "lng": contractor.current_lng,
            }
        else:
            result["driver"] = None
    else:
        result["driver"] = None

    # Include payment status
    if job.payment:
        result["payment_status"] = job.payment.payment_status
    else:
        result["payment_status"] = None

    return jsonify({"success": True, "tracking": result}), 200


@tracking_bp.route("/<job_id>/driver-location", methods=["GET"])
def get_driver_location(job_id):
    """
    Get the current driver location for a job.
    Returns lat/lng if a driver is assigned and has a known location.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if not job.driver_id:
        return jsonify({"success": True, "location": None, "message": "No driver assigned yet"}), 200

    contractor = db.session.get(Contractor, job.driver_id)
    if not contractor or contractor.current_lat is None:
        return jsonify({"success": True, "location": None, "message": "Driver location unavailable"}), 200

    return jsonify({
        "success": True,
        "location": {
            "lat": contractor.current_lat,
            "lng": contractor.current_lng,
            "driver_name": contractor.user.name if contractor.user else None,
            "status": job.status,
        },
    }), 200
