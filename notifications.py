"""
Notification services for Umuve.

Email: Resend (preferred) or SendGrid (legacy fallback).
SMS: Twilio.

IMPORTANT: No function in this module should ever raise an exception.
All errors are caught and logged so that a notification failure never
takes down a booking or payment flow.

Email sending is performed asynchronously via a background thread so that
HTTP request handlers are never blocked by network I/O to the email provider.
"""

import os
import logging
import threading

from email_templates import (
    booking_confirmation_html,
    booking_assigned_html,
    driver_en_route_html,
    job_completed_html,
    payment_receipt_html,
    welcome_html,
    password_reset_html,
    job_status_update_html,
    pickup_reminder_html,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Twilio SMS
# ---------------------------------------------------------------------------
_twilio_client = None

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


def _get_twilio():
    """Lazily initialise the Twilio client."""
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        except Exception:
            logger.exception("Failed to initialise Twilio client")
    return _twilio_client


def send_sms(to_number, body):
    """Send an SMS via Twilio. Returns message SID or None.

    Never raises. Logs errors and returns None on failure.
    """
    try:
        client = _get_twilio()
        if not client or not TWILIO_FROM_NUMBER:
            logger.info("[DEV] SMS to %s: %s", to_number, body)
            return None

        message = client.messages.create(
            body=body,
            from_=TWILIO_FROM_NUMBER,
            to=to_number,
        )
        logger.info("SMS sent to %s (SID: %s)", to_number, message.sid)
        return message.sid
    except Exception:
        logger.exception("Failed to send SMS to %s", to_number)
        return None


def send_verification_sms(phone_number, code):
    """Send a verification code via SMS. Never raises."""
    try:
        body = "Your Umuve verification code is: {}. It expires in 10 minutes.".format(code)
        return send_sms(phone_number, body)
    except Exception:
        logger.exception("Failed in send_verification_sms for %s", phone_number)
        return None


def send_booking_sms(phone_number, booking_id, scheduled_date, address):
    """Send booking confirmation via SMS. Never raises."""
    try:
        short_id = str(booking_id)[:8] if booking_id else "N/A"
        body = (
            "Umuve Booking Confirmed!\n"
            "Booking: #{}\n"
            "Date: {}\n"
            "Address: {}\n\n"
            "We'll send a reminder 24h before your pickup."
        ).format(short_id, scheduled_date, address)
        return send_sms(phone_number, body)
    except Exception:
        logger.exception("Failed in send_booking_sms for %s", phone_number)
        return None


# ---------------------------------------------------------------------------
# Email — Resend (preferred) or SendGrid (legacy fallback)
# ---------------------------------------------------------------------------
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM",
                            os.environ.get("SENDGRID_FROM_EMAIL", "bookings@goumuve.com"))
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME",
                                 os.environ.get("SENDGRID_FROM_NAME", "Umuve"))


def _send_email_sync(to_email, subject, html_content):
    """Send an email synchronously via Resend (preferred) or SendGrid (fallback).

    Returns a status indicator or None in dev mode. Never raises.
    """
    try:
        # --- Resend (preferred) ---
        if RESEND_API_KEY:
            return _send_email_resend(to_email, subject, html_content)

        # --- SendGrid (legacy fallback) ---
        if SENDGRID_API_KEY:
            return _send_email_sendgrid(to_email, subject, html_content)

        # --- Dev mode: no email provider configured ---
        logger.info(
            "[DEV] Email to %s: %s — %s",
            to_email, subject, html_content[:120],
        )
        return None
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return None


def send_email(to_email, subject, html_content):
    """Send an email asynchronously in a background thread.

    This ensures the HTTP request handler is never blocked by email I/O.
    Returns immediately. Never raises.
    """
    try:
        thread = threading.Thread(
            target=_send_email_sync,
            args=(to_email, subject, html_content),
            daemon=True,
        )
        thread.start()
        logger.debug("Email queued (async) to %s: %s", to_email, subject)
    except Exception:
        logger.exception("Failed to queue async email to %s", to_email)


def send_email_sync(to_email, subject, html_content):
    """Public synchronous email sender (for cases where you need to wait).

    Prefer ``send_email`` (async) for request handlers.
    """
    return _send_email_sync(to_email, subject, html_content)


def _send_email_resend(to_email, subject, html_content):
    """Send via the Resend API. Returns the response id or None."""
    try:
        import resend
        resend.api_key = RESEND_API_KEY

        params = {
            "from": "{} <{}>".format(EMAIL_FROM_NAME, EMAIL_FROM),
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }
        response = resend.Emails.send(params)
        logger.info("Email sent via Resend to %s (id: %s)", to_email, response.get("id"))
        return response.get("id")
    except Exception:
        logger.exception("Resend email failed for %s", to_email)
        return None


def _send_email_sendgrid(to_email, subject, html_content):
    """Send via SendGrid. Returns status code or None."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=(EMAIL_FROM, EMAIL_FROM_NAME),
            to_emails=to_email,
            subject=subject,
            html_content=html_content,
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info("Email sent via SendGrid to %s (status: %s)", to_email, response.status_code)
        return response.status_code
    except Exception:
        logger.exception("SendGrid email failed for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Booking confirmation email
# ---------------------------------------------------------------------------
def send_booking_confirmation_email(to_email, customer_name, booking_id, address,
                                     scheduled_date, scheduled_time, total_amount):
    """Send a booking confirmation email. Never raises."""
    try:
        short_id = str(booking_id)[:8] if booking_id else "N/A"
        subject = "Your Umuve Booking is Confirmed! #{}".format(short_id)

        html = booking_confirmation_html(
            customer_name=customer_name,
            booking_id=booking_id,
            address=address,
            date=scheduled_date,
            time=scheduled_time,
            total=total_amount,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_booking_confirmation_email for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Job lifecycle: Driver Assigned
# ---------------------------------------------------------------------------
def send_driver_assigned_email(to_email, customer_name, driver_name, address,
                                truck_type=None, eta=None):
    """Email customer that a driver has been assigned. Never raises.

    Backward compatible: ``address`` is kept as positional for existing
    callers; ``truck_type`` and ``eta`` are optional enhancements.
    """
    try:
        subject = "Your Umuve Driver Has Been Assigned"

        html = booking_assigned_html(
            customer_name=customer_name,
            driver_name=driver_name,
            truck_type=truck_type,
            eta=eta or address,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_driver_assigned_email for %s", to_email)
        return None


def send_driver_assigned_sms(to_number, driver_name, address):
    """SMS customer that a driver has been assigned. Never raises."""
    try:
        body = "Umuve: Driver {} assigned to your pickup at {}".format(
            driver_name or "your driver", address or "your location"
        )
        return send_sms(to_number, body)
    except Exception:
        logger.exception("Failed in send_driver_assigned_sms for %s", to_number)
        return None


# ---------------------------------------------------------------------------
# Job lifecycle: Driver En Route
# ---------------------------------------------------------------------------
def send_driver_en_route_email(to_email, customer_name, driver_name, address,
                                eta_minutes=None):
    """Email customer that driver is on the way. Never raises.

    Backward compatible: ``address`` is kept as positional for existing
    callers; ``eta_minutes`` is an optional enhancement.
    """
    try:
        subject = "Your Umuve Driver Is On The Way!"

        html = driver_en_route_html(
            customer_name=customer_name,
            driver_name=driver_name,
            eta_minutes=eta_minutes,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_driver_en_route_email for %s", to_email)
        return None


# Convenience alias matching the task specification
send_en_route_email = send_driver_en_route_email


def send_driver_en_route_sms(to_number, driver_name, address):
    """SMS customer that driver is en route. Never raises."""
    try:
        body = "Umuve: Driver {} is en route to {}".format(
            driver_name or "your driver", address or "your location"
        )
        return send_sms(to_number, body)
    except Exception:
        logger.exception("Failed in send_driver_en_route_sms for %s", to_number)
        return None


# ---------------------------------------------------------------------------
# Job lifecycle: Job Completed
# ---------------------------------------------------------------------------
def send_job_completed_email(to_email, customer_name, job_id, address,
                              total=None, rating_url=None):
    """Email customer that pickup is complete, asking for a rating. Never raises.

    Backward compatible: ``job_id`` and ``address`` are positional for
    existing callers; ``total`` and ``rating_url`` are optional enhancements.
    """
    try:
        short_id = str(job_id)[:8] if job_id else "N/A"
        subject = "Your Umuve Pickup Is Complete! #{}".format(short_id)

        html = job_completed_html(
            customer_name=customer_name,
            booking_id=job_id,
            total=total,
            rating_url=rating_url,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_job_completed_email for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Payment receipt email
# ---------------------------------------------------------------------------
def send_payment_receipt_email(to_email, customer_name, job_id, address, amount,
                                payment_method_last4=None, date=None):
    """Email customer a payment receipt. Never raises.

    Backward compatible: ``job_id``, ``address``, and ``amount`` are
    positional for existing callers; ``payment_method_last4`` and ``date``
    are optional enhancements.
    """
    try:
        short_id = str(job_id)[:8] if job_id else "N/A"
        subject = "Umuve Payment Receipt #{}".format(short_id)

        html = payment_receipt_html(
            customer_name=customer_name,
            booking_id=job_id,
            amount=amount,
            payment_method_last4=payment_method_last4,
            date=date,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_payment_receipt_email for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Welcome email (new user registration)
# ---------------------------------------------------------------------------
def send_welcome_email(to_email, user_name):
    """Send a welcome email to a newly registered user. Never raises."""
    try:
        subject = "Welcome to Umuve!"

        html = welcome_html(name=user_name)

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_welcome_email for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Password reset email
# ---------------------------------------------------------------------------
def send_password_reset_email(to_email, reset_token, customer_name=None):
    """Send a password reset email. Never raises.

    Backward compatible: ``reset_token`` can be a raw token string (legacy
    callers pass just a token) or a full URL.  If it does not look like a
    URL the template builds one automatically.  ``customer_name`` is optional.
    """
    try:
        subject = "Reset Your Umuve Password"

        # Build a reset URL if the caller passed a bare token
        if reset_token and not str(reset_token).startswith("http"):
            base = os.environ.get("FRONTEND_URL", "https://goumuve.com")
            reset_url = "{}/reset-password?token={}".format(base.rstrip("/"), reset_token)
        else:
            reset_url = str(reset_token) if reset_token else ""

        html = password_reset_html(
            name=customer_name,
            reset_url=reset_url,
        )

        return send_email(to_email, subject, html)
    except Exception:
        logger.exception("Failed in send_password_reset_email for %s", to_email)
        return None


# ---------------------------------------------------------------------------
# Push notification (delegates to push_notifications.py APNs sender)
# ---------------------------------------------------------------------------
def send_push_notification(user_id, title, body, data=None, category=None):
    """Send a push notification to a user's device(s) via APNs.

    Delegates to push_notifications.send_push_notification which queries
    DeviceToken and sends real APNs pushes via HTTP/2.
    Never raises.
    """
    try:
        from push_notifications import send_push_notification as _send_apns
        return _send_apns(user_id, title, body, data=data, category=category)
    except Exception:
        logger.exception("Failed in send_push_notification for user %s", user_id)
        return None
