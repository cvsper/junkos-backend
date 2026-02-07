"""Tenant model"""
from app import db
from .base import BaseModel
from sqlalchemy.dialects.postgresql import JSONB


class Tenant(BaseModel):
    """
    Tenant model - represents a customer organization using the platform
    Each tenant has isolated data for multi-tenancy
    """
    __tablename__ = 'tenants'
    
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='active')
    subscription_tier = db.Column(db.String(50), nullable=False, default='basic')
    
    contact_email = db.Column(db.String(255), nullable=False)
    contact_phone = db.Column(db.String(50))
    
    # White-label branding
    branding_config = db.Column(JSONB, default={
        'logo_url': None,
        'primary_color': '#3B82F6',
        'secondary_color': '#10B981',
        'company_name': None,
        'custom_domain': None,
        'email_from_name': None,
        'email_from_address': None
    })
    
    # Billing
    billing_address = db.Column(db.Text)
    billing_email = db.Column(db.String(255))
    
    # Subscription tracking
    trial_ends_at = db.Column(db.DateTime(timezone=True))
    subscription_started_at = db.Column(db.DateTime(timezone=True))
    subscription_cancelled_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    users = db.relationship('User', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    customers = db.relationship('Customer', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    jobs = db.relationship('Job', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Tenant {self.name} ({self.slug})>'
    
    def is_active(self):
        """Check if tenant is active"""
        return self.status in ['active', 'trial']
    
    def to_dict(self, include_branding=False):
        """Convert to dictionary with optional branding config"""
        data = super().to_dict(exclude=['billing_address', 'billing_email'])
        
        if not include_branding:
            data.pop('branding_config', None)
        
        return data
