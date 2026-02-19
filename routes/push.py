"""
Push Notification API Routes

Endpoints for registering/unregistering APNs device tokens and
sending test push notifications.
"""

import logging
import os

from flask import Blueprint, request, jsonify

from auth_routes import require_auth
from models import db, DeviceToken
from push_notifications import send_push_notification

logger = logging.getLogger(__name__)

push_bp = Blueprint("push", __name__, url_prefix="/api/push")


# ---------------------------------------------------------------------------
# POST /api/push/register-token
# ---------------------------------------------------------------------------
@push_bp.route("/register-token", methods=["POST"])
@require_auth
def register_token(user_id):
    """Register an APNs (or FCM) device token for the authenticated user.

    Body JSON:
        token    (str, required) - the device token hex string
        platform (str, optional) - "ios" (default) or "android"
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    platform = data.get("platform", "ios").strip().lower()

    if not token:
        return jsonify({"error": "token is required"}), 400

    if platform not in ("ios", "android"):
        return jsonify({"error": "platform must be 'ios' or 'android'"}), 400

    # Check if this exact token already exists
    existing = DeviceToken.query.filter_by(token=token).first()

    if existing:
        if existing.user_id == user_id and existing.platform == platform:
            # Already registered for this user -- nothing to do
            logger.info("Device token already registered: user=%s token=%s...", user_id, token[:12])
            return jsonify({"success": True, "device_token": existing.to_dict()}), 200

        # Token exists but belongs to a different user (e.g. the user logged
        # out and a new user logged in on the same device).  Re-assign it.
        logger.info(
            "Re-assigning device token from user=%s to user=%s token=%s...",
            existing.user_id,
            user_id,
            token[:12],
        )
        existing.user_id = user_id
        existing.platform = platform
        db.session.commit()
        return jsonify({"success": True, "device_token": existing.to_dict()}), 200

    # Create new device token record
    dt = DeviceToken(user_id=user_id, token=token, platform=platform)
    db.session.add(dt)
    db.session.commit()

    logger.info("Device token registered: user=%s platform=%s token=%s...", user_id, platform, token[:12])
    return jsonify({"success": True, "device_token": dt.to_dict()}), 201


# ---------------------------------------------------------------------------
# DELETE /api/push/unregister-token
# ---------------------------------------------------------------------------
@push_bp.route("/unregister-token", methods=["DELETE"])
@require_auth
def unregister_token(user_id):
    """Remove a device token for the authenticated user.

    Body JSON:
        token (str, required) - the device token to remove
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()

    if not token:
        return jsonify({"error": "token is required"}), 400

    dt = DeviceToken.query.filter_by(token=token, user_id=user_id).first()

    if not dt:
        return jsonify({"error": "Token not found"}), 404

    db.session.delete(dt)
    db.session.commit()

    logger.info("Device token unregistered: user=%s token=%s...", user_id, token[:12])
    return jsonify({"success": True, "message": "Token removed"}), 200


# ---------------------------------------------------------------------------
# GET /api/push/test  (development only)
# ---------------------------------------------------------------------------
@push_bp.route("/test", methods=["GET"])
@require_auth
def test_push(user_id):
    """Send a test push notification to the authenticated user.

    Only available when FLASK_ENV=development.
    """
    if os.environ.get("FLASK_ENV", "development") != "development":
        return jsonify({"error": "Test push is only available in development mode"}), 403

    count = send_push_notification(
        user_id=user_id,
        title="Umuve Test",
        body="If you see this, push notifications are working!",
        data={"type": "test"},
    )

    return jsonify({
        "success": True,
        "message": f"Test push sent to {count} device(s)",
        "devices_reached": count,
    }), 200
