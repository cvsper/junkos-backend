"""
Umuve APNs Push Notification Service

Sends iOS push notifications via Apple's HTTP/2 APNs gateway.
Uses a .p8 auth key (token-based authentication) and httpx for HTTP/2 support.

Required environment variables:
    APNS_KEY_ID        - The 10-character Key ID from Apple Developer portal
    APNS_TEAM_ID       - Your Apple Developer Team ID
    APNS_AUTH_KEY_PATH - Absolute path to the .p8 private key file
    APNS_BUNDLE_ID     - Your app's bundle identifier (e.g. com.goumuve.driver)
    FLASK_ENV          - When "development", uses the APNs sandbox endpoint
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import jwt  # PyJWT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APNs endpoints
# ---------------------------------------------------------------------------
APNS_PRODUCTION_URL = "https://api.push.apple.com"
APNS_SANDBOX_URL = "https://api.sandbox.push.apple.com"

# ---------------------------------------------------------------------------
# Configuration (read once at import time; safe to re-read later)
# ---------------------------------------------------------------------------
APNS_KEY_ID = os.environ.get("APNS_KEY_ID", "")
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID", "")
APNS_AUTH_KEY_PATH = os.environ.get("APNS_AUTH_KEY_PATH", "")
APNS_BUNDLE_ID = os.environ.get("APNS_BUNDLE_ID", "")

# Cache the signing key bytes so we only read the file once
_auth_key_bytes: bytes | None = None
# Cache the bearer token and its issue time so we can reuse it (Apple
# recommends reusing tokens for ~20 minutes before refreshing).
_cached_token: str | None = None
_cached_token_issued_at: float = 0.0
_TOKEN_REFRESH_INTERVAL = 50 * 60  # refresh every 50 minutes (valid for 60)


def _is_configured() -> bool:
    """Return True when all required APNs env vars are set."""
    return bool(APNS_KEY_ID and APNS_TEAM_ID and APNS_AUTH_KEY_PATH and APNS_BUNDLE_ID)


def _get_apns_base_url() -> str:
    """Return the APNs gateway URL based on the environment."""
    if os.environ.get("FLASK_ENV", "development") == "development":
        return APNS_SANDBOX_URL
    return APNS_PRODUCTION_URL


def _load_auth_key() -> bytes:
    """Load the .p8 private key from disk (cached after first read)."""
    global _auth_key_bytes
    if _auth_key_bytes is not None:
        return _auth_key_bytes
    try:
        with open(APNS_AUTH_KEY_PATH, "rb") as f:
            _auth_key_bytes = f.read()
        logger.info("APNs auth key loaded from %s", APNS_AUTH_KEY_PATH)
        return _auth_key_bytes
    except Exception:
        logger.exception("Failed to load APNs auth key from %s", APNS_AUTH_KEY_PATH)
        raise


def _get_bearer_token() -> str:
    """Create (or return cached) APNs bearer token signed with the .p8 key.

    Apple requires ES256-signed JWTs. The token contains:
        iss  - Team ID
        iat  - Issued-at timestamp
        kid  - Key ID (set in the JWT header)
    """
    global _cached_token, _cached_token_issued_at

    now = time.time()
    if _cached_token and (now - _cached_token_issued_at) < _TOKEN_REFRESH_INTERVAL:
        return _cached_token

    key_data = _load_auth_key()
    issued_at = int(now)

    token = jwt.encode(
        {"iss": APNS_TEAM_ID, "iat": issued_at},
        key_data,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID},
    )

    _cached_token = token
    _cached_token_issued_at = now
    logger.debug("APNs bearer token generated (iat=%d)", issued_at)
    return token


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_push_to_token(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
    badge: int | None = None,
    sound: str = "default",
    category: str | None = None,
) -> bool:
    """Send a push notification to a single APNs device token.

    Returns True on success, False on any failure.  Never raises.
    """
    if not _is_configured():
        logger.warning(
            "APNs is not configured (missing env vars). Skipping push to token=%s...",
            token[:12] if token else "None",
        )
        return False

    try:
        import httpx  # imported here so the module can be loaded even if httpx is absent

        base_url = _get_apns_base_url()
        url = f"{base_url}/3/device/{token}"
        bearer = _get_bearer_token()

        # Build the APNs payload
        aps_payload: dict = {
            "alert": {"title": title, "body": body},
            "sound": sound,
        }
        if badge is not None:
            aps_payload["badge"] = badge
        if category:
            aps_payload["category"] = category

        payload: dict = {"aps": aps_payload}
        if data:
            payload.update(data)

        headers = {
            "authorization": f"bearer {bearer}",
            "apns-topic": APNS_BUNDLE_ID,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-expiration": "0",
        }

        logger.info(
            "Sending APNs push: token=%s... title=%r url=%s",
            token[:12],
            title,
            base_url,
        )

        with httpx.Client(http2=True, timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            logger.info("APNs push sent successfully to token=%s...", token[:12])
            return True

        # APNs returns JSON with a "reason" field on error
        try:
            error_body = response.json()
        except Exception:
            error_body = response.text

        logger.error(
            "APNs push failed: status=%d token=%s... reason=%s",
            response.status_code,
            token[:12],
            error_body,
        )

        # If the token is invalid, remove it from the database
        if response.status_code == 410 or (
            isinstance(error_body, dict) and error_body.get("reason") == "BadDeviceToken"
        ):
            _remove_invalid_token(token)

        return False

    except Exception:
        logger.exception("APNs push failed with exception for token=%s...", token[:12] if token else "None")
        return False


def send_push_notification(
    user_id: str,
    title: str,
    body: str,
    data: dict | None = None,
    badge: int | None = None,
    category: str | None = None,
) -> int:
    """Send a push notification to all registered devices for a user.

    Returns the number of tokens that were successfully sent to.
    Never raises.
    """
    try:
        from models import DeviceToken

        tokens = DeviceToken.query.filter_by(user_id=user_id, platform="ios").all()

        if not tokens:
            logger.info("No iOS device tokens registered for user_id=%s", user_id)
            return 0

        logger.info(
            "Sending push to %d device(s) for user_id=%s: title=%r",
            len(tokens),
            user_id,
            title,
        )

        success_count = 0
        for dt in tokens:
            if send_push_to_token(dt.token, title, body, data=data, badge=badge, category=category):
                success_count += 1

        logger.info(
            "Push results for user_id=%s: %d/%d succeeded",
            user_id,
            success_count,
            len(tokens),
        )
        return success_count

    except Exception:
        logger.exception("send_push_notification failed for user_id=%s", user_id)
        return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _remove_invalid_token(token: str) -> None:
    """Remove an invalid device token from the database.

    Called when APNs responds with 410 Gone or BadDeviceToken.
    """
    try:
        from models import db, DeviceToken

        dt = DeviceToken.query.filter_by(token=token).first()
        if dt:
            logger.info("Removing invalid device token id=%s token=%s...", dt.id, token[:12])
            db.session.delete(dt)
            db.session.commit()
    except Exception:
        logger.exception("Failed to remove invalid device token=%s...", token[:12])
