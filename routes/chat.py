"""
Chat API routes for real-time messaging between customers and drivers on a job.
"""

from flask import Blueprint, request, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from models import db, Job, User, Contractor, ChatMessage, generate_uuid, utcnow
from auth_routes import require_auth

chat_bp = Blueprint("chat", __name__, url_prefix="/api/jobs")


def _get_sender_role(user_id, job):
    """Determine whether the authenticated user is 'customer' or 'driver' for this job."""
    if job.customer_id == user_id:
        return "customer"
    # Check if user is the assigned driver
    user = db.session.get(User, user_id)
    if user and user.contractor_profile and job.driver_id == user.contractor_profile.id:
        return "driver"
    return None


@chat_bp.route("/<job_id>/messages", methods=["GET"])
@require_auth
def get_messages(user_id, job_id):
    """
    Get chat messages for a job.
    Requires auth. Caller must be the job's customer or assigned driver.
    Supports pagination via ?before=<message_id>&limit=<n> (newest first by default).
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    role = _get_sender_role(user_id, job)
    if role is None:
        return jsonify({"error": "You do not have access to this job's chat"}), 403

    limit = min(int(request.args.get("limit", 50)), 100)
    before = request.args.get("before")  # message id for cursor-based pagination

    query = ChatMessage.query.filter_by(job_id=job_id)

    if before:
        cursor_msg = db.session.get(ChatMessage, before)
        if cursor_msg:
            query = query.filter(ChatMessage.created_at < cursor_msg.created_at)

    messages = (
        query
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )

    # Return in chronological order (oldest first)
    messages.reverse()

    return jsonify({
        "success": True,
        "messages": [m.to_dict() for m in messages],
        "has_more": len(messages) == limit,
    }), 200


@chat_bp.route("/<job_id>/messages", methods=["POST"])
@require_auth
def send_message(user_id, job_id):
    """
    Send a chat message on a job.
    Requires auth. Caller must be the job's customer or assigned driver.
    Body: { "message": "..." }
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    role = _get_sender_role(user_id, job)
    if role is None:
        return jsonify({"error": "You do not have access to this job's chat"}), 403

    data = request.get_json() or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "Message is required"}), 400

    if len(text) > 2000:
        return jsonify({"error": "Message must be 2000 characters or fewer"}), 400

    msg = ChatMessage(
        id=generate_uuid(),
        job_id=job_id,
        sender_id=user_id,
        sender_role=role,
        message=text,
    )
    db.session.add(msg)
    db.session.commit()

    msg_dict = msg.to_dict()

    # Broadcast via Socket.IO to the job room
    try:
        from socket_events import socketio
        socketio.emit("chat:message", msg_dict, room=job_id)
    except Exception:
        pass  # Socket broadcast is best-effort

    return jsonify({"success": True, "message": msg_dict}), 201


@chat_bp.route("/<job_id>/messages/read", methods=["PUT"])
@require_auth
def mark_messages_read(user_id, job_id):
    """
    Mark all unread messages in this job as read (for the authenticated user).
    Only marks messages sent by the *other* party as read.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    role = _get_sender_role(user_id, job)
    if role is None:
        return jsonify({"error": "You do not have access to this job's chat"}), 403

    # Mark messages from the OTHER sender as read
    other_role = "driver" if role == "customer" else "customer"
    now = utcnow()

    updated = (
        ChatMessage.query
        .filter_by(job_id=job_id, sender_role=other_role)
        .filter(ChatMessage.read_at.is_(None))
        .update({"read_at": now})
    )
    db.session.commit()

    # Notify the other party via Socket.IO
    try:
        from socket_events import socketio
        socketio.emit("chat:read", {
            "job_id": job_id,
            "read_by": role,
            "read_at": now.isoformat(),
            "count": updated,
        }, room=job_id)
    except Exception:
        pass

    return jsonify({"success": True, "marked_read": updated}), 200


@chat_bp.route("/<job_id>/messages/unread-count", methods=["GET"])
@require_auth
def unread_count(user_id, job_id):
    """
    Get the count of unread messages for the authenticated user in this job's chat.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    role = _get_sender_role(user_id, job)
    if role is None:
        return jsonify({"error": "You do not have access to this job's chat"}), 403

    other_role = "driver" if role == "customer" else "customer"
    count = (
        ChatMessage.query
        .filter_by(job_id=job_id, sender_role=other_role)
        .filter(ChatMessage.read_at.is_(None))
        .count()
    )

    return jsonify({"success": True, "unread_count": count}), 200
