from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps
from datetime import datetime, timedelta
import os
import logging

from sanitize import sanitize_dict
from extensions import limiter

from app_config import Config
from database import Database
from auth_routes import auth_bp, require_auth
from models import db as sqlalchemy_db
from socket_events import socketio
from routes import drivers_bp, pricing_bp, ratings_bp, admin_bp, payments_bp, webhook_bp, booking_bp, upload_bp, jobs_bp, tracking_bp, driver_bp, operator_bp, push_bp, service_area_bp, recurring_bp, referrals_bp, support_bp, chat_bp, onboarding_bp, promos_bp, reviews_bp, operator_applications_bp

# ---------------------------------------------------------------------------
# Sentry error monitoring (optional -- only active when SENTRY_DSN is set)
# ---------------------------------------------------------------------------
_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
    )

# ---------------------------------------------------------------------------
# Production startup checks
# ---------------------------------------------------------------------------
_startup_logger = logging.getLogger("umuve.startup")

_CRITICAL_ENV_VARS = [
    "JWT_SECRET",
    "SECRET_KEY",
    "DATABASE_URL",
]

_RECOMMENDED_ENV_VARS = [
    "ADMIN_SEED_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "CORS_ORIGINS",
]

_flask_env = os.environ.get("FLASK_ENV", "development")
if _flask_env != "development":
    _missing_critical = [v for v in _CRITICAL_ENV_VARS if not os.environ.get(v)]
    _missing_recommended = [v for v in _RECOMMENDED_ENV_VARS if not os.environ.get(v)]

    if _missing_critical:
        _startup_logger.critical(
            "MISSING CRITICAL ENV VARS (app may not work correctly): %s",
            ", ".join(_missing_critical),
        )
    if _missing_recommended:
        _startup_logger.warning(
            "Missing recommended env vars: %s",
            ", ".join(_missing_recommended),
        )
    if not _sentry_dsn:
        _startup_logger.warning(
            "SENTRY_DSN is not set -- error monitoring is disabled."
        )

app = Flask(__name__)
app.config.from_object(Config)

# ---------------------------------------------------------------------------
# SQLAlchemy configuration
# ---------------------------------------------------------------------------
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    # Fix postgres:// to postgresql:// for SQLAlchemy 2.x
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Fallback to SQLite for local development
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///umuve.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max request body

# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------
_is_development = os.environ.get("FLASK_ENV", "development") == "development"

_DEFAULT_ORIGINS = [
    "https://platform-olive-nu.vercel.app",
    "https://landing-page-premium-five.vercel.app",
    "https://umuve-backend.onrender.com",
    "https://goumuve.com",
    "https://www.goumuve.com",
    "https://app.goumuve.com",
]

_cors_env = os.environ.get("CORS_ORIGINS", "")
if _cors_env:
    # Honour explicit env-var override (comma-separated list)
    _allowed_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    # Block wildcard CORS in production -- it must be an explicit list
    if not _is_development and "*" in _allowed_origins:
        _startup_logger.critical(
            "CORS_ORIGINS is set to '*' in a non-development environment! "
            "Falling back to the default allow-list for safety."
        )
        _allowed_origins = _DEFAULT_ORIGINS
elif _is_development:
    _allowed_origins = "*"
else:
    _allowed_origins = _DEFAULT_ORIGINS

# ---------------------------------------------------------------------------
# Initialize extensions
# ---------------------------------------------------------------------------
CORS(app, resources={r"/api/*": {"origins": _allowed_origins}})
sqlalchemy_db.init_app(app)
socketio.init_app(app, cors_allowed_origins=_allowed_origins, async_mode="eventlet")

# ---------------------------------------------------------------------------
# Rate limiting (in-memory; upgrade to Redis via RATELIMIT_STORAGE_URI)
# ---------------------------------------------------------------------------
limiter.init_app(app)


@app.errorhandler(429)
def ratelimit_handler(e):
    # e.description is set by Flask-Limiter and contains the limit that was hit.
    # Retry-After header is automatically set by Flask-Limiter; read it back.
    retry_after = e.get_headers().get("Retry-After") if hasattr(e, "get_headers") else None
    retry_after_seconds = int(retry_after) if retry_after else 60
    return jsonify({
        "error": "Too many requests. Please try again later.",
        "retry_after": retry_after_seconds,
    }), 429

# Legacy SQLite database (kept for backward compatibility with existing endpoints)
legacy_db = Database(app.config["DATABASE_PATH"])

# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------
app.register_blueprint(auth_bp)
app.register_blueprint(drivers_bp)
app.register_blueprint(pricing_bp)
app.register_blueprint(ratings_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(webhook_bp)
app.register_blueprint(booking_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(tracking_bp)
app.register_blueprint(driver_bp)
app.register_blueprint(operator_bp)
app.register_blueprint(push_bp)
app.register_blueprint(service_area_bp)
app.register_blueprint(recurring_bp)
app.register_blueprint(referrals_bp)
app.register_blueprint(support_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(promos_bp)
app.register_blueprint(reviews_bp)
app.register_blueprint(operator_applications_bp)

# ---------------------------------------------------------------------------
# Input sanitization middleware (XSS / injection prevention)
# ---------------------------------------------------------------------------
# Paths that must NOT have their bodies sanitized (file uploads, webhooks).
_SANITIZE_SKIP_PREFIXES = ("/api/bookings/upload-photos", "/uploads/", "/api/webhooks/", "/api/upload/", "/api/drivers/onboarding/documents")


@app.before_request
def sanitize_json_input():
    """Sanitize all string values in incoming JSON bodies.

    Skips file-upload and webhook endpoints so that binary payloads and
    third-party webhook signatures are not corrupted.
    """
    if request.path.startswith(_SANITIZE_SKIP_PREFIXES):
        return  # skip

    # Skip sanitization for job photo uploads (multipart/form-data, not JSON)
    if "/photos/before" in request.path or "/photos/after" in request.path:
        return  # skip

    if request.is_json:
        try:
            raw = request.get_json(silent=True)
            if raw is not None:
                # Replace the parsed JSON cache with sanitized data so that
                # downstream calls to request.get_json() return clean values.
                request._cached_data = request.get_data()
                sanitized = sanitize_dict(raw)
                request._json = sanitized  # type: ignore[attr-defined]
        except Exception:
            pass  # If JSON parsing fails, let the route handler deal with it.


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    if not _is_development:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---------------------------------------------------------------------------
# Create all SQLAlchemy tables on startup
# ---------------------------------------------------------------------------
with app.app_context():
    sqlalchemy_db.create_all()

# ---------------------------------------------------------------------------
# Background scheduler (recurring jobs, pickup reminders)
# ---------------------------------------------------------------------------
from scheduler import init_scheduler
_scheduler = init_scheduler(app)


# ---------------------------------------------------------------------------
# Flask CLI command:  flask db-migrate
# ---------------------------------------------------------------------------
import click

@app.cli.command("db-migrate")
def cli_db_migrate():
    """Run database migrations (add new columns / create new tables)."""
    from migrate import run_migrations
    url = app.config["SQLALCHEMY_DATABASE_URI"]
    click.echo("Running Umuve database migrations...")
    actions = run_migrations(url)
    for action in actions:
        click.echo("  -> {}".format(action))
    click.echo("Migration complete.")


# ---------------------------------------------------------------------------
# Authentication decorator (legacy API-key based)
# ---------------------------------------------------------------------------
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key != app.config["API_KEY"]:
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Helper functions (legacy)
# ---------------------------------------------------------------------------
def calculate_price(service_ids, zip_code):
    """Calculate estimated price based on services"""
    total = 0
    services = []

    for service_id in service_ids:
        service = legacy_db.get_service(service_id)
        if service:
            total += service["base_price"]
            services.append(service)

    if len(services) > 0 and total < app.config["BASE_PRICE"]:
        total += app.config["BASE_PRICE"]

    return round(total, 2), services


def get_available_time_slots(requested_date=None):
    """Generate available time slots for booking"""
    slots = []
    start_date = datetime.now() + timedelta(days=1)

    if requested_date:
        try:
            start_date = datetime.strptime(requested_date, "%Y-%m-%d")
        except Exception:
            pass

    for day_offset in range(7):
        date = start_date + timedelta(days=day_offset)
        for hour in [9, 13]:
            slot_time = date.replace(hour=hour, minute=0, second=0)
            slots.append(slot_time.strftime("%Y-%m-%d %H:%M"))

    return slots[:10]


# ---------------------------------------------------------------------------
# Legacy API Routes (kept for backward compatibility)
# ---------------------------------------------------------------------------
@app.route("/api/health", methods=["GET"])
@limiter.exempt
def health_check():
    """Health check endpoint (exempt from rate limiting)"""
    return jsonify({"status": "healthy", "service": "Umuve API", "version": "2.1.0-driver-auth"}), 200


@app.route("/api/run-migrate/<secret>", methods=["POST"])
@limiter.exempt
def run_migrate_endpoint(secret):
    """Database migration endpoint secured by ADMIN_SEED_SECRET env var."""
    expected = os.environ.get("ADMIN_SEED_SECRET", "")
    if not expected or secret != expected:
        return jsonify({"error": "Forbidden"}), 403
    try:
        from migrate import run_migrations
        url = app.config["SQLALCHEMY_DATABASE_URI"]
        actions = run_migrations(url)
        return jsonify({"success": True, "actions": actions}), 200
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 500


@app.route("/api/services", methods=["GET"])
@require_api_key
def get_services():
    """Get all available services"""
    try:
        services = legacy_db.get_services()
        return jsonify({"success": True, "services": services}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/quote", methods=["POST"])
@require_api_key
def get_quote():
    """Get instant price quote"""
    try:
        data = request.get_json()

        if not data.get("services") or not isinstance(data["services"], list):
            return jsonify({"error": "Services array is required"}), 400

        zip_code = data.get("zip_code", "")
        service_ids = data["services"]

        estimated_price, services = calculate_price(service_ids, zip_code)
        available_slots = get_available_time_slots()

        return jsonify({
            "success": True,
            "estimated_price": estimated_price,
            "services": services,
            "available_time_slots": available_slots,
            "currency": "USD"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bookings", methods=["POST"])
@require_api_key
def create_booking():
    """Create new booking"""
    try:
        data = request.get_json()

        required_fields = ["address", "services", "scheduled_datetime", "customer"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": "Missing required field: {}".format(field)}), 400

        customer_data = data["customer"]
        required_customer_fields = ["name", "email", "phone"]
        for field in required_customer_fields:
            if field not in customer_data:
                return jsonify({"error": "Missing customer field: {}".format(field)}), 400

        customer_id = legacy_db.create_customer(
            customer_data["name"],
            customer_data["email"],
            customer_data["phone"]
        )

        estimated_price, services = calculate_price(
            data["services"],
            data.get("zip_code", "")
        )

        booking_id = legacy_db.create_booking(
            customer_id=customer_id,
            address=data["address"],
            zip_code=data.get("zip_code", ""),
            services=data["services"],
            photos=data.get("photos", []),
            scheduled_datetime=data["scheduled_datetime"],
            estimated_price=estimated_price,
            notes=data.get("notes", "")
        )

        return jsonify({
            "success": True,
            "booking_id": booking_id,
            "estimated_price": estimated_price,
            "confirmation": "Booking #{} confirmed".format(booking_id),
            "scheduled_datetime": data["scheduled_datetime"],
            "services": services
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bookings/<int:booking_id>", methods=["GET"])
@require_api_key
def get_booking(booking_id):
    """Get booking details"""
    try:
        booking = legacy_db.get_booking(booking_id)

        if not booking:
            return jsonify({"error": "Booking not found"}), 404

        return jsonify({"success": True, "booking": booking}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Customer bookings endpoint (used by iOS app)
# ---------------------------------------------------------------------------
@app.route("/api/bookings/customer", methods=["POST"])
@require_auth
def get_customer_bookings(user_id):
    """Get all bookings for the authenticated customer"""
    from models import Job, User, Contractor

    # Use the authenticated user — ignore any email in the body
    user = sqlalchemy_db.session.get(User, user_id)
    if not user:
        return jsonify({"success": True, "bookings": []}), 200

    # Get jobs for this customer
    jobs = Job.query.filter_by(customer_id=user.id).order_by(Job.created_at.desc()).all()

    bookings = []
    for job in jobs:
        booking = job.to_dict()
        booking["confirmation"] = "Booking #{} confirmed".format(job.id[:8])
        # Include operator name for delegated jobs
        if job.operator_id and job.operator_rel:
            op_user = job.operator_rel.user
            booking["operator_name"] = op_user.name if op_user else None
        else:
            booking["operator_name"] = None
        bookings.append(booking)

    return jsonify({"success": True, "bookings": bookings}), 200


# ---------------------------------------------------------------------------
# Customer portal compatibility endpoints
# ---------------------------------------------------------------------------
@app.route("/api/bookings/validate-address", methods=["POST"])
def validate_address():
    """Validate an address (stub - returns success with formatted data)"""
    data = request.get_json()
    address = data.get("address", "")
    if not address:
        return jsonify({"success": False, "error": "Address is required"}), 400

    return jsonify({
        "success": True,
        "address": {
            "formatted": address,
            "placeId": None,
            "lat": 26.1224,
            "lng": -80.1373,
        }
    }), 200


@app.route("/api/bookings/upload-photos", methods=["POST"])
@require_auth
def upload_booking_photos(user_id):
    """Upload photos for a booking (proxy to upload blueprint)"""
    from models import generate_uuid
    from werkzeug.utils import secure_filename
    import os

    upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(upload_folder, exist_ok=True)

    if "photos" not in request.files:
        return jsonify({"success": False, "error": "No photos provided"}), 400

    files = request.files.getlist("photos")
    if len(files) > 10:
        return jsonify({"success": False, "error": "Maximum 10 photos per upload"}), 400
    urls = []

    for file in files:
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in {"jpg", "jpeg", "png", "webp"}:
                unique_name = "{}.{}".format(generate_uuid(), ext)
                filepath = os.path.join(upload_folder, secure_filename(unique_name))
                file.save(filepath)
                urls.append("/uploads/{}".format(secure_filename(unique_name)))

    return jsonify({"success": True, "urls": urls}), 201


@app.route("/api/bookings/estimate", methods=["POST"])
def portal_estimate():
    """Price estimate compatible with customer portal API shape.

    Accepts EITHER the simple portal format (itemCategory + quantity) OR the
    full v2 format (items array with optional size + scheduledDate).
    """
    data = request.get_json() or {}

    from routes.booking import calculate_estimate

    # --- Build items list from whichever format the caller uses ---
    items = data.get("items")
    if not items or not isinstance(items, list):
        # Legacy simple format: single category + quantity
        category = data.get("itemCategory") or data.get("category", "general")
        quantity = int(data.get("quantity", 1))
        size = data.get("size")
        items = [{"category": category, "quantity": quantity}]
        if size:
            items[0]["size"] = size

    scheduled_date = data.get("scheduledDate") or data.get("scheduled_date")
    address = data.get("address") or {}
    lat = address.get("lat")
    lng = address.get("lng")

    est = calculate_estimate(items, scheduled_date=scheduled_date, lat=lat, lng=lng)

    # --- Format duration label ---
    duration_min = est["estimated_duration"]
    if duration_min <= 60:
        duration_label = "{} minutes".format(duration_min)
    else:
        hours = duration_min // 60
        remaining = duration_min % 60
        duration_label = "{}-{} hours".format(hours, hours + 1) if remaining else "{} hour{}".format(hours, "s" if hours > 1 else "")

    # Return both the portal-compatible shape AND the full v2 breakdown
    return jsonify({
        "success": True,
        "estimate": {
            "subtotal": est["base_price"],
            "serviceFee": est["service_fee"],
            "tax": 0,
            "total": est["total"],
            "estimatedDuration": duration_label,
            "truckSize": est["truck_size"],
            # v2 detailed breakdown
            "items_subtotal": est["items_subtotal"],
            "items": est["items"],
            "volume_discount": est["volume_discount"],
            "volume_discount_label": est["volume_discount_label"],
            "surge_multiplier": est["surge_multiplier"],
            "surge_amount": est["surge_amount"],
            "surge_reasons": est["surge_reasons"],
            "minimum_applied": est["minimum_applied"],
        }
    }), 200


@app.route("/api/bookings/available-slots", methods=["GET"])
def get_portal_available_slots():
    """Available time slots compatible with customer portal"""
    date_str = request.args.get("date")
    slots = get_available_time_slots(date_str[:10] if date_str else None)

    formatted = []
    for slot in slots:
        formatted.append({
            "date": slot.split(" ")[0],
            "time": slot.split(" ")[1] if " " in slot else "09:00",
            "available": True,
        })

    return jsonify({"success": True, "slots": formatted}), 200


@app.route("/api/bookings/create", methods=["POST"])
def portal_create_booking():
    """Create a booking from the customer portal (no auth required).

    Accepts the portal's form shape and creates a User + Job + Payment.
    """
    from werkzeug.security import generate_password_hash
    from models import Job, Payment, User, Notification, generate_uuid, utcnow
    from routes.booking import calculate_estimate, _notify_nearby_contractors

    data = request.get_json() or {}

    address = data.get("address")
    if not address:
        return jsonify({"error": "address is required"}), 400

    customer_info = data.get("customerInfo") or {}
    email = customer_info.get("email")
    name = customer_info.get("name", "")
    phone = customer_info.get("phone", "")

    if not email:
        return jsonify({"error": "customerInfo.email is required"}), 400

    # Find or create user
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, name=name, phone=phone, role="customer",
                     password_hash=generate_password_hash(generate_uuid()))
        sqlalchemy_db.session.add(user)
        sqlalchemy_db.session.flush()

    category = data.get("itemCategory") or data.get("category") or "general"
    quantity = int(data.get("quantity", 1))
    size = data.get("size")
    total_amount = float(data.get("totalAmount", 0))
    # Also accept total from estimate object
    if total_amount <= 0:
        estimate_data = data.get("estimate") or {}
        total_amount = float(estimate_data.get("total", 0))

    # Parse location from addressDetails if available
    addr_details = data.get("addressDetails") or {}
    location = addr_details.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")

    # --- Service area geofence check ---
    if lat is not None and lng is not None:
        from geofencing import is_in_service_area
        try:
            if not is_in_service_area(float(lat), float(lng)):
                return jsonify({
                    "error": "Address is outside our service area. "
                             "We currently serve Miami-Dade, Broward, and Palm Beach counties."
                }), 400
        except (TypeError, ValueError):
            pass  # Invalid coords -- skip check, let downstream handle it

    # Parse scheduled datetime
    scheduled_at = None
    selected_date = data.get("selectedDate")
    selected_time = data.get("selectedTime", "09:00")

    # Normalize time: convert "8:00 AM - 10:00 AM" or "2:00 PM" to "HH:MM"
    if selected_time and isinstance(selected_time, str):
        import re
        am_pm_match = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", selected_time, re.IGNORECASE)
        if am_pm_match:
            hour = int(am_pm_match.group(1))
            minute = am_pm_match.group(2)
            period = am_pm_match.group(3).upper()
            if period == "PM" and hour != 12:
                hour += 12
            if period == "AM" and hour == 12:
                hour = 0
            selected_time = "{:02d}:{}".format(hour, minute)

    if selected_date:
        try:
            date_str = selected_date[:10] if isinstance(selected_date, str) else selected_date.strftime("%Y-%m-%d")
            from datetime import timezone as tz
            scheduled_at = datetime.strptime("{} {}".format(date_str, selected_time), "%Y-%m-%d %H:%M").replace(tzinfo=tz.utc)
        except Exception:
            pass

    items = [{"category": category, "quantity": quantity}]
    if size:
        items[0]["size"] = size
    photos = data.get("photoUrls") or data.get("photos") or []

    # Use the v2 pricing engine for accurate calculation
    scheduled_date_for_pricing = selected_date[:10] if selected_date and isinstance(selected_date, str) else None
    est = calculate_estimate(
        items,
        scheduled_date=scheduled_date_for_pricing,
        lat=float(lat) if lat else None,
        lng=float(lng) if lng else None,
    )

    # Use calculated total, unless the caller provided a valid totalAmount
    if total_amount <= 0:
        total_amount = est["total"]

    # --- Apply promo code if provided ---
    promo_code_str = data.get("promoCode", "").strip() or data.get("promo_code", "").strip()
    promo_code_id = None
    discount_amount = 0.0

    if promo_code_str:
        from routes.promos import validate_promo_code
        from models import PromoCode as _PC
        promo, discount, promo_error = validate_promo_code(promo_code_str, total_amount)
        if promo_error:
            return jsonify({"error": promo_error}), 400
        promo_code_id = promo.id
        discount_amount = discount
        total_amount = round(total_amount - discount, 2)
        promo.use_count = (promo.use_count or 0) + 1

    job = Job(
        id=generate_uuid(),
        customer_id=user.id,
        status="pending",
        address=address,
        lat=float(lat) if lat else None,
        lng=float(lng) if lng else None,
        items=items,
        photos=photos,
        scheduled_at=scheduled_at,
        base_price=est["base_price"],
        item_total=est["items_subtotal"],
        service_fee=est["service_fee"],
        surge_multiplier=est["surge_multiplier"],
        total_price=total_amount,
        promo_code_id=promo_code_id,
        discount_amount=discount_amount,
        notes=data.get("itemDescription") or data.get("description", ""),
    )
    sqlalchemy_db.session.add(job)

    payment = Payment(
        id=generate_uuid(),
        job_id=job.id,
        amount=total_amount,
        service_fee=est["service_fee"],
        payment_status="pending",
    )
    sqlalchemy_db.session.add(payment)

    _notify_nearby_contractors(job)
    sqlalchemy_db.session.commit()

    # Send confirmation email and SMS
    from notifications import send_booking_confirmation_email, send_booking_sms
    date_str = selected_date[:10] if selected_date and isinstance(selected_date, str) else "TBD"
    if email:
        send_booking_confirmation_email(
            to_email=email,
            customer_name=name,
            booking_id=job.id,
            address=address,
            scheduled_date=date_str,
            scheduled_time=selected_time,
            total_amount=total_amount,
        )
    if phone:
        send_booking_sms(phone, job.id, date_str, address)

    return jsonify({
        "success": True,
        "bookingId": job.id,
        "job": job.to_dict(),
    }), 201


# Serve uploaded files
@app.route("/uploads/<filename>")
def serve_uploaded_file(filename):
    """Serve uploaded files"""
    from flask import send_from_directory
    import os
    upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    return send_from_directory(upload_folder, filename)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    socketio.run(app, debug=debug, host="0.0.0.0", port=port)
