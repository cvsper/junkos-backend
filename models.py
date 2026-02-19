"""
Umuve SQLAlchemy Models
All database entities for the on-demand junk removal marketplace.
"""

import uuid
import string
import random
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Column, String, Float, Boolean, Integer, Text, DateTime, ForeignKey, JSON,
    CheckConstraint, Index
)
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def generate_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


def generate_referral_code():
    """Generate a unique 8-character alphanumeric referral code."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=True, index=True)
    phone = Column(String(20), unique=True, nullable=True, index=True)
    name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="customer")
    avatar_url = Column(Text, nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    apple_id = Column(String(255), nullable=True, unique=True)
    referral_code = Column(String(8), unique=True, nullable=True, index=True, default=generate_referral_code)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    contractor_profile = relationship("Contractor", back_populates="user", uselist=False, lazy="joined")
    referrals_made = relationship("Referral", foreign_keys="Referral.referrer_id", back_populates="referrer", lazy="dynamic")
    referral_received = relationship("Referral", foreign_keys="Referral.referee_id", back_populates="referee", uselist=False, lazy="joined")
    notifications = relationship("Notification", back_populates="user", lazy="dynamic")
    device_tokens = relationship("DeviceToken", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    ratings_given = relationship("Rating", foreign_keys="Rating.from_user_id", back_populates="from_user", lazy="dynamic")
    ratings_received = relationship("Rating", foreign_keys="Rating.to_user_id", back_populates="to_user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self, include_private=False):
        data = {
            "id": self.id,
            "email": self.email,
            "phone": self.phone,
            "name": self.name,
            "role": self.role,
            "avatar_url": self.avatar_url,
            "status": self.status,
            "referral_code": self.referral_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_private:
            data["stripe_customer_id"] = self.stripe_customer_id
        return data


# ---------------------------------------------------------------------------
# Contractor
# ---------------------------------------------------------------------------
class Contractor(db.Model):
    __tablename__ = "contractors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    license_url = Column(Text, nullable=True)
    insurance_url = Column(Text, nullable=True)
    truck_photos = Column(JSON, nullable=True, default=list)
    truck_type = Column(String(100), nullable=True)
    truck_capacity = Column(Float, nullable=True)
    stripe_connect_id = Column(String(255), nullable=True)
    is_online = Column(Boolean, default=False)
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    avg_rating = Column(Float, default=0.0)
    total_jobs = Column(Integer, default=0)
    approval_status = Column(String(20), default="pending")
    availability_schedule = Column(JSON, nullable=True, default=dict)

    # Onboarding fields
    onboarding_status = Column(String(20), default="pending")  # pending, documents_submitted, under_review, approved, rejected
    background_check_status = Column(String(20), default="not_started")  # not_started, pending, passed, failed
    insurance_document_url = Column(String(500), nullable=True)
    drivers_license_url = Column(String(500), nullable=True)
    vehicle_registration_url = Column(String(500), nullable=True)
    insurance_expiry = Column(DateTime, nullable=True)
    license_expiry = Column(DateTime, nullable=True)
    onboarding_completed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Operator fields
    is_operator = Column(Boolean, default=False)
    operator_id = Column(String(36), ForeignKey("contractors.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_commission_rate = Column(Float, default=0.15)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="contractor_profile")
    jobs = relationship("Job", back_populates="driver", lazy="dynamic", foreign_keys="Job.driver_id")
    # Self-referential: operator -> fleet contractors
    operator = relationship("Contractor", remote_side="Contractor.id", backref="fleet_contractors", foreign_keys=[operator_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user": self.user.to_dict() if self.user else None,
            "license_url": self.license_url,
            "insurance_url": self.insurance_url,
            "truck_photos": self.truck_photos or [],
            "truck_type": self.truck_type,
            "truck_capacity": self.truck_capacity,
            "stripe_connect_id": self.stripe_connect_id,
            "is_online": self.is_online,
            "current_lat": self.current_lat,
            "current_lng": self.current_lng,
            "avg_rating": self.avg_rating,
            "total_jobs": self.total_jobs,
            "approval_status": self.approval_status,
            "availability_schedule": self.availability_schedule or {},
            "onboarding_status": self.onboarding_status or "pending",
            "background_check_status": self.background_check_status or "not_started",
            "insurance_document_url": self.insurance_document_url,
            "drivers_license_url": self.drivers_license_url,
            "vehicle_registration_url": self.vehicle_registration_url,
            "insurance_expiry": self.insurance_expiry.isoformat() if self.insurance_expiry else None,
            "license_expiry": self.license_expiry.isoformat() if self.license_expiry else None,
            "onboarding_completed_at": self.onboarding_completed_at.isoformat() if self.onboarding_completed_at else None,
            "rejection_reason": self.rejection_reason,
            "is_operator": self.is_operator or False,
            "operator_id": self.operator_id,
            "operator_commission_rate": self.operator_commission_rate or 0.15,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# PromoCode
# ---------------------------------------------------------------------------
class PromoCode(db.Model):
    __tablename__ = "promo_codes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(50), unique=True, nullable=False, index=True)
    discount_type = Column(String(20), nullable=False)  # "percentage" or "fixed"
    discount_value = Column(Float, nullable=False)  # e.g., 20 for 20% or 20 for $20
    min_order_amount = Column(Float, default=0.0)
    max_discount = Column(Float, nullable=True)  # cap for percentage discounts
    max_uses = Column(Integer, nullable=True)  # null = unlimited
    use_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    created_by = Column(String(36), nullable=True)  # admin user_id

    __table_args__ = (
        CheckConstraint(
            "discount_type IN ('percentage', 'fixed')",
            name="ck_promo_discount_type",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "min_order_amount": self.min_order_amount or 0.0,
            "max_discount": self.max_discount,
            "max_uses": self.max_uses,
            "use_count": self.use_count or 0,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------
class Job(db.Model):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    driver_id = Column(String(36), ForeignKey("contractors.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_id = Column(String(36), ForeignKey("contractors.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String(30), nullable=False, default="pending")
    delegated_at = Column(DateTime, nullable=True)

    address = Column(Text, nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    items = Column(JSON, nullable=True, default=list)
    volume_estimate = Column(Float, nullable=True)
    photos = Column(JSON, nullable=True, default=list)
    before_photos = Column(JSON, nullable=True, default=list)
    after_photos = Column(JSON, nullable=True, default=list)
    proof_submitted_at = Column(DateTime, nullable=True)

    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    base_price = Column(Float, default=0.0)
    item_total = Column(Float, default=0.0)
    volume_price = Column(Float, default=0.0)
    service_fee = Column(Float, default=0.0)
    surge_multiplier = Column(Float, default=1.0)
    total_price = Column(Float, default=0.0)

    promo_code_id = Column(String(36), ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)
    discount_amount = Column(Float, default=0.0)

    notes = Column(Text, nullable=True)
    confirmation_code = Column(String(8), unique=True, nullable=True, index=True, default=generate_referral_code)

    cancelled_at = Column(DateTime, nullable=True)
    cancellation_fee = Column(Float, default=0.0)
    rescheduled_count = Column(Integer, default=0)

    volume_adjustment_proposed = Column(Boolean, default=False)
    adjusted_volume = Column(Float, nullable=True)
    adjusted_price = Column(Float, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    customer = relationship("User", foreign_keys=[customer_id], backref="customer_jobs")
    driver = relationship("Contractor", foreign_keys=[driver_id], back_populates="jobs")
    operator_rel = relationship("Contractor", foreign_keys=[operator_id], backref="operator_jobs")
    payment = relationship("Payment", back_populates="job", uselist=False, lazy="joined")
    rating = relationship("Rating", back_populates="job", uselist=False, lazy="joined")
    promo_code = relationship("PromoCode", foreign_keys=[promo_code_id], backref="jobs")

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_location", "lat", "lng"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "driver_id": self.driver_id,
            "operator_id": self.operator_id,
            "status": self.status,
            "delegated_at": self.delegated_at.isoformat() if self.delegated_at else None,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "items": self.items or [],
            "volume_estimate": self.volume_estimate,
            "photos": self.photos or [],
            "before_photos": self.before_photos or [],
            "after_photos": self.after_photos or [],
            "proof_submitted_at": self.proof_submitted_at.isoformat() if self.proof_submitted_at else None,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "base_price": self.base_price,
            "item_total": self.item_total,
            "volume_price": self.volume_price,
            "service_fee": self.service_fee,
            "surge_multiplier": self.surge_multiplier,
            "total_price": self.total_price,
            "promo_code_id": self.promo_code_id,
            "discount_amount": self.discount_amount or 0.0,
            "notes": self.notes,
            "confirmation_code": self.confirmation_code,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_fee": self.cancellation_fee or 0.0,
            "rescheduled_count": self.rescheduled_count or 0,
            "volume_adjustment_proposed": self.volume_adjustment_proposed,
            "adjusted_volume": self.adjusted_volume,
            "adjusted_price": self.adjusted_price,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------
class Rating(db.Model):
    __tablename__ = "ratings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    from_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stars = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("stars >= 1 AND stars <= 5", name="ck_rating_stars"),
    )

    job = relationship("Job", back_populates="rating")
    from_user = relationship("User", foreign_keys=[from_user_id], back_populates="ratings_given")
    to_user = relationship("User", foreign_keys=[to_user_id], back_populates="ratings_received")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "from_user_id": self.from_user_id,
            "to_user_id": self.to_user_id,
            "stars": self.stars,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "from_user": self.from_user.to_dict() if self.from_user else None,
        }


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
class Payment(db.Model):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True)
    amount = Column(Float, nullable=False, default=0.0)
    service_fee = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    driver_payout_amount = Column(Float, default=0.0)
    operator_payout_amount = Column(Float, default=0.0)
    payout_status = Column(String(30), default="pending")
    payment_status = Column(String(30), default="pending")
    tip_amount = Column(Float, default=0.0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    job = relationship("Job", back_populates="payment")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "stripe_payment_intent_id": self.stripe_payment_intent_id,
            "amount": self.amount,
            "service_fee": self.service_fee,
            "commission": self.commission,
            "driver_payout_amount": self.driver_payout_amount,
            "operator_payout_amount": self.operator_payout_amount or 0.0,
            "payout_status": self.payout_status,
            "payment_status": self.payment_status,
            "tip_amount": self.tip_amount,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# PricingRule
# ---------------------------------------------------------------------------
class PricingRule(db.Model):
    __tablename__ = "pricing_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    item_type = Column(String(100), nullable=False, unique=True)
    base_price = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "item_type": self.item_type,
            "base_price": self.base_price,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# SurgeZone
# ---------------------------------------------------------------------------
class SurgeZone(db.Model):
    __tablename__ = "surge_zones"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    boundary = Column(JSON, nullable=True)
    surge_multiplier = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    start_time = Column(String(5), nullable=True)
    end_time = Column(String(5), nullable=True)
    days_of_week = Column(JSON, nullable=True, default=list)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "boundary": self.boundary,
            "surge_multiplier": self.surge_multiplier,
            "is_active": self.is_active,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "days_of_week": self.days_of_week or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
class Notification(db.Model):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="notifications")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# OperatorInvite
# ---------------------------------------------------------------------------
class OperatorInvite(db.Model):
    __tablename__ = "operator_invites"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    operator_id = Column(String(36), ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    invite_code = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    max_uses = Column(Integer, default=1)
    use_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    operator = relationship("Contractor", foreign_keys=[operator_id])

    def to_dict(self):
        return {
            "id": self.id,
            "operator_id": self.operator_id,
            "invite_code": self.invite_code,
            "email": self.email,
            "max_uses": self.max_uses,
            "use_count": self.use_count,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# DeviceToken (APNs / FCM push notification tokens)
# ---------------------------------------------------------------------------
class DeviceToken(db.Model):
    __tablename__ = "device_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(512), unique=True, nullable=False)
    platform = Column(String(10), nullable=False, default="ios")  # "ios" or "android"
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("platform IN ('ios', 'android')", name="ck_device_token_platform"),
    )

    user = relationship("User", back_populates="device_tokens")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "token": self.token,
            "platform": self.platform,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# PricingConfig (singleton-style key/value for admin-overridable settings)
# ---------------------------------------------------------------------------
class PricingConfig(db.Model):
    __tablename__ = "pricing_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# RecurringBooking
# ---------------------------------------------------------------------------
class RecurringBooking(db.Model):
    __tablename__ = "recurring_bookings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    frequency = Column(String(20), nullable=False)  # "weekly", "biweekly", "monthly"
    day_of_week = Column(Integer, nullable=True)     # 0=Monday .. 6=Sunday (for weekly/biweekly)
    day_of_month = Column(Integer, nullable=True)    # 1-28 (for monthly)
    preferred_time = Column(String(5), nullable=False, default="09:00")  # "HH:MM"

    address = Column(Text, nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    items = Column(JSON, nullable=True, default=list)
    notes = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    next_scheduled_at = Column(DateTime, nullable=True)
    total_bookings_created = Column(Integer, default=0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('weekly', 'biweekly', 'monthly')",
            name="ck_recurring_frequency",
        ),
        CheckConstraint(
            "day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)",
            name="ck_recurring_day_of_week",
        ),
        CheckConstraint(
            "day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 28)",
            name="ck_recurring_day_of_month",
        ),
    )

    customer = relationship("User", foreign_keys=[customer_id], backref="recurring_bookings")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "frequency": self.frequency,
            "day_of_week": self.day_of_week,
            "day_of_month": self.day_of_month,
            "preferred_time": self.preferred_time,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "items": self.items or [],
            "notes": self.notes,
            "is_active": self.is_active,
            "next_scheduled_at": self.next_scheduled_at.isoformat() if self.next_scheduled_at else None,
            "total_bookings_created": self.total_bookings_created,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------
class Referral(db.Model):
    __tablename__ = "referrals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    referrer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referee_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    referral_code = Column(String(8), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    reward_amount = Column(Float, default=10.00)
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'signed_up', 'completed', 'rewarded')",
            name="ck_referral_status",
        ),
    )

    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals_made")
    referee = relationship("User", foreign_keys=[referee_id], back_populates="referral_received")

    def to_dict(self):
        return {
            "id": self.id,
            "referrer_id": self.referrer_id,
            "referee_id": self.referee_id,
            "referral_code": self.referral_code,
            "status": self.status,
            "reward_amount": self.reward_amount,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "referrer_name": self.referrer.name if self.referrer else None,
            "referee_name": self.referee.name if self.referee else None,
        }


# ---------------------------------------------------------------------------
# SupportMessage
# ---------------------------------------------------------------------------
class SupportMessage(db.Model):
    __tablename__ = "support_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="other")
    status = Column(String(20), nullable=False, default="open")

    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="ck_support_message_status"),
        Index("ix_support_messages_status", "status"),
    )

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "message": self.message,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------
class Refund(db.Model):
    __tablename__ = "refunds"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    payment_id = Column(String(36), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    stripe_refund_id = Column(String(255), nullable=True, unique=True)
    status = Column(String(30), nullable=False, default="pending")
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'cancelled')",
            name="ck_refund_status",
        ),
    )

    payment = relationship("Payment", backref="refunds")

    def to_dict(self):
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "amount": self.amount,
            "reason": self.reason,
            "stripe_refund_id": self.stripe_refund_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# WebhookEvent (audit log for all incoming Stripe webhook events)
# ---------------------------------------------------------------------------
class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    stripe_event_id = Column(String(255), nullable=True, unique=True, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="processed")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "stripe_event_id": self.stripe_event_id,
            "event_type": self.event_type,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# ChatMessage (real-time chat between customer and driver on a job)
# ---------------------------------------------------------------------------
class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(String(36), nullable=False)  # user_id
    sender_role = Column(String(20), nullable=False)  # "customer" or "driver"
    message = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    job = relationship("Job", backref="chat_messages")

    __table_args__ = (
        CheckConstraint("sender_role IN ('customer', 'driver')", name="ck_chat_sender_role"),
        Index("ix_chat_messages_job_created", "job_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "sender_id": self.sender_id,
            "sender_role": self.sender_role,
            "message": self.message,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Review (customer review of a completed job)
# ---------------------------------------------------------------------------
class Review(db.Model):
    __tablename__ = "reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    contractor_id = Column(String(36), ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating"),
    )

    job = relationship("Job", backref="review")
    customer = relationship("User", foreign_keys=[customer_id])
    contractor = relationship("Contractor", backref="reviews")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "customer_id": self.customer_id,
            "contractor_id": self.contractor_id,
            "rating": self.rating,
            "comment": self.comment,
            "customer_name": self.customer.name if self.customer else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }



# ---------------------------------------------------------------------------
# OperatorApplication (landing page operator signup form)
# ---------------------------------------------------------------------------
class OperatorApplication(db.Model):
    __tablename__ = "operator_applications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    city = Column(String(100), nullable=False)
    trucks = Column(String(20), nullable=True)
    experience = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, rejected
    rejection_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "city": self.city,
            "trucks": self.trucks,
            "experience": self.experience,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
