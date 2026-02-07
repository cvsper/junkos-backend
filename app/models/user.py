"""User model"""
from app import db
from .base import BaseModel, TenantMixin
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.postgresql import JSONB


class User(BaseModel, TenantMixin, UserMixin):
    """
    User model - admins, dispatchers, and drivers
    Includes Flask-Login integration
    """
    __tablename__ = 'users'
    
    email = db.Column(db.String(255), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    
    role = db.Column(db.String(50), nullable=False)  # admin, dispatcher, driver
    status = db.Column(db.String(50), nullable=False, default='active')
    
    # Driver-specific fields
    driver_license_number = db.Column(db.String(100))
    driver_license_expiry = db.Column(db.Date)
    vehicle_info = db.Column(JSONB)  # {type, make, model, year, plate, capacity}
    
    # Authentication & security
    email_verified_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    password_changed_at = db.Column(db.DateTime(timezone=True))
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'email', name='unique_email_per_tenant'),
        db.Index('idx_users_role', 'tenant_id', 'role'),
        db.Index('idx_users_status', 'tenant_id', 'status'),
    )
    
    # Relationships
    job_assignments = db.relationship('JobAssignment', backref='user', lazy='dynamic')
    routes = db.relationship('Route', backref='driver', lazy='dynamic')
    
    def __repr__(self):
        return f'<User {self.email} ({self.role})>'
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)
    
    @property
    def full_name(self):
        """Get full name"""
        return f'{self.first_name} {self.last_name}'
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == 'admin'
    
    def is_dispatcher(self):
        """Check if user is dispatcher"""
        return self.role == 'dispatcher'
    
    def is_driver(self):
        """Check if user is driver"""
        return self.role == 'driver'
    
    def is_active(self):
        """Check if user is active (required by Flask-Login)"""
        return self.status == 'active' and self.deleted_at is None
    
    def to_dict(self, include_sensitive=False):
        """Convert to dictionary, optionally exclude sensitive fields"""
        exclude = ['password_hash']
        if not include_sensitive:
            exclude.extend(['driver_license_number', 'driver_license_expiry'])
        
        data = super().to_dict(exclude=exclude)
        data['full_name'] = self.full_name
        
        return data
