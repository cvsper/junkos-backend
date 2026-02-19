"""
Customer-facing Job API routes for Umuve.
"""

from flask import Blueprint, request, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename

from models import db, Job, Contractor, Rating, Payment, User, Notification, generate_uuid, utcnow
from auth_routes import require_auth
from notifications import send_push_notification

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

# ---------------------------------------------------------------------------
# Upload constants (shared with routes/upload.py)
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_FILES = 10
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def _allowed_file(filename):
    """Check if a filename has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ensure_upload_dir():
    """Create the uploads directory if it does not exist."""
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------
# GET /api/jobs/lookup/<confirmation_code>  (PUBLIC -- no auth required)
# ---------------------------------------------------------------------------
@jobs_bp.route("/lookup/<confirmation_code>", methods=["GET"])
def lookup_by_confirmation_code(confirmation_code):
    """
    Public endpoint: look up a job by its 8-character confirmation code.
    Returns job details suitable for unauthenticated customers to track
    their pickup status. Does NOT expose sensitive internal data.
    """
    code = confirmation_code.strip().upper()
    if not code or len(code) != 8:
        return jsonify({"error": "Invalid confirmation code format"}), 400

    job = Job.query.filter_by(confirmation_code=code).first()
    if not job:
        return jsonify({"error": "No job found with that confirmation code"}), 404

    # Build a safe public response (no customer_id, payment details, internal IDs)
    result = {
        "id": job.id,
        "confirmation_code": job.confirmation_code,
        "status": job.status,
        "address": job.address,
        "items": job.items or [],
        "photos": job.photos or [],
        "before_photos": job.before_photos or [],
        "after_photos": job.after_photos or [],
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "total_price": job.total_price,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "notes": job.notes,
    }

    # Include contractor info if assigned
    if job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor:
            result["contractor"] = {
                "name": contractor.user.name if contractor.user else None,
                "truck_type": contractor.truck_type,
                "avg_rating": contractor.avg_rating,
                "total_jobs": contractor.total_jobs,
            }
        else:
            result["contractor"] = None
    else:
        result["contractor"] = None

    return jsonify({"success": True, "job": result}), 200


@jobs_bp.route("", methods=["GET"])
@require_auth
def list_jobs(user_id):
    """
    Return all jobs belonging to the authenticated customer.
    Optional query param: status (filter by job status).
    Results are ordered by created_at descending.
    """
    query = Job.query.filter_by(customer_id=user_id)

    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)

    query = query.order_by(Job.created_at.desc())
    jobs = query.all()

    result = []
    for job in jobs:
        job_dict = job.to_dict()
        if job.payment:
            job_dict["payment"] = {
                "id": job.payment.id,
                "amount": job.payment.amount,
                "payment_status": job.payment.payment_status,
                "tip_amount": job.payment.tip_amount,
            }
        else:
            job_dict["payment"] = None
        if job.rating:
            job_dict["rating"] = {
                "id": job.rating.id,
                "stars": job.rating.stars,
                "comment": job.rating.comment,
                "created_at": job.rating.created_at.isoformat() if job.rating.created_at else None,
            }
        else:
            job_dict["rating"] = None
        result.append(job_dict)

    return jsonify({"success": True, "jobs": result}), 200


@jobs_bp.route("/<job_id>", methods=["GET"])
@require_auth
def get_job(user_id, job_id):
    """
    Return a single job detail for the authenticated customer.
    Includes nested payment, rating, and contractor info.
    """
    job = db.session.get(Job, job_id)
    if not job or job.customer_id != user_id:
        return jsonify({"error": "Job not found"}), 404

    job_dict = job.to_dict()

    # Include payment info
    if job.payment:
        job_dict["payment"] = {
            "id": job.payment.id,
            "amount": job.payment.amount,
            "payment_status": job.payment.payment_status,
            "tip_amount": job.payment.tip_amount,
        }
    else:
        job_dict["payment"] = None

    # Include rating info
    if job.rating:
        job_dict["rating"] = {
            "id": job.rating.id,
            "stars": job.rating.stars,
            "comment": job.rating.comment,
            "created_at": job.rating.created_at.isoformat() if job.rating.created_at else None,
        }
    else:
        job_dict["rating"] = None

    # Include contractor info
    if job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor:
            contractor_dict = contractor.to_dict()
            job_dict["contractor"] = contractor_dict
        else:
            job_dict["contractor"] = None
    else:
        job_dict["contractor"] = None

    return jsonify({"success": True, "job": job_dict}), 200


@jobs_bp.route("/<job_id>/cancel", methods=["POST", "PUT"])
@require_auth
def cancel_job(user_id, job_id):
    """
    Cancel a job.

    Rules:
    - Only the customer who created the job can cancel it.
    - Cancellable statuses: pending, confirmed, assigned.
    - Cancellation fee based on time until scheduled pickup:
        - >24 hrs before: free
        - <24 hrs before: $25
        - <2 hrs before:  $50
    - If cancelled after driver assignment, notify the driver via push.
    - Creates a Notification record for the customer.
    """
    job = db.session.get(Job, job_id)
    if not job or job.customer_id != user_id:
        return jsonify({"error": "Job not found"}), 404

    cancellable = ("pending", "confirmed", "assigned")
    if job.status not in cancellable:
        return jsonify({"error": "Job cannot be cancelled in its current status"}), 409

    # --- Calculate cancellation fee ---
    cancellation_fee = 0.0
    now = datetime.utcnow()
    if job.scheduled_at:
        # Ensure both are naive UTC for comparison
        scheduled = job.scheduled_at.replace(tzinfo=None) if job.scheduled_at.tzinfo else job.scheduled_at
        time_until = scheduled - now
        if time_until < timedelta(hours=2):
            cancellation_fee = 50.0
        elif time_until < timedelta(hours=24):
            cancellation_fee = 25.0
        # else: > 24 hrs, free

    # --- Update job ---
    had_driver = job.driver_id is not None
    job.status = "cancelled"
    job.cancelled_at = utcnow()
    job.cancellation_fee = cancellation_fee

    # --- Notify assigned driver via push ---
    if had_driver:
        driver = db.session.get(Contractor, job.driver_id)
        if driver:
            send_push_notification(
                driver.user_id,
                "Job Cancelled",
                "Job #{} has been cancelled by the customer.".format(str(job.id)[:8]),
                {"job_id": job.id, "status": "cancelled"},
            )
            # Notification record for the driver
            driver_notif = Notification(
                id=generate_uuid(),
                user_id=driver.user_id,
                type="job_cancelled",
                title="Job Cancelled",
                body="Job #{} has been cancelled by the customer.".format(str(job.id)[:8]),
                data={"job_id": job.id},
            )
            db.session.add(driver_notif)

    # --- Notification record for the customer ---
    fee_msg = ""
    if cancellation_fee > 0:
        fee_msg = " A cancellation fee of ${:.2f} applies.".format(cancellation_fee)
    customer_notif = Notification(
        id=generate_uuid(),
        user_id=user_id,
        type="job_cancelled",
        title="Job Cancelled",
        body="Your job #{} has been cancelled.{}".format(str(job.id)[:8], fee_msg),
        data={"job_id": job.id, "cancellation_fee": cancellation_fee},
    )
    db.session.add(customer_notif)

    db.session.commit()

    return jsonify({
        "success": True,
        "job": job.to_dict(),
        "cancellation_fee": cancellation_fee,
    }), 200


@jobs_bp.route("/<job_id>/reschedule", methods=["PUT"])
@require_auth
def reschedule_job(user_id, job_id):
    """
    Reschedule a job to a new date/time.

    Rules:
    - Only the customer who created the job can reschedule.
    - Reschedulable statuses: pending, confirmed, assigned.
    - Accepts ``scheduled_date`` (YYYY-MM-DD) and ``scheduled_time`` (HH:MM)
      in the request body. These are combined into ``scheduled_at``.
    - Increments ``rescheduled_count``.
    - If a driver is assigned, notify them of the change via push.
    - Creates Notification records.
    """
    job = db.session.get(Job, job_id)
    if not job or job.customer_id != user_id:
        return jsonify({"error": "Job not found"}), 404

    reschedulable = ("pending", "confirmed", "assigned")
    if job.status not in reschedulable:
        return jsonify({"error": "Job cannot be rescheduled in its current status"}), 409

    data = request.get_json(silent=True) or {}
    scheduled_date = data.get("scheduled_date")
    scheduled_time = data.get("scheduled_time")

    if not scheduled_date or not scheduled_time:
        return jsonify({"error": "scheduled_date and scheduled_time are required"}), 400

    # Parse into a datetime
    try:
        new_scheduled_at = datetime.strptime(
            "{} {}".format(scheduled_date, scheduled_time), "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return jsonify({"error": "Invalid date/time format. Use YYYY-MM-DD and HH:MM"}), 400

    # Prevent scheduling in the past
    if new_scheduled_at < datetime.now(timezone.utc):
        return jsonify({"error": "Cannot schedule a job in the past"}), 400

    # --- Update job ---
    old_scheduled_at = job.scheduled_at
    job.scheduled_at = new_scheduled_at
    job.rescheduled_count = (job.rescheduled_count or 0) + 1

    # --- Notify assigned driver ---
    if job.driver_id:
        driver = db.session.get(Contractor, job.driver_id)
        if driver:
            send_push_notification(
                driver.user_id,
                "Job Rescheduled",
                "Job #{} has been rescheduled to {} at {}.".format(
                    str(job.id)[:8], scheduled_date, scheduled_time
                ),
                {"job_id": job.id, "scheduled_date": scheduled_date, "scheduled_time": scheduled_time},
            )
            driver_notif = Notification(
                id=generate_uuid(),
                user_id=driver.user_id,
                type="job_rescheduled",
                title="Job Rescheduled",
                body="Job #{} has been rescheduled to {} at {}.".format(
                    str(job.id)[:8], scheduled_date, scheduled_time
                ),
                data={"job_id": job.id, "scheduled_date": scheduled_date, "scheduled_time": scheduled_time},
            )
            db.session.add(driver_notif)

    # --- Notification record for the customer ---
    customer_notif = Notification(
        id=generate_uuid(),
        user_id=user_id,
        type="job_rescheduled",
        title="Job Rescheduled",
        body="Your job #{} has been rescheduled to {} at {}.".format(
            str(job.id)[:8], scheduled_date, scheduled_time
        ),
        data={"job_id": job.id, "scheduled_date": scheduled_date, "scheduled_time": scheduled_time},
    )
    db.session.add(customer_notif)

    db.session.commit()

    return jsonify({"success": True, "job": job.to_dict()}), 200


@jobs_bp.route("/<job_id>/proof", methods=["GET"])
@require_auth
def get_job_proof(user_id, job_id):
    """
    Return proof photos (before/after) for a job.

    Accessible to:
        - The customer who owns the job
        - The driver assigned to the job
        - An admin user
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Determine access: customer, driver, or admin
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    is_customer = job.customer_id == user_id
    is_admin = user.role == "admin"

    # Check if the user is the assigned driver
    is_driver = False
    if user.contractor_profile and job.driver_id == user.contractor_profile.id:
        is_driver = True

    if not (is_customer or is_driver or is_admin):
        return jsonify({"error": "You do not have access to this job's proof photos"}), 403

    return jsonify({
        "success": True,
        "job_id": job.id,
        "before_photos": job.before_photos or [],
        "after_photos": job.after_photos or [],
        "proof_submitted_at": job.proof_submitted_at.isoformat() if job.proof_submitted_at else None,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/photos  (customer or driver can view)
# ---------------------------------------------------------------------------
@jobs_bp.route("/<job_id>/photos", methods=["GET"])
@require_auth
def get_job_photos(user_id, job_id):
    """
    Return all photos for a job (before_photos, after_photos, and original photos).

    Accessible to:
        - The customer who owns the job
        - The driver assigned to the job
        - An admin user
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    is_customer = job.customer_id == user_id
    is_admin = user.role == "admin"
    is_driver = False
    if user.contractor_profile and job.driver_id == user.contractor_profile.id:
        is_driver = True

    if not (is_customer or is_driver or is_admin):
        return jsonify({"error": "You do not have access to this job's photos"}), 403

    return jsonify({
        "success": True,
        "job_id": job.id,
        "photos": job.photos or [],
        "before_photos": job.before_photos or [],
        "after_photos": job.after_photos or [],
        "proof_submitted_at": job.proof_submitted_at.isoformat() if job.proof_submitted_at else None,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/photos/before  (driver uploads before photos)
# ---------------------------------------------------------------------------
@jobs_bp.route("/<job_id>/photos/before", methods=["POST"])
@require_auth
def upload_before_photos(user_id, job_id):
    """
    Driver uploads before photos for a job (multipart/form-data).

    Only the assigned driver can upload.
    Form field: ``files`` (multiple).
    Appends uploaded URLs to ``job.before_photos``.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Verify the authenticated user is the assigned driver
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    is_driver = False
    if user.contractor_profile and job.driver_id == user.contractor_profile.id:
        is_driver = True

    if not is_driver:
        return jsonify({"error": "Only the assigned driver can upload before photos"}), 403

    # Parse files from the request
    if "files" not in request.files:
        return jsonify({"error": "No files provided. Use the 'files' form field."}), 400

    files = request.files.getlist("files")
    if len(files) == 0:
        return jsonify({"error": "No files provided"}), 400
    if len(files) > MAX_FILES:
        return jsonify({"error": "Maximum {} files allowed per upload".format(MAX_FILES)}), 400

    _ensure_upload_dir()

    urls = []
    errors = []

    for file in files:
        if not file or not file.filename:
            errors.append({"file": "unknown", "error": "Empty file"})
            continue

        if not _allowed_file(file.filename):
            errors.append({"file": file.filename, "error": "File type not allowed. Accepted: jpg, png, webp"})
            continue

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > MAX_FILE_SIZE:
            errors.append({"file": file.filename, "error": "File exceeds maximum size of 10 MB"})
            continue

        ext = file.filename.rsplit(".", 1)[1].lower()
        unique_name = "{}.{}".format(generate_uuid(), ext)
        safe_name = secure_filename(unique_name)
        filepath = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(filepath)

        url = "/uploads/{}".format(safe_name)
        urls.append(url)

    if not urls:
        return jsonify({"success": False, "error": "No files were uploaded successfully", "errors": errors}), 400

    # Append to existing before_photos
    existing = list(job.before_photos or [])
    existing.extend(urls)
    job.before_photos = existing

    db.session.commit()

    response = {"success": True, "urls": urls, "before_photos": job.before_photos}
    if errors:
        response["errors"] = errors

    return jsonify(response), 201


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/photos/after  (driver uploads after photos)
# ---------------------------------------------------------------------------
@jobs_bp.route("/<job_id>/photos/after", methods=["POST"])
@require_auth
def upload_after_photos(user_id, job_id):
    """
    Driver uploads after photos for a job (multipart/form-data).

    Only the assigned driver can upload.
    Form field: ``files`` (multiple).
    Appends uploaded URLs to ``job.after_photos``.
    Sets ``proof_submitted_at`` on first upload.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Verify the authenticated user is the assigned driver
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    is_driver = False
    if user.contractor_profile and job.driver_id == user.contractor_profile.id:
        is_driver = True

    if not is_driver:
        return jsonify({"error": "Only the assigned driver can upload after photos"}), 403

    # Parse files from the request
    if "files" not in request.files:
        return jsonify({"error": "No files provided. Use the 'files' form field."}), 400

    files = request.files.getlist("files")
    if len(files) == 0:
        return jsonify({"error": "No files provided"}), 400
    if len(files) > MAX_FILES:
        return jsonify({"error": "Maximum {} files allowed per upload".format(MAX_FILES)}), 400

    _ensure_upload_dir()

    urls = []
    errors = []

    for file in files:
        if not file or not file.filename:
            errors.append({"file": "unknown", "error": "Empty file"})
            continue

        if not _allowed_file(file.filename):
            errors.append({"file": file.filename, "error": "File type not allowed. Accepted: jpg, png, webp"})
            continue

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > MAX_FILE_SIZE:
            errors.append({"file": file.filename, "error": "File exceeds maximum size of 10 MB"})
            continue

        ext = file.filename.rsplit(".", 1)[1].lower()
        unique_name = "{}.{}".format(generate_uuid(), ext)
        safe_name = secure_filename(unique_name)
        filepath = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(filepath)

        url = "/uploads/{}".format(safe_name)
        urls.append(url)

    if not urls:
        return jsonify({"success": False, "error": "No files were uploaded successfully", "errors": errors}), 400

    # Append to existing after_photos
    existing = list(job.after_photos or [])
    existing.extend(urls)
    job.after_photos = existing

    # Mark proof submission timestamp on first after-photo upload
    if not job.proof_submitted_at:
        job.proof_submitted_at = utcnow()

    db.session.commit()

    response = {"success": True, "urls": urls, "after_photos": job.after_photos}
    if errors:
        response["errors"] = errors

    return jsonify(response), 201


@jobs_bp.route("/<job_id>/volume/approve", methods=["POST"])
@require_auth
def approve_volume_adjustment(user_id, job_id):
    """Customer approves the driver's proposed volume adjustment."""
    import stripe
    from socket_events import socketio
    import logging

    logger = logging.getLogger(__name__)

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.customer_id != user_id:
        return jsonify({"error": "Only the customer can approve volume adjustments"}), 403

    if not job.volume_adjustment_proposed:
        return jsonify({"error": "No volume adjustment is pending"}), 409

    # Update Stripe PaymentIntent to new price
    try:
        if job.payment and job.payment.stripe_payment_intent_id:
            stripe.PaymentIntent.modify(
                job.payment.stripe_payment_intent_id,
                amount=int(job.adjusted_price * 100)
            )
            # Update payment record
            job.payment.amount = job.adjusted_price
            job.payment.commission = job.adjusted_price * 0.20
            job.payment.driver_payout_amount = job.adjusted_price * 0.80
    except Exception as e:
        logger.warning("Failed to update Stripe PaymentIntent for approved volume adjustment: %s", e)

    # Update job with approved values
    job.total_price = job.adjusted_price
    job.volume_estimate = job.adjusted_volume
    job.volume_adjustment_proposed = False
    job.updated_at = utcnow()

    db.session.commit()

    # Emit socket event to driver
    try:
        socketio.emit("volume:approved", {"job_id": job_id}, room=f"driver:{job.driver_id}")
    except Exception as e:
        logger.warning("Failed to emit volume:approved socket event: %s", e)

    logger.info("Volume adjustment approved for job %s by customer %s", job_id, user_id)

    return jsonify({"success": True}), 200


@jobs_bp.route("/<job_id>/volume/decline", methods=["POST"])
@require_auth
def decline_volume_adjustment(user_id, job_id):
    """Customer declines the driver's proposed volume adjustment - charges trip fee and cancels job."""
    import stripe
    from socket_events import socketio
    import logging

    logger = logging.getLogger(__name__)

    TRIP_FEE = 50.0

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.customer_id != user_id:
        return jsonify({"error": "Only the customer can decline volume adjustments"}), 403

    if not job.volume_adjustment_proposed:
        return jsonify({"error": "No volume adjustment is pending"}), 409

    # Update Stripe PaymentIntent to trip fee
    try:
        if job.payment and job.payment.stripe_payment_intent_id:
            stripe.PaymentIntent.modify(
                job.payment.stripe_payment_intent_id,
                amount=int(TRIP_FEE * 100)
            )
            # Update payment record
            job.payment.amount = TRIP_FEE
            job.payment.commission = TRIP_FEE * 0.20
            job.payment.driver_payout_amount = TRIP_FEE * 0.80
    except Exception as e:
        logger.warning("Failed to update Stripe PaymentIntent for declined volume adjustment: %s", e)

    # Cancel job with trip fee
    job.status = "cancelled"
    job.cancelled_at = utcnow()
    job.cancellation_fee = TRIP_FEE
    job.volume_adjustment_proposed = False
    job.updated_at = utcnow()

    db.session.commit()

    # Emit socket event to driver
    try:
        socketio.emit("volume:declined", {"job_id": job_id, "trip_fee": TRIP_FEE}, room=f"driver:{job.driver_id}")
    except Exception as e:
        logger.warning("Failed to emit volume:declined socket event: %s", e)

    logger.info("Volume adjustment declined for job %s by customer %s - charging $%.2f trip fee", job_id, user_id, TRIP_FEE)

    return jsonify({"success": True, "trip_fee": TRIP_FEE}), 200
