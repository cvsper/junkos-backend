"""
Socket.IO event handlers for Umuve real-time features.
- Driver GPS location streaming
- Job status broadcasts
- New-job alerts to nearby drivers
"""

from math import radians, cos, sin, asin, sqrt
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request

from models import db, Contractor, Job

socketio = SocketIO()

EARTH_RADIUS_KM = 6371.0
DRIVER_BROADCAST_RADIUS_KM = 30.0


def _haversine(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


@socketio.on("connect")
def handle_connect():
    print("[socket] Client connected: {}".format(request.sid))


@socketio.on("disconnect")
def handle_disconnect():
    print("[socket] Client disconnected: {}".format(request.sid))


@socketio.on("join")
def handle_join(data):
    """Join a room. data = { room: "<job_id>" }"""
    room = data.get("room")
    if room:
        join_room(room)
        emit("joined", {"room": room}, room=request.sid)


@socketio.on("leave")
def handle_leave(data):
    room = data.get("room")
    if room:
        leave_room(room)


@socketio.on("admin:join")
def handle_admin_join():
    """Admin clients join the admin room for live map updates."""
    join_room("admin")
    emit("joined", {"room": "admin"}, room=request.sid)


@socketio.on("admin:leave")
def handle_admin_leave():
    """Admin clients leave the admin room."""
    leave_room("admin")


@socketio.on("operator:join")
def handle_operator_join(data):
    """Operator joins their room to receive delegated job notifications."""
    operator_id = data.get("operator_id")
    if operator_id:
        room = f"operator:{operator_id}"
        join_room(room)
        emit("joined", {"room": room}, room=request.sid)


@socketio.on("operator:leave")
def handle_operator_leave(data):
    """Operator leaves their room."""
    operator_id = data.get("operator_id")
    if operator_id:
        leave_room(f"operator:{operator_id}")


@socketio.on("customer:join")
def handle_customer_join(data):
    """Customer joins a job room to receive live tracking updates."""
    job_id = data.get("job_id")
    if job_id:
        join_room(job_id)
        emit("joined", {"room": job_id}, room=request.sid)


@socketio.on("customer:leave")
def handle_customer_leave(data):
    """Customer leaves a job room."""
    job_id = data.get("job_id")
    if job_id:
        leave_room(job_id)


@socketio.on("driver:location")
def handle_driver_location(data):
    """
    Receive driver GPS updates and broadcast to the job room.
    data = { contractor_id, lat, lng, job_id (optional) }
    """
    contractor_id = data.get("contractor_id")
    lat = data.get("lat")
    lng = data.get("lng")
    job_id = data.get("job_id")

    if not contractor_id or lat is None or lng is None:
        return

    try:
        contractor = db.session.get(Contractor, contractor_id)
        if contractor:
            contractor.current_lat = float(lat)
            contractor.current_lng = float(lng)
            db.session.commit()
    except Exception:
        db.session.rollback()

    if job_id:
        # Broadcast to everyone in the job room (customers tracking this job)
        emit("driver:location", {
            "contractor_id": contractor_id,
            "lat": lat,
            "lng": lng,
        }, room=job_id)

    # Broadcast to admin room for live map
    socketio.emit("admin:contractor-location", {
        "contractor_id": contractor_id,
        "lat": lat,
        "lng": lng,
    }, room="admin")


def broadcast_job_status(job_id, status, extra=None):
    """Utility called from REST routes to push status updates via socket."""
    payload = {"job_id": job_id, "status": status}
    if extra:
        payload.update(extra)
    socketio.emit("job:status", payload, room=job_id)
    # Also notify admin room
    socketio.emit("admin:job-status", payload, room="admin")


def broadcast_job_accepted(job_id, driver_id):
    """
    Broadcast job acceptance to ALL online approved contractors.
    Unlike broadcast_job_status (which targets the job room),
    this targets every driver room so they can remove the job from their feed.
    """
    contractors = Contractor.query.filter_by(
        is_online=True, approval_status="approved", is_operator=False
    ).all()
    payload = {"job_id": job_id, "status": "accepted", "driver_id": driver_id}
    for c in contractors:
        # Emit to each driver's personal room
        socketio.emit("job:accepted", payload, room=f"driver:{c.id}")
    # Also notify admin room
    socketio.emit("admin:job-status", payload, room="admin")


@socketio.on("chat:send")
def handle_chat_send(data):
    """
    Receive a chat message via Socket.IO, persist to DB, and broadcast to job room.
    data = { job_id, sender_id, sender_role, message }
    """
    from models import ChatMessage, generate_uuid

    job_id = data.get("job_id")
    sender_id = data.get("sender_id")
    sender_role = data.get("sender_role")
    message = (data.get("message") or "").strip()

    if not job_id or not sender_id or not sender_role or not message:
        emit("chat:error", {"error": "Missing required fields"}, room=request.sid)
        return

    if sender_role not in ("customer", "driver"):
        emit("chat:error", {"error": "Invalid sender_role"}, room=request.sid)
        return

    if len(message) > 2000:
        emit("chat:error", {"error": "Message too long"}, room=request.sid)
        return

    try:
        msg = ChatMessage(
            id=generate_uuid(),
            job_id=job_id,
            sender_id=sender_id,
            sender_role=sender_role,
            message=message,
        )
        db.session.add(msg)
        db.session.commit()

        msg_dict = msg.to_dict()
        emit("chat:message", msg_dict, room=job_id)
    except Exception as e:
        db.session.rollback()
        emit("chat:error", {"error": "Failed to save message"}, room=request.sid)


@socketio.on("chat:typing")
def handle_chat_typing(data):
    """
    Broadcast typing indicator to the job room.
    data = { job_id, sender_id, sender_role, is_typing }
    """
    job_id = data.get("job_id")
    if not job_id:
        return
    emit("chat:typing", {
        "job_id": job_id,
        "sender_id": data.get("sender_id"),
        "sender_role": data.get("sender_role"),
        "is_typing": data.get("is_typing", True),
    }, room=job_id, include_self=False)


@socketio.on("chat:read")
def handle_chat_read(data):
    """
    Mark messages as read and notify the sender.
    data = { job_id, reader_role }
    """
    from models import ChatMessage
    from datetime import datetime, timezone

    job_id = data.get("job_id")
    reader_role = data.get("reader_role")
    if not job_id or not reader_role:
        return

    other_role = "driver" if reader_role == "customer" else "customer"
    now = datetime.now(timezone.utc)

    try:
        updated = (
            ChatMessage.query
            .filter_by(job_id=job_id, sender_role=other_role)
            .filter(ChatMessage.read_at.is_(None))
            .update({"read_at": now})
        )
        db.session.commit()

        if updated > 0:
            emit("chat:read", {
                "job_id": job_id,
                "read_by": reader_role,
                "read_at": now.isoformat(),
                "count": updated,
            }, room=job_id)
    except Exception:
        db.session.rollback()


def notify_nearby_drivers(job):
    """
    Called after a new job is created.
    Emits a job:new event to all online approved contractors within range.
    """
    if job.lat is None or job.lng is None:
        socketio.emit("job:new", job.to_dict(), namespace="/")
        return

    contractors = Contractor.query.filter_by(is_online=True, approval_status="approved", is_operator=False).all()
    for c in contractors:
        if c.current_lat is None or c.current_lng is None:
            continue
        dist = _haversine(job.lat, job.lng, c.current_lat, c.current_lng)
        if dist <= DRIVER_BROADCAST_RADIUS_KM:
            socketio.emit("job:new", job.to_dict(), room=f"driver:{c.id}")
