"""
Umuve API Route Blueprints
"""
from .drivers import drivers_bp
from .pricing import pricing_bp
from .ratings import ratings_bp
from .admin import admin_bp
from .payments import payments_bp, webhook_bp
from .booking import booking_bp
from .upload import upload_bp
from .jobs import jobs_bp
from .tracking import tracking_bp
from .driver import driver_bp
from .operator import operator_bp
from .push import push_bp
from .service_area import service_area_bp
from .recurring import recurring_bp
from .referrals import referrals_bp
from .support import support_bp
from .chat import chat_bp
from .onboarding import onboarding_bp
from .promos import promos_bp
from .reviews import reviews_bp
from .operator_applications import operator_applications_bp

__all__ = [
    "drivers_bp",
    "pricing_bp",
    "ratings_bp",
    "admin_bp",
    "payments_bp",
    "webhook_bp",
    "booking_bp",
    "upload_bp",
    "jobs_bp",
    "tracking_bp",
    "driver_bp",
    "operator_bp",
    "push_bp",
    "service_area_bp",
    "recurring_bp",
    "referrals_bp",
    "support_bp",
    "chat_bp",
    "onboarding_bp",
    "promos_bp",
    "reviews_bp",
    "operator_applications_bp",
]
