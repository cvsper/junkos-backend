"""
Support chat API routes for Umuve.
POST /api/support/message  -- public (rate-limited) endpoint for customers.
GET  /api/admin/support-messages -- admin-only listing.
"""

from flask import Blueprint, request, jsonify
from functools import wraps

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, SupportMessage, generate_uuid, utcnow
from auth_routes import require_auth
from extensions import limiter

support_bp = Blueprint("support", __name__)


# ---------------------------------------------------------------------------
# Public endpoint -- submit a support message
# ---------------------------------------------------------------------------

@support_bp.route("/api/support/message", methods=["POST"])
@limiter.limit("10 per minute")
def create_support_message():
    """Accept a support message from the chat widget.

    Body: { name, email, message, category }
    Optionally authenticated -- if a valid JWT is provided we link the user_id.
    """
    data = request.get_json() or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()
    category = (data.get("category") or "other").strip()

    if not message:
        return jsonify({"error": "message is required"}), 400
    if not email:
        return jsonify({"error": "email is required"}), 400

    # Try to extract user_id from optional JWT
    user_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        import jwt as pyjwt
        from app_config import Config
        token = auth_header.split(" ", 1)[1]
        try:
            payload = pyjwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("user_id")
        except Exception:
            pass  # Token invalid -- still accept the message as anonymous

    msg = SupportMessage(
        id=generate_uuid(),
        user_id=user_id,
        name=name or "Guest",
        email=email,
        message=message,
        category=category,
        status="open",
    )
    db.session.add(msg)
    db.session.commit()

    # Best-effort email notification to the support inbox
    try:
        from notifications import send_email
        html_body = (
            "<p><strong>From:</strong> {} &lt;{}&gt;</p>"
            "<p><strong>Category:</strong> {}</p>"
            "<hr/><p>{}</p>"
        ).format(name or "Guest", email, category, message.replace("\n", "<br/>"))
        send_email(
            to_email="support@goumuve.com",
            subject="New support message from {} ({})".format(name or "Guest", category),
            html_content=html_body,
        )
    except Exception:
        pass  # Email sending is non-critical

    return jsonify({"success": True, "id": msg.id}), 201


# ---------------------------------------------------------------------------
# Admin endpoint -- list support messages
# ---------------------------------------------------------------------------

def _require_admin(f):
    """Convenience: require_auth + admin role check."""
    @wraps(f)
    @require_auth
    def wrapper(user_id, *args, **kwargs):
        user = db.session.get(User, user_id)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(user_id=user_id, *args, **kwargs)
    return wrapper


@support_bp.route("/api/admin/support-messages", methods=["GET"])
@_require_admin
def list_support_messages(user_id):
    """Return support messages with optional filters.

    Query params:
      status  -- "open" | "resolved" (default: all)
      page    -- page number (default 1)
      per_page -- items per page (default 50)
    """
    status_filter = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)

    query = SupportMessage.query.order_by(SupportMessage.created_at.desc())

    if status_filter in ("open", "resolved"):
        query = query.filter_by(status=status_filter)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "success": True,
        "messages": [m.to_dict() for m in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


@support_bp.route("/api/admin/support-messages/<message_id>/resolve", methods=["PUT"])
@_require_admin
def resolve_support_message(user_id, message_id):
    """Mark a support message as resolved."""
    msg = db.session.get(SupportMessage, message_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404

    msg.status = "resolved"
    db.session.commit()

    return jsonify({"success": True, "message": msg.to_dict()}), 200
