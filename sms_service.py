"""
Umuve SMS Service

Centralised SMS sending via Twilio with:
- Phone number formatting (ensures +1 prefix for US numbers)
- Graceful fallback when credentials are not configured
- Background-thread sending so SMS never blocks a request
- Pre-built message helpers for every job lifecycle event

IMPORTANT: No function in this module should ever raise an exception.
All errors are caught and logged so that an SMS failure never takes down
a booking or payment flow.
"""

import os
import re
import logging
import threading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Twilio configuration (lazy-initialised)
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER",
                                     os.environ.get("TWILIO_FROM_NUMBER", ""))

_twilio_client = None


def _get_twilio():
    """Lazily initialise the Twilio REST client."""
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        except Exception:
            logger.exception("Failed to initialise Twilio client")
    return _twilio_client


# ---------------------------------------------------------------------------
# Phone number formatting
# ---------------------------------------------------------------------------
def format_phone(phone):
    """Ensure a US phone number has the +1 international prefix.

    Handles common input formats:
        "3055551234"       -> "+13055551234"
        "13055551234"      -> "+13055551234"
        "+13055551234"     -> "+13055551234"
        "(305) 555-1234"   -> "+13055551234"
        ""                 -> ""
        None               -> ""

    Non-US numbers that already start with '+' are returned as-is.
    """
    if not phone:
        return ""

    # Strip everything except digits and leading '+'
    stripped = re.sub(r"[^\d+]", "", phone.strip())

    if not stripped:
        return ""

    # Already has international prefix
    if stripped.startswith("+"):
        return stripped

    # Digits only from here
    digits = re.sub(r"\D", "", stripped)

    if len(digits) == 10:
        # US 10-digit number -> prepend +1
        return "+1{}".format(digits)
    elif len(digits) == 11 and digits.startswith("1"):
        # US 11-digit with leading 1 -> prepend +
        return "+{}".format(digits)
    else:
        # Best effort: prepend + and hope for the best
        return "+{}".format(digits)


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------
def send_sms(to_phone, message):
    """Send an SMS via Twilio. Returns the message SID or None.

    If Twilio credentials are not configured, logs the message content at
    INFO level (dev/test fallback) and returns None.

    Never raises.
    """
    try:
        formatted = format_phone(to_phone)
        if not formatted:
            logger.warning("send_sms called with empty/invalid phone: %r", to_phone)
            return None

        client = _get_twilio()
        if not client or not TWILIO_PHONE_NUMBER:
            logger.info("[SMS-DEV] To %s: %s", formatted, message)
            return None

        msg = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=formatted,
        )
        logger.info("SMS sent to %s (SID: %s)", formatted, msg.sid)
        return msg.sid
    except Exception:
        logger.exception("Failed to send SMS to %s", to_phone)
        return None


def send_sms_async(to_phone, message):
    """Send an SMS in a background thread so the calling request is not blocked.

    Returns the Thread object (useful for testing), or None if the phone is
    empty.  Never raises.
    """
    try:
        if not to_phone:
            return None
        t = threading.Thread(
            target=send_sms,
            args=(to_phone, message),
            daemon=True,
        )
        t.start()
        return t
    except Exception:
        logger.exception("Failed to start background SMS thread for %s", to_phone)
        return None


# ---------------------------------------------------------------------------
# Job lifecycle SMS helpers
# ---------------------------------------------------------------------------

def sms_booking_confirmed(to_phone, job_id, date, time):
    """Booking confirmed -> SMS to customer.

    Message: "Your Umuve pickup is confirmed for {date} at {time}. Job #{job_id}"
    """
    try:
        short_id = str(job_id)[:8] if job_id else "N/A"
        body = (
            "Your Umuve pickup is confirmed for {} at {}. "
            "Job #{}"
        ).format(date or "TBD", time or "TBD", short_id)
        return send_sms_async(to_phone, body)
    except Exception:
        logger.exception("sms_booking_confirmed failed for %s", to_phone)
        return None


def sms_driver_en_route(to_phone, driver_name, tracking_url=None):
    """Driver en_route -> SMS to customer.

    Message: "Your driver {name} is on the way! Track live: {tracking_url}"
    """
    try:
        name = driver_name or "your driver"
        if tracking_url:
            body = (
                "Your driver {} is on the way! "
                "Track live: {}"
            ).format(name, tracking_url)
        else:
            body = "Your driver {} is on the way!".format(name)
        return send_sms_async(to_phone, body)
    except Exception:
        logger.exception("sms_driver_en_route failed for %s", to_phone)
        return None


def sms_driver_arrived(to_phone, address):
    """Driver arrived -> SMS to customer.

    Message: "Your driver has arrived at {address}!"
    """
    try:
        body = "Your driver has arrived at {}!".format(address or "your location")
        return send_sms_async(to_phone, body)
    except Exception:
        logger.exception("sms_driver_arrived failed for %s", to_phone)
        return None


def sms_job_completed(to_phone, amount):
    """Job completed -> SMS to customer.

    Message: "Pickup complete! Total: ${amount}. Thank you!"
    """
    try:
        if amount is not None:
            body = "Pickup complete! Total: ${:.2f}. Thank you for using Umuve!".format(
                float(amount)
            )
        else:
            body = "Pickup complete! Thank you for using Umuve!"
        return send_sms_async(to_phone, body)
    except Exception:
        logger.exception("sms_job_completed failed for %s", to_phone)
        return None


def sms_pickup_reminder(to_phone, job_id, date, time, address):
    """24-hour pickup reminder -> SMS to customer.

    Intended to be called by a scheduler (not wired up here).
    Message: "Reminder: Your Umuve pickup is tomorrow at {time}. Job #{job_id}"
    """
    try:
        short_id = str(job_id)[:8] if job_id else "N/A"
        body = (
            "Reminder: Your Umuve pickup is tomorrow at {} at {}. "
            "Job #{}\n"
            "Address: {}"
        ).format(date or "your scheduled date", time or "the scheduled time",
                 short_id, address or "your location")
        return send_sms_async(to_phone, body)
    except Exception:
        logger.exception("sms_pickup_reminder failed for %s", to_phone)
        return None


def sms_custom(to_phone, message):
    """Send a custom / freeform SMS (used by the admin endpoint).

    Sends in a background thread. Never raises.
    """
    try:
        return send_sms_async(to_phone, message)
    except Exception:
        logger.exception("sms_custom failed for %s", to_phone)
        return None
