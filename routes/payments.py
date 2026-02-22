"""
Payment API routes for Umuve.
Stripe Connect: customer pays -> platform takes commission -> contractor gets payout.
"""

import os
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, Job, Payment, Contractor, User, Notification, generate_uuid, utcnow
from auth_routes import require_auth
from extensions import limiter

payments_bp = Blueprint("payments", __name__, url_prefix="/api/payments")

_stripe = None

PLATFORM_COMMISSION = 0.20
SERVICE_FEE_RATE = 0.08  # 8% of amount – matches booking.py


def _get_stripe():
    global _stripe
    if _stripe is None:
        import stripe
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        _stripe = stripe
    return _stripe


@payments_bp.route("/create-intent", methods=["POST"])
@limiter.limit("10 per minute")
@require_auth
def create_payment_intent(user_id):
    """
    Create a Stripe PaymentIntent for a job.
    Body JSON: job_id (str), tip_amount (float, optional)
    """
    data = request.get_json() or {}
    job_id = data.get("job_id")
    tip_amount = float(data.get("tip_amount", 0))

    if tip_amount < 0:
        return jsonify({"error": "tip_amount cannot be negative"}), 400

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job.customer_id != user_id:
        return jsonify({"error": "Not authorised for this job"}), 403

    if job.payment and job.payment.payment_status == "succeeded":
        return jsonify({"error": "Job is already paid"}), 409

    amount = round(job.total_price + tip_amount, 2)
    commission = round(amount * PLATFORM_COMMISSION, 2)
    service_fee = round(amount * SERVICE_FEE_RATE, 2)
    driver_payout = max(0, round(amount - commission - service_fee, 2))

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")

    intent_id = None
    client_secret = None

    if stripe_key:
        try:
            intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),
                currency="usd",
                metadata={"job_id": job_id, "user_id": user_id},
            )
            intent_id = intent.id
            client_secret = intent.client_secret
        except Exception as e:
            return jsonify({"error": "Stripe error: {}".format(str(e))}), 502
    else:
        intent_id = "pi_dev_{}".format(generate_uuid()[:8])
        client_secret = "{}_secret_dev".format(intent_id)

    payment = job.payment
    if not payment:
        payment = Payment(
            id=generate_uuid(),
            job_id=job_id,
        )
        db.session.add(payment)

    payment.stripe_payment_intent_id = intent_id
    payment.amount = amount
    payment.service_fee = service_fee
    payment.commission = commission
    payment.driver_payout_amount = driver_payout
    payment.tip_amount = tip_amount
    payment.payment_status = "pending"
    payment.updated_at = utcnow()

    db.session.commit()

    return jsonify({
        "success": True,
        "client_secret": client_secret,
        "payment_intent_id": intent_id,
        "amount": amount,
        "payment": payment.to_dict(),
    }), 201


@payments_bp.route("/confirm", methods=["POST"])
@require_auth
def confirm_payment(user_id):
    """
    Mark a payment as succeeded.
    Body JSON: payment_intent_id (str)
    """
    data = request.get_json() or {}
    intent_id = data.get("payment_intent_id")

    if not intent_id:
        return jsonify({"error": "payment_intent_id is required"}), 400

    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()
    if not payment:
        return jsonify({"error": "Payment not found"}), 404

    payment.payment_status = "succeeded"
    payment.updated_at = utcnow()

    job = db.session.get(Job, payment.job_id)
    if job and job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor:
            notification = Notification(
                id=generate_uuid(),
                user_id=contractor.user_id,
                type="payment",
                title="Payment Received",
                body="Payment of ${:.2f} confirmed for job.".format(payment.amount),
                data={"job_id": job.id, "amount": payment.amount},
            )
            db.session.add(notification)

    db.session.commit()

    # --- Send payment receipt email to customer ---
    try:
        if job:
            customer = db.session.get(User, job.customer_id)
            if customer and customer.email:
                from notifications import send_payment_receipt_email
                send_payment_receipt_email(
                    customer.email, customer.name, job.id,
                    job.address, payment.amount,
                )
    except Exception:
        pass  # Notifications must never block the main flow

    return jsonify({"success": True, "payment": payment.to_dict()}), 200


@payments_bp.route("/payout/<job_id>", methods=["POST"])
@require_auth
def trigger_payout(user_id, job_id):
    """Trigger Stripe Connect payout to the contractor for a completed job."""
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    payment = job.payment
    if not payment:
        return jsonify({"error": "No payment record for this job"}), 404
    if payment.payment_status != "succeeded":
        return jsonify({"error": "Payment has not succeeded yet"}), 409
    if payment.payout_status == "paid":
        return jsonify({"error": "Payout already completed"}), 409

    if not job.driver_id:
        return jsonify({"error": "No driver assigned to this job"}), 400

    contractor = db.session.get(Contractor, job.driver_id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")

    if stripe_key and contractor.stripe_connect_id:
        try:
            stripe.Transfer.create(
                amount=int(payment.driver_payout_amount * 100),
                currency="usd",
                destination=contractor.stripe_connect_id,
                metadata={"job_id": job_id},
            )
        except Exception as e:
            payment.payout_status = "failed"
            db.session.commit()
            return jsonify({"error": "Stripe payout error: {}".format(str(e))}), 502

    payment.payout_status = "paid"
    payment.updated_at = utcnow()

    notification = Notification(
        id=generate_uuid(),
        user_id=contractor.user_id,
        type="payment",
        title="Payout Sent",
        body="${:.2f} has been sent to your account.".format(payment.driver_payout_amount),
        data={"job_id": job_id, "amount": payment.driver_payout_amount},
    )
    db.session.add(notification)
    db.session.commit()

    return jsonify({"success": True, "payment": payment.to_dict()}), 200


@payments_bp.route("/create-intent-simple", methods=["POST"])
@limiter.limit("10 per minute")
def create_simple_payment_intent():
    """
    Create a Stripe PaymentIntent without auth (for customer portal / iOS app).
    Body JSON: amount (float, in dollars, required), bookingId (str, optional),
               customerEmail (str, optional)
    """
    data = request.get_json() or {}
    booking_id = data.get("bookingId") or data.get("booking_id")
    customer_email = data.get("customerEmail") or data.get("customer_email")

    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400

    if amount <= 0:
        return jsonify({"error": "amount is required and must be positive"}), 400

    if amount > 10000:
        return jsonify({"error": "amount exceeds maximum allowed ($10,000)"}), 400

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")

    intent_id = None
    client_secret = None

    metadata = {}
    if booking_id:
        metadata["booking_id"] = booking_id
    if customer_email:
        metadata["customer_email"] = customer_email

    if stripe_key:
        try:
            intent_kwargs = {
                "amount": int(amount * 100),
                "currency": "usd",
                "metadata": metadata,
            }
            if customer_email:
                intent_kwargs["receipt_email"] = customer_email
            intent = stripe.PaymentIntent.create(**intent_kwargs)
            intent_id = intent.id
            client_secret = intent.client_secret
        except Exception as e:
            return jsonify({"error": "Stripe error: {}".format(str(e))}), 502
    else:
        # Dev mode - return mock intent
        intent_id = "pi_dev_{}".format(generate_uuid()[:8])
        client_secret = "{}_secret_dev".format(intent_id)

    # Link intent to the job's payment record if booking exists
    if booking_id:
        payment = Payment.query.filter_by(job_id=booking_id).first()
        if payment:
            payment.stripe_payment_intent_id = intent_id
            payment.amount = amount
            payment.payment_status = "pending"
            payment.updated_at = utcnow()
            db.session.commit()

    return jsonify({
        "success": True,
        "clientSecret": client_secret,
        "paymentIntentId": intent_id,
    }), 201


@payments_bp.route("/confirm-simple", methods=["POST"])
@limiter.limit("10 per minute")
def confirm_simple_payment():
    """
    Confirm / mark a payment as succeeded (for customer portal / iOS app).
    Validates the PaymentIntent status against Stripe before marking as paid.
    Body JSON: paymentIntentId (str, required), paymentMethodType (str, optional)
    """
    data = request.get_json() or {}
    intent_id = data.get("paymentIntentId") or data.get("payment_intent_id")

    if not intent_id:
        return jsonify({"error": "paymentIntentId is required"}), 400

    # Validate against Stripe that the intent actually succeeded (skip for dev intents)
    if not intent_id.startswith("pi_dev_"):
        stripe = _get_stripe()
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if stripe_key:
            try:
                intent_obj = stripe.PaymentIntent.retrieve(intent_id)
                if intent_obj.status != "succeeded":
                    return jsonify({"error": "Payment intent has not succeeded (status: {})".format(intent_obj.status)}), 400
            except Exception as e:
                return jsonify({"error": "Failed to verify payment with Stripe: {}".format(str(e))}), 502

    # Look up existing payment record
    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()

    if not payment:
        return jsonify({"error": "Payment not found"}), 404

    payment.payment_status = "succeeded"
    payment.updated_at = utcnow()

    job = db.session.get(Job, payment.job_id)
    if job and job.status == "pending":
        job.status = "confirmed"
        job.updated_at = utcnow()

        # Auto-assign nearest driver
        _auto_assign_driver(job)

        # Broadcast status update via SocketIO
        from socket_events import broadcast_job_status
        broadcast_job_status(job.id, job.status)

    db.session.commit()

    # --- Send payment receipt email to customer ---
    try:
        if job:
            customer = db.session.get(User, job.customer_id)
            if customer and customer.email:
                from notifications import send_payment_receipt_email
                send_payment_receipt_email(
                    customer.email, customer.name, job.id,
                    job.address, payment.amount,
                )
    except Exception:
        pass  # Notifications must never block the main flow

    return jsonify({
        "success": True,
        "payment": payment.to_dict(),
        "job": job.to_dict() if job else None,
    }), 200


@payments_bp.route("/earnings", methods=["GET"])
@require_auth
def get_earnings(user_id):
    """Return earnings summary for a contractor."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    now = utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    all_payments = (
        Payment.query
        .join(Job, Payment.job_id == Job.id)
        .filter(Job.driver_id == contractor.id, Payment.payment_status == "succeeded")
        .all()
    )

    total_earnings = sum(p.driver_payout_amount for p in all_payments)
    total_tips = sum(p.tip_amount for p in all_payments)
    earnings_30d = sum(p.driver_payout_amount for p in all_payments if p.created_at and p.created_at >= thirty_days_ago)
    earnings_7d = sum(p.driver_payout_amount for p in all_payments if p.created_at and p.created_at >= seven_days_ago)

    pending_payout = sum(
        p.driver_payout_amount for p in all_payments if p.payout_status == "pending"
    )

    return jsonify({
        "success": True,
        "earnings": {
            "total_earnings": round(total_earnings, 2),
            "total_tips": round(total_tips, 2),
            "earnings_30d": round(earnings_30d, 2),
            "earnings_7d": round(earnings_7d, 2),
            "pending_payout": round(pending_payout, 2),
            "total_jobs": contractor.total_jobs or 0,
        },
    }), 200


# ---------------------------------------------------------------------------
# Stripe Connect
# ---------------------------------------------------------------------------

@payments_bp.route("/connect/create-account", methods=["POST"])
@require_auth
def create_connect_account(user_id):
    """Create a Stripe Connect Express account for the authenticated driver."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    # Idempotent — return existing account if already created
    if contractor.stripe_connect_id:
        return jsonify({
            "success": True,
            "account_id": contractor.stripe_connect_id,
        }), 200

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    account_id = None

    if stripe_key:
        try:
            account = stripe.Account.create(
                type="express",
                country="US",
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            )
            account_id = account.id
        except Exception as e:
            return jsonify({"error": "Stripe error: {}".format(str(e))}), 502
    else:
        # Dev mode — generate mock account ID
        account_id = "acct_dev_{}".format(generate_uuid()[:8])

    contractor.stripe_connect_id = account_id
    db.session.commit()

    return jsonify({
        "success": True,
        "account_id": account_id,
    }), 201


@payments_bp.route("/connect/account-link", methods=["POST"])
@require_auth
def create_account_link(user_id):
    """Generate a fresh Stripe Connect account onboarding link (expires in 5 minutes)."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    if not contractor.stripe_connect_id:
        return jsonify({"error": "No Stripe Connect account found. Call /connect/create-account first."}), 400

    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8080")
    refresh_url = "{}/api/payments/connect/refresh".format(base_url)
    return_url = "{}/api/payments/connect/return".format(base_url)

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")

    if stripe_key:
        try:
            account_link = stripe.AccountLink.create(
                account=contractor.stripe_connect_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
            return jsonify({
                "success": True,
                "url": account_link.url,
                "expires_at": account_link.expires_at,
            }), 200
        except Exception as e:
            return jsonify({"error": "Stripe error: {}".format(str(e))}), 502
    else:
        # Dev mode — return mock URL
        return jsonify({
            "success": True,
            "url": "https://connect.stripe.com/setup/e/mock",
            "expires_at": int((utcnow() + timedelta(minutes=5)).timestamp()),
        }), 200


@payments_bp.route("/connect/status", methods=["GET"])
@require_auth
def get_connect_status(user_id):
    """Get the Stripe Connect onboarding status for the authenticated driver."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    if not contractor.stripe_connect_id:
        return jsonify({
            "success": True,
            "status": "not_set_up",
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": False,
        }), 200

    stripe = _get_stripe()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")

    charges_enabled = False
    payouts_enabled = False
    details_submitted = False

    if stripe_key:
        try:
            account = stripe.Account.retrieve(contractor.stripe_connect_id)
            charges_enabled = account.get("charges_enabled", False)
            payouts_enabled = account.get("payouts_enabled", False)
            details_submitted = account.get("details_submitted", False)
        except Exception:
            pass  # Fall back to stored values or False

    # Determine status
    if charges_enabled and payouts_enabled:
        status = "active"
    elif contractor.stripe_connect_id:
        status = "pending_verification"
    else:
        status = "not_set_up"

    return jsonify({
        "success": True,
        "status": status,
        "charges_enabled": charges_enabled,
        "payouts_enabled": payouts_enabled,
        "details_submitted": details_submitted,
    }), 200


@payments_bp.route("/connect/return", methods=["GET"])
def connect_return():
    """Stripe calls this URL after successful onboarding completion."""
    return """
    <html>
    <head><title>Setup Complete</title></head>
    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1>Setup complete!</h1>
        <p>Return to the Umuve Pro app.</p>
    </body>
    </html>
    """, 200


@payments_bp.route("/connect/refresh", methods=["GET"])
def connect_refresh():
    """Stripe calls this URL if the onboarding link expires."""
    return """
    <html>
    <head><title>Link Expired</title></head>
    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1>Link expired</h1>
        <p>Please return to the app and try again.</p>
    </body>
    </html>
    """, 200


@payments_bp.route("/earnings/history", methods=["GET"])
@require_auth
def get_earnings_history(user_id):
    """Return detailed earnings history with per-job payout status (driver's 80% take only)."""
    contractor = Contractor.query.filter_by(user_id=user_id).first()
    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # Query all succeeded payments for this driver
    payments = (
        Payment.query
        .join(Job, Payment.job_id == Job.id)
        .filter(Job.driver_id == contractor.id, Payment.payment_status == "succeeded")
        .order_by(Payment.created_at.desc())
        .all()
    )

    # Build entries
    entries = []
    for payment in payments:
        job = db.session.get(Job, payment.job_id)
        payout = payment.driver_payout_amount or 0.0
        entries.append({
            "id": payment.id,
            "job_id": payment.job_id,
            "address": job.address if job else None,
            "amount": round(payout, 2),
            "date": payment.created_at.isoformat() if payment.created_at else None,
            "payout_status": payment.payout_status,
        })

    # Compute summary (handle None values)
    today_earnings = sum(
        (p.driver_payout_amount or 0.0) for p in payments
        if p.created_at and p.created_at >= today_start
    )
    week_earnings = sum(
        (p.driver_payout_amount or 0.0) for p in payments
        if p.created_at and p.created_at >= seven_days_ago
    )
    month_earnings = sum(
        (p.driver_payout_amount or 0.0) for p in payments
        if p.created_at and p.created_at >= thirty_days_ago
    )
    all_time_earnings = sum((p.driver_payout_amount or 0.0) for p in payments)

    return jsonify({
        "success": True,
        "entries": entries,
        "summary": {
            "today": round(today_earnings, 2),
            "week": round(week_earnings, 2),
            "month": round(month_earnings, 2),
            "all_time": round(all_time_earnings, 2),
        },
    }), 200


# ---------------------------------------------------------------------------
# Stripe Webhook
# ---------------------------------------------------------------------------
webhook_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


@webhook_bp.route("/stripe", methods=["POST"])
def stripe_webhook():
    """
    Handle Stripe webhook events with signature verification.
    Events: payment_intent.succeeded, payment_intent.payment_failed,
            charge.refunded, charge.dispute.created
    """
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    stripe = _get_stripe()

    # Verify webhook signature when secret is configured
    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.error.SignatureVerificationError:
            return jsonify({"error": "Invalid signature"}), 400
        except ValueError:
            return jsonify({"error": "Invalid payload"}), 400
    else:
        # Dev mode — parse without verification
        import json
        try:
            event = json.loads(payload)
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

    event_type = event.get("type") if isinstance(event, dict) else event["type"]
    data_object = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        _handle_payment_succeeded(data_object)

    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(data_object)

    elif event_type == "charge.refunded":
        _handle_charge_refunded(data_object)

    elif event_type == "charge.dispute.created":
        _handle_dispute_created(data_object)

    elif event_type == "account.updated":
        _handle_account_updated(data_object)

    return jsonify({"received": True}), 200


def _handle_payment_succeeded(intent):
    """Mark payment as succeeded, update job to confirmed, and trigger auto-assignment."""
    intent_id = intent.get("id", "")
    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()
    if not payment:
        return

    payment.payment_status = "succeeded"
    payment.updated_at = utcnow()

    # Recalculate commission split (platform 20%, operator commission from remainder)
    amount = payment.amount or 0.0
    platform_commission = round(amount * PLATFORM_COMMISSION, 2)
    driver_gross = round(amount - platform_commission - (payment.service_fee or 0.0), 2)

    job = db.session.get(Job, payment.job_id)
    operator_payout = 0.0
    if job and job.operator_id:
        op = db.session.get(Contractor, job.operator_id)
        if op:
            rate = op.operator_commission_rate or 0.15
            operator_payout = round(driver_gross * rate, 2)

    payment.commission = platform_commission
    payment.operator_payout_amount = operator_payout
    payment.driver_payout_amount = max(0, round(driver_gross - operator_payout, 2))

    if job:
        # Move job from pending to confirmed now that payment succeeded
        if job.status == "pending":
            job.status = "confirmed"
            job.updated_at = utcnow()

        # Notify assigned contractor if one exists
        if job.driver_id:
            contractor = db.session.get(Contractor, job.driver_id)
            if contractor:
                notification = Notification(
                    id=generate_uuid(),
                    user_id=contractor.user_id,
                    type="payment",
                    title="Payment Confirmed",
                    body="Payment of ${:.2f} confirmed for job at {}.".format(
                        payment.amount, job.address or "address"
                    ),
                    data={"job_id": job.id, "amount": payment.amount},
                )
                db.session.add(notification)

        # Send customer confirmation
        customer = db.session.get(User, job.customer_id)
        if customer and customer.email:
            from notifications import send_booking_confirmation_email
            send_booking_confirmation_email(
                to_email=customer.email,
                customer_name=customer.name or "",
                booking_id=job.id,
                address=job.address or "",
                scheduled_date=str(job.scheduled_at.date()) if job.scheduled_at else "TBD",
                scheduled_time=str(job.scheduled_at.strftime("%H:%M")) if job.scheduled_at else "",
                total_amount=payment.amount,
            )

        # Auto-assign to nearest available driver
        if not job.driver_id:
            _auto_assign_driver(job)

        # Broadcast status update via SocketIO
        from socket_events import broadcast_job_status
        broadcast_job_status(job.id, job.status)

    db.session.commit()


def _auto_assign_driver(job):
    """Find the nearest online approved contractor and assign the job."""
    from math import radians, cos, sin, asin, sqrt

    EARTH_RADIUS_KM = 6371.0
    AUTO_ASSIGN_RADIUS_KM = 50.0

    def haversine(lat1, lng1, lat2, lng2):
        lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
        return 2 * EARTH_RADIUS_KM * asin(sqrt(a))

    query = Contractor.query.filter_by(
        is_online=True, approval_status="approved", is_operator=False
    )

    # If job belongs to an operator, only assign to that operator's fleet
    if job.operator_id:
        query = query.filter_by(operator_id=job.operator_id)
    else:
        # Only independent contractors (not in any fleet)
        query = query.filter(Contractor.operator_id.is_(None))

    contractors = query.all()

    if not contractors:
        return

    # If job has location, sort by distance; otherwise pick first available
    best = None
    best_dist = float("inf")

    for c in contractors:
        # Skip contractors already handling active jobs
        active = Job.query.filter(
            Job.driver_id == c.id,
            Job.status.in_(["accepted", "en_route", "arrived", "started"]),
        ).first()
        if active:
            continue

        if job.lat is not None and job.lng is not None and c.current_lat is not None and c.current_lng is not None:
            dist = haversine(job.lat, job.lng, c.current_lat, c.current_lng)
            if dist <= AUTO_ASSIGN_RADIUS_KM and dist < best_dist:
                best = c
                best_dist = dist
        elif best is None:
            best = c

    if best:
        job.driver_id = best.id
        job.status = "assigned"
        job.updated_at = utcnow()

        # Notify driver
        notification = Notification(
            id=generate_uuid(),
            user_id=best.user_id,
            type="job_assigned",
            title="New Job Assigned",
            body="You've been assigned a job at {}.".format(job.address or "an address"),
            data={"job_id": job.id, "address": job.address, "total_price": job.total_price},
        )
        db.session.add(notification)

        # Notify customer
        notification_cust = Notification(
            id=generate_uuid(),
            user_id=job.customer_id,
            type="job_update",
            title="Driver Assigned",
            body="A driver has been assigned to your job.",
            data={"job_id": job.id, "status": "assigned"},
        )
        db.session.add(notification_cust)

        # Emit SocketIO events
        from socket_events import socketio
        socketio.emit("job:assigned", {
            "job_id": job.id,
            "contractor_id": best.id,
            "contractor_name": best.user.name if best.user else None,
        }, room="driver:{}".format(best.id))

        socketio.emit("job:status", {
            "job_id": job.id,
            "status": "assigned",
            "driver_id": best.id,
        }, room=job.id)


def _handle_payment_failed(intent):
    """Mark payment as failed."""
    intent_id = intent.get("id", "")
    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()
    if not payment:
        return

    payment.payment_status = "failed"
    payment.updated_at = utcnow()

    job = db.session.get(Job, payment.job_id)
    if job:
        customer = db.session.get(User, job.customer_id)
        if customer:
            notification = Notification(
                id=generate_uuid(),
                user_id=customer.id,
                type="payment",
                title="Payment Failed",
                body="Your payment of ${:.2f} could not be processed.".format(payment.amount),
                data={"job_id": job.id},
            )
            db.session.add(notification)

    db.session.commit()


def _handle_charge_refunded(charge):
    """Mark payment as refunded."""
    intent_id = charge.get("payment_intent", "")
    if not intent_id:
        return

    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()
    if not payment:
        return

    refund_amount = charge.get("amount_refunded", 0) / 100.0
    payment.payment_status = "refunded"
    payment.updated_at = utcnow()

    job = db.session.get(Job, payment.job_id)
    if job:
        customer = db.session.get(User, job.customer_id)
        if customer:
            notification = Notification(
                id=generate_uuid(),
                user_id=customer.id,
                type="payment",
                title="Refund Processed",
                body="A refund of ${:.2f} has been issued.".format(refund_amount),
                data={"job_id": job.id, "amount": refund_amount},
            )
            db.session.add(notification)

    db.session.commit()


def _handle_dispute_created(dispute):
    """Log dispute and notify admin."""
    intent_id = dispute.get("payment_intent", "")
    if not intent_id:
        return

    payment = Payment.query.filter_by(stripe_payment_intent_id=intent_id).first()
    if not payment:
        return

    payment.payment_status = "disputed"
    payment.updated_at = utcnow()
    db.session.commit()


def _handle_account_updated(account):
    """Handle Stripe Connect account.updated webhook event."""
    import logging
    logger = logging.getLogger(__name__)

    account_id = account.get("id")
    if not account_id:
        return

    contractor = Contractor.query.filter_by(stripe_connect_id=account_id).first()
    if not contractor:
        logger.info("account.updated webhook for unknown account: %s", account_id)
        return

    charges_enabled = account.get("charges_enabled", False)
    payouts_enabled = account.get("payouts_enabled", False)

    logger.info(
        "Stripe Connect account updated: %s (contractor: %s, charges_enabled: %s, payouts_enabled: %s)",
        account_id, contractor.id, charges_enabled, payouts_enabled
    )

    # Status is derived from Stripe API calls in /connect/status endpoint
    # No model changes needed here — just log for debugging
    db.session.commit()
