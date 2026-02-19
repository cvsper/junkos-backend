"""
Driver Onboarding API routes for Umuve.
Handles the driver onboarding pipeline: document upload, submission, and admin review.
"""

import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from functools import wraps
from werkzeug.utils import secure_filename

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    db, User, Contractor, Notification, generate_uuid, utcnow,
)
from auth_routes import require_auth

onboarding_bp = Blueprint("onboarding", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"
)


def _allowed_file(filename):
    """Check if a filename has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ensure_upload_dir():
    """Create the uploads directory if it does not exist."""
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _get_contractor_or_404(user_id):
    """Look up the Contractor record for the authenticated user."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return None, (jsonify({"error": "Driver profile not found"}), 404)
    return contractor, None


def require_admin(f):
    """Wrap require_auth and additionally check that the user has admin role."""
    @wraps(f)
    @require_auth
    def wrapper(user_id, *args, **kwargs):
        user = db.session.get(User, user_id)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(user_id=user_id, *args, **kwargs)
    return wrapper


# ===========================================================================
# Driver Endpoints
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/drivers/onboarding/status
# ---------------------------------------------------------------------------
@onboarding_bp.route("/api/drivers/onboarding/status", methods=["GET"])
@require_auth
def get_onboarding_status(user_id):
    """Get current onboarding status and checklist for the authenticated driver."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    checklist = {
        "insurance_uploaded": bool(contractor.insurance_document_url),
        "drivers_license_uploaded": bool(contractor.drivers_license_url),
        "vehicle_registration_uploaded": bool(contractor.vehicle_registration_url),
        "insurance_expiry_set": bool(contractor.insurance_expiry),
        "license_expiry_set": bool(contractor.license_expiry),
        "documents_submitted": contractor.onboarding_status in (
            "documents_submitted", "under_review", "approved",
        ),
        "background_check_passed": contractor.background_check_status == "passed",
    }

    all_docs_uploaded = (
        checklist["insurance_uploaded"]
        and checklist["drivers_license_uploaded"]
        and checklist["vehicle_registration_uploaded"]
    )

    return jsonify({
        "success": True,
        "onboarding_status": contractor.onboarding_status or "pending",
        "background_check_status": contractor.background_check_status or "not_started",
        "rejection_reason": contractor.rejection_reason,
        "onboarding_completed_at": (
            contractor.onboarding_completed_at.isoformat()
            if contractor.onboarding_completed_at else None
        ),
        "checklist": checklist,
        "can_submit": all_docs_uploaded and contractor.onboarding_status == "pending",
        "documents": {
            "insurance_document_url": contractor.insurance_document_url,
            "drivers_license_url": contractor.drivers_license_url,
            "vehicle_registration_url": contractor.vehicle_registration_url,
            "insurance_expiry": (
                contractor.insurance_expiry.isoformat()
                if contractor.insurance_expiry else None
            ),
            "license_expiry": (
                contractor.license_expiry.isoformat()
                if contractor.license_expiry else None
            ),
        },
    }), 200


# ---------------------------------------------------------------------------
# POST /api/drivers/onboarding/documents
# ---------------------------------------------------------------------------
@onboarding_bp.route("/api/drivers/onboarding/documents", methods=["POST"])
@require_auth
def upload_onboarding_documents(user_id):
    """
    Upload onboarding documents (insurance, license, registration).

    Accepts multipart/form-data with optional fields:
        - insurance (file)
        - drivers_license (file)
        - vehicle_registration (file)
        - insurance_expiry (string, ISO date)
        - license_expiry (string, ISO date)
    """
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    if contractor.onboarding_status in ("approved",):
        return jsonify({"error": "Onboarding already completed"}), 409

    _ensure_upload_dir()
    uploaded = {}
    errors = []

    # Process each document type
    for field_name, url_attr in [
        ("insurance", "insurance_document_url"),
        ("drivers_license", "drivers_license_url"),
        ("vehicle_registration", "vehicle_registration_url"),
    ]:
        if field_name in request.files:
            file = request.files[field_name]
            if not file or not file.filename:
                errors.append({"field": field_name, "error": "Empty file"})
                continue

            if not _allowed_file(file.filename):
                errors.append({
                    "field": field_name,
                    "error": "File type not allowed. Accepted: jpg, png, webp, pdf",
                })
                continue

            # Check file size
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > MAX_FILE_SIZE:
                errors.append({
                    "field": field_name,
                    "error": "File exceeds maximum size of 10 MB",
                })
                continue

            ext = file.filename.rsplit(".", 1)[1].lower()
            unique_name = "{}.{}".format(generate_uuid(), ext)
            safe_name = secure_filename(unique_name)
            filepath = os.path.join(UPLOAD_FOLDER, safe_name)
            file.save(filepath)

            url = "/uploads/{}".format(safe_name)
            setattr(contractor, url_attr, url)
            uploaded[field_name] = url

    # Process expiry dates from form data
    insurance_expiry = request.form.get("insurance_expiry")
    if insurance_expiry:
        try:
            contractor.insurance_expiry = datetime.fromisoformat(
                insurance_expiry.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            errors.append({"field": "insurance_expiry", "error": "Invalid date format"})

    license_expiry = request.form.get("license_expiry")
    if license_expiry:
        try:
            contractor.license_expiry = datetime.fromisoformat(
                license_expiry.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            errors.append({"field": "license_expiry", "error": "Invalid date format"})

    # If the driver was previously rejected, reset to pending so they can re-submit
    if contractor.onboarding_status == "rejected":
        contractor.onboarding_status = "pending"
        contractor.rejection_reason = None

    contractor.updated_at = utcnow()
    db.session.commit()

    response = {
        "success": True,
        "uploaded": uploaded,
        "documents": {
            "insurance_document_url": contractor.insurance_document_url,
            "drivers_license_url": contractor.drivers_license_url,
            "vehicle_registration_url": contractor.vehicle_registration_url,
            "insurance_expiry": (
                contractor.insurance_expiry.isoformat()
                if contractor.insurance_expiry else None
            ),
            "license_expiry": (
                contractor.license_expiry.isoformat()
                if contractor.license_expiry else None
            ),
        },
    }
    if errors:
        response["errors"] = errors

    return jsonify(response), 200


# ---------------------------------------------------------------------------
# POST /api/drivers/onboarding/submit
# ---------------------------------------------------------------------------
@onboarding_bp.route("/api/drivers/onboarding/submit", methods=["POST"])
@require_auth
def submit_for_review(user_id):
    """Submit onboarding for admin review. Moves status to documents_submitted."""
    contractor, err = _get_contractor_or_404(user_id)
    if err:
        return err

    if contractor.onboarding_status not in ("pending", "rejected"):
        return jsonify({
            "error": "Cannot submit in current status: {}".format(
                contractor.onboarding_status
            ),
        }), 409

    # Validate that all required documents are uploaded
    missing = []
    if not contractor.insurance_document_url:
        missing.append("insurance")
    if not contractor.drivers_license_url:
        missing.append("drivers_license")
    if not contractor.vehicle_registration_url:
        missing.append("vehicle_registration")

    if missing:
        return jsonify({
            "error": "Missing required documents: {}".format(", ".join(missing)),
            "missing_documents": missing,
        }), 400

    contractor.onboarding_status = "documents_submitted"
    contractor.rejection_reason = None
    contractor.updated_at = utcnow()

    # Notify all admins about new submission
    admin_users = User.query.filter_by(role="admin").all()
    driver_name = contractor.user.name if contractor.user else "A driver"
    for admin in admin_users:
        notification = Notification(
            id=generate_uuid(),
            user_id=admin.id,
            type="onboarding_submission",
            title="New Onboarding Submission",
            body="{} has submitted onboarding documents for review.".format(driver_name),
            data={
                "contractor_id": contractor.id,
                "onboarding_status": "documents_submitted",
            },
        )
        db.session.add(notification)

    db.session.commit()

    return jsonify({
        "success": True,
        "onboarding_status": contractor.onboarding_status,
        "message": "Documents submitted for review",
    }), 200


# ===========================================================================
# Admin Endpoints
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/admin/onboarding/applications
# ---------------------------------------------------------------------------
@onboarding_bp.route("/api/admin/onboarding/applications", methods=["GET"])
@require_admin
def list_onboarding_applications(user_id):
    """List all contractors with onboarding status, filterable by status."""
    status_filter = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Contractor.query

    if status_filter:
        query = query.filter_by(onboarding_status=status_filter)

    pagination = query.order_by(
        Contractor.updated_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    applications = []
    for c in pagination.items:
        c_data = c.to_dict()
        user_obj = c_data.pop("user", None) or {}
        c_data["name"] = user_obj.get("name")
        c_data["email"] = user_obj.get("email")
        c_data["phone"] = user_obj.get("phone")
        applications.append(c_data)

    return jsonify({
        "success": True,
        "applications": applications,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/onboarding/<contractor_id>/review
# ---------------------------------------------------------------------------
@onboarding_bp.route("/api/admin/onboarding/<contractor_id>/review", methods=["PUT"])
@require_admin
def review_onboarding(user_id, contractor_id):
    """
    Approve or reject a contractor's onboarding application.

    Body JSON:
        action           (str, required) - "approve" or "reject"
        rejection_reason (str, optional) - reason for rejection (required if rejecting)
    """
    contractor = db.session.get(Contractor, contractor_id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    data = request.get_json() or {}
    action = data.get("action", "").lower()

    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400

    driver_name = contractor.user.name if contractor.user else "Driver"

    if action == "approve":
        contractor.onboarding_status = "approved"
        contractor.onboarding_completed_at = utcnow()
        contractor.rejection_reason = None
        # Also approve the contractor's general approval status
        contractor.approval_status = "approved"
        contractor.updated_at = utcnow()

        notification = Notification(
            id=generate_uuid(),
            user_id=contractor.user_id,
            type="onboarding_approved",
            title="Onboarding Approved!",
            body="Congratulations! Your onboarding has been approved. You can now go online and start accepting jobs.",
            data={
                "onboarding_status": "approved",
                "contractor_id": contractor.id,
            },
        )
        db.session.add(notification)

        # Send push notification
        try:
            from notifications import send_push_notification
            send_push_notification(
                contractor.user_id,
                "Onboarding Approved!",
                "Your onboarding has been approved. You can now accept jobs.",
                {"type": "onboarding_approved", "contractor_id": contractor.id},
            )
        except Exception:
            pass  # Push notification failures must not block the main flow

    elif action == "reject":
        rejection_reason = data.get("rejection_reason", "").strip()
        if not rejection_reason:
            return jsonify({"error": "rejection_reason is required when rejecting"}), 400

        contractor.onboarding_status = "rejected"
        contractor.rejection_reason = rejection_reason
        contractor.onboarding_completed_at = None
        contractor.updated_at = utcnow()

        notification = Notification(
            id=generate_uuid(),
            user_id=contractor.user_id,
            type="onboarding_rejected",
            title="Onboarding Update",
            body="Your onboarding application was not approved. Reason: {}".format(
                rejection_reason
            ),
            data={
                "onboarding_status": "rejected",
                "contractor_id": contractor.id,
                "rejection_reason": rejection_reason,
            },
        )
        db.session.add(notification)

        # Send push notification
        try:
            from notifications import send_push_notification
            send_push_notification(
                contractor.user_id,
                "Onboarding Update",
                "Your application needs attention. Please check the app for details.",
                {"type": "onboarding_rejected", "contractor_id": contractor.id},
            )
        except Exception:
            pass

    db.session.commit()

    c_data = contractor.to_dict()
    user_obj = c_data.pop("user", None) or {}
    c_data["name"] = user_obj.get("name")
    c_data["email"] = user_obj.get("email")
    c_data["phone"] = user_obj.get("phone")

    return jsonify({
        "success": True,
        "contractor": c_data,
        "action": action,
    }), 200
