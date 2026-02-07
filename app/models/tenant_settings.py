"""Tenant Settings model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import JSONB


class TenantSettings(BaseModel, TenantMixin):
    """
    Tenant Settings model - configurable settings per tenant
    """
    __tablename__ = 'tenant_settings'
    
    # Business settings
    business_hours = db.Column(JSONB)  # {monday: {open: "08:00", close: "18:00"}, ...}
    service_area_radius_miles = db.Column(db.Integer, default=50)
    auto_accept_bookings = db.Column(db.Boolean, default=False)
    require_customer_signature = db.Column(db.Boolean, default=True)
    
    # Pricing & fees
    default_tax_rate = db.Column(db.Numeric(5, 4), default=0.0000)
    default_dump_fee = db.Column(db.Numeric(10, 2), default=0.00)
    
    # Notifications
    email_notifications_enabled = db.Column(db.Boolean, default=True)
    sms_notifications_enabled = db.Column(db.Boolean, default=False)
    
    # Integrations
    integrations = db.Column(JSONB, default={})  # API keys, webhooks, etc.
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('tenant_id', name='unique_settings_per_tenant'),
    )
    
    def __repr__(self):
        return f'<TenantSettings tenant={self.tenant_id}>'
    
    def get_integration_key(self, service_name):
        """Get integration API key for a service"""
        return self.integrations.get(service_name, {}).get('api_key')
    
    def set_integration_key(self, service_name, api_key, **kwargs):
        """Set integration API key for a service"""
        if not self.integrations:
            self.integrations = {}
        
        self.integrations[service_name] = {
            'api_key': api_key,
            **kwargs
        }
        db.session.commit()
