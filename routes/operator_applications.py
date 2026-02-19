"""
Operator Applications API routes for Umuve.
Handles the public operator application form and admin review workflow.
"""

import os
import logging
from functools import wraps

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    db, User, Contractor, OperatorApplication, generate_uuid, utcnow,
)
from auth_routes import require_auth
from notifications import send_email

logger = logging.getLogger(__name__)

operator_applications_bp = Blueprint("operator_applications", __name__)


# ---------------------------------------------------------------------------
# Admin decorator (same pattern as onboarding.py)
# ---------------------------------------------------------------------------
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
# Public Endpoint
# ===========================================================================

# ---------------------------------------------------------------------------
# POST /api/operator-applications
# ---------------------------------------------------------------------------
@operator_applications_bp.route("/api/operator-applications", methods=["POST"])
def submit_operator_application():
    """Submit a new operator application from the landing page form.

    No authentication required. Accepts JSON body with applicant details.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Validate required fields
    required_fields = ["first_name", "last_name", "email", "phone", "city"]
    missing = [f for f in required_fields if not data.get(f, "").strip()]
    if missing:
        return jsonify({
            "error": "Missing required fields: {}".format(", ".join(missing)),
            "missing_fields": missing,
        }), 400

    email = data["email"].strip().lower()

    # Check for duplicate email
    existing = OperatorApplication.query.filter_by(email=email).first()
    if existing:
        return jsonify({
            "error": "An application with this email already exists",
        }), 409

    # Create the application record
    application = OperatorApplication(
        id=generate_uuid(),
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        email=email,
        phone=data["phone"].strip(),
        city=data["city"].strip(),
        trucks=data.get("trucks", "").strip() or None,
        experience=data.get("experience", "").strip() or None,
        status="pending",
    )
    db.session.add(application)
    db.session.commit()

    # Send confirmation email to applicant
    applicant_name = "{} {}".format(application.first_name, application.last_name)
    try:
        send_email(
            to_email=email,
            subject="Umuve Operator Application Received",
            html_content=(
                '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px;">'
                '<h2 style="color: #111; margin-bottom: 16px;">Application Received!</h2>'
                '<p style="color: #444; line-height: 1.6;">Hi {name},</p>'
                '<p style="color: #444; line-height: 1.6;">'
                'Thank you for applying to become an Umuve operator. We have received your application '
                'and our team will review it within 24 hours.'
                '</p>'
                '<p style="color: #444; line-height: 1.6;">'
                'We will send you an email once your application has been reviewed.'
                '</p>'
                '<p style="color: #888; font-size: 14px; margin-top: 32px;">'
                '&mdash; The Umuve Team'
                '</p>'
                '</div>'
            ).format(name=application.first_name),
        )
    except Exception:
        logger.exception("Failed to send applicant confirmation email to %s", email)

    # Send notification email to admins
    try:
        admin_users = User.query.filter_by(role="admin").all()
        for admin in admin_users:
            if admin.email:
                send_email(
                    to_email=admin.email,
                    subject="New Operator Application: {} {}".format(
                        application.first_name, application.last_name
                    ),
                    html_content=(
                        '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px;">'
                        '<h2 style="color: #111; margin-bottom: 16px;">New Operator Application</h2>'
                        '<table style="width: 100%; border-collapse: collapse; margin: 16px 0;">'
                        '<tr><td style="padding: 8px 0; color: #888;">Name</td><td style="padding: 8px 0; color: #111;">{first} {last}</td></tr>'
                        '<tr><td style="padding: 8px 0; color: #888;">Email</td><td style="padding: 8px 0; color: #111;">{email}</td></tr>'
                        '<tr><td style="padding: 8px 0; color: #888;">Phone</td><td style="padding: 8px 0; color: #111;">{phone}</td></tr>'
                        '<tr><td style="padding: 8px 0; color: #888;">City</td><td style="padding: 8px 0; color: #111;">{city}</td></tr>'
                        '<tr><td style="padding: 8px 0; color: #888;">Trucks</td><td style="padding: 8px 0; color: #111;">{trucks}</td></tr>'
                        '<tr><td style="padding: 8px 0; color: #888;">Experience</td><td style="padding: 8px 0; color: #111;">{experience}</td></tr>'
                        '</table>'
                        '<p style="color: #444; line-height: 1.6;">'
                        'Review this application in the admin dashboard.'
                        '</p>'
                        '</div>'
                    ).format(
                        first=application.first_name,
                        last=application.last_name,
                        email=application.email,
                        phone=application.phone,
                        city=application.city,
                        trucks=application.trucks or "N/A",
                        experience=application.experience or "N/A",
                    ),
                )
    except Exception:
        logger.exception("Failed to send admin notification email for application %s", application.id)

    return jsonify({
        "success": True,
        "message": "Application submitted successfully",
        "application": application.to_dict(),
    }), 201


# ===========================================================================
# Admin Endpoints
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/admin/operator-applications
# ---------------------------------------------------------------------------
@operator_applications_bp.route("/api/admin/operator-applications", methods=["GET"])
@require_admin
def list_operator_applications(user_id):
    """List all operator applications with pagination and optional status filter."""
    status_filter = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = OperatorApplication.query

    if status_filter:
        query = query.filter_by(status=status_filter)

    pagination = query.order_by(
        OperatorApplication.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "success": True,
        "applications": [app.to_dict() for app in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/operator-applications/<app_id>/review
# ---------------------------------------------------------------------------
@operator_applications_bp.route(
    "/api/admin/operator-applications/<app_id>/review", methods=["PUT"]
)
@require_admin
def review_operator_application(user_id, app_id):
    """Approve or reject an operator application.

    Body JSON:
        action           (str, required) - "approve" or "reject"
        rejection_reason (str, optional) - reason for rejection (required if rejecting)
        notes            (str, optional) - internal admin notes
    """
    application = db.session.get(OperatorApplication, app_id)
    if not application:
        return jsonify({"error": "Application not found"}), 404

    data = request.get_json() or {}
    action = data.get("action", "").lower()

    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400

    # Allow admin to attach notes regardless of action
    if data.get("notes"):
        application.notes = data["notes"].strip()

    applicant_name = "{} {}".format(application.first_name, application.last_name)

    if action == "approve":
        application.status = "approved"
        application.rejection_reason = None
        application.updated_at = utcnow()

        # Create User record for the new operator
        existing_user = User.query.filter_by(email=application.email).first()
        if existing_user:
            user = existing_user
            # Upgrade role to operator if not already
            if user.role not in ("admin",):
                user.role = "operator"
        else:
            user = User(
                id=generate_uuid(),
                email=application.email,
                phone=application.phone,
                name=applicant_name,
                role="operator",
                status="active",
            )
            db.session.add(user)
            db.session.flush()

        # Create Contractor record with is_operator=True
        existing_contractor = Contractor.query.filter_by(user_id=user.id).first()
        if existing_contractor:
            existing_contractor.is_operator = True
            existing_contractor.approval_status = "approved"
            existing_contractor.updated_at = utcnow()
        else:
            contractor = Contractor(
                id=generate_uuid(),
                user_id=user.id,
                is_operator=True,
                approval_status="approved",
                onboarding_status="approved",
                onboarding_completed_at=utcnow(),
            )
            db.session.add(contractor)

        # Send approval email
        try:
            send_email(
                to_email=application.email,
                subject="Welcome to Umuve - Application Approved!",
                html_content=(
                    '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px;">'
                    '<h2 style="color: #111; margin-bottom: 16px;">You are Approved!</h2>'
                    '<p style="color: #444; line-height: 1.6;">Hi {name},</p>'
                    '<p style="color: #444; line-height: 1.6;">'
                    'Great news! Your Umuve operator application has been approved. '
                    'You can now log in and start managing your fleet.'
                    '</p>'
                    '<p style="color: #444; line-height: 1.6;">'
                    'Download the Umuve app or visit our platform to get started. '
                    'If you have any questions, just reply to this email.'
                    '</p>'
                    '<p style="color: #888; font-size: 14px; margin-top: 32px;">'
                    '&mdash; The Umuve Team'
                    '</p>'
                    '</div>'
                ).format(name=application.first_name),
            )
        except Exception:
            logger.exception("Failed to send approval email to %s", application.email)

    elif action == "reject":
        rejection_reason = data.get("rejection_reason", "").strip()
        if not rejection_reason:
            return jsonify({"error": "rejection_reason is required when rejecting"}), 400

        application.status = "rejected"
        application.rejection_reason = rejection_reason
        application.updated_at = utcnow()

        # Send rejection email
        try:
            send_email(
                to_email=application.email,
                subject="Umuve Operator Application Update",
                html_content=(
                    '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px;">'
                    '<h2 style="color: #111; margin-bottom: 16px;">Application Update</h2>'
                    '<p style="color: #444; line-height: 1.6;">Hi {name},</p>'
                    '<p style="color: #444; line-height: 1.6;">'
                    'Thank you for your interest in becoming an Umuve operator. '
                    'After reviewing your application, we are unable to approve it at this time.'
                    '</p>'
                    '<p style="color: #444; line-height: 1.6;">'
                    '<strong>Reason:</strong> {reason}'
                    '</p>'
                    '<p style="color: #444; line-height: 1.6;">'
                    'If you believe this was in error or your circumstances have changed, '
                    'feel free to reapply or reply to this email.'
                    '</p>'
                    '<p style="color: #888; font-size: 14px; margin-top: 32px;">'
                    '&mdash; The Umuve Team'
                    '</p>'
                    '</div>'
                ).format(name=application.first_name, reason=rejection_reason),
            )
        except Exception:
            logger.exception("Failed to send rejection email to %s", application.email)

    db.session.commit()

    return jsonify({
        "success": True,
        "application": application.to_dict(),
        "action": action,
    }), 200
