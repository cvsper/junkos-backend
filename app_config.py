import os
import secrets
from dotenv import load_dotenv

load_dotenv()

# Database rename fallback: migrate junkos.db -> umuve.db seamlessly
_DB_NAME = 'umuve.db'
if not os.path.exists(_DB_NAME) and os.path.exists('junkos.db'):
    os.rename('junkos.db', _DB_NAME)


def _require_in_production(var_name, default):
    """Return env var value. In production, warn loudly if still using default."""
    value = os.environ.get(var_name, "")
    if value:
        return value
    env = os.environ.get("FLASK_ENV", "development")
    if env != "development" and default:
        import logging
        logging.getLogger(__name__).warning(
            "%s is using an insecure default. Set it via environment variable!", var_name
        )
    return default


class Config:
    """Application configuration"""

    # Flask
    SECRET_KEY = _require_in_production(
        'SECRET_KEY', 'dev-only-' + secrets.token_hex(16)
    )
    DEBUG = os.environ.get('FLASK_ENV', 'development') == 'development'

    # API Security
    API_KEY = _require_in_production(
        'API_KEY', 'dev-only-' + secrets.token_hex(16)
    )

    # JWT Authentication
    JWT_SECRET = _require_in_production(
        'JWT_SECRET', 'dev-only-' + secrets.token_hex(32)
    )

    # Admin seed secret (used by /api/auth/seed-admin)
    ADMIN_SEED_SECRET = os.environ.get('ADMIN_SEED_SECRET', '')

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 'umuve.db')

    # CORS - Allow iOS app origin
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')

    # Pricing
    BASE_PRICE = float(os.environ.get('BASE_PRICE', '50.0'))

    # Stripe
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    # Twilio SMS
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')

    # Email: Resend (preferred) or SendGrid (legacy)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
    EMAIL_FROM = os.environ.get('EMAIL_FROM', 'bookings@goumuve.com')
    EMAIL_FROM_NAME = os.environ.get('EMAIL_FROM_NAME', 'Umuve')

    # Server
    PORT = int(os.environ.get('PORT', '8080'))
