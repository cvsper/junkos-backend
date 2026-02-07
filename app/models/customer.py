"""Customer model"""
from app import db
from .base import BaseModel, TenantMixin


class Customer(BaseModel, TenantMixin):
    """
    Customer model - end customers who book junk removal services
    """
    __tablename__ = 'customers'
    
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), index=True)
    phone = db.Column(db.String(50), nullable=False)
    
    # Address
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(2), default='US')
    
    # Geolocation
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    
    # CRM
    notes = db.Column(db.Text)
    rating = db.Column(db.Numeric(3, 2))
    total_jobs_completed = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Numeric(10, 2), default=0.00)
    
    # Marketing
    marketing_opt_in = db.Column(db.Boolean, default=False)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_customers_phone', 'tenant_id', 'phone'),
        db.Index('idx_customers_email', 'tenant_id', 'email'),
    )
    
    # Relationships
    jobs = db.relationship('Job', backref='customer', lazy='dynamic')
    invoices = db.relationship('Invoice', backref='customer', lazy='dynamic')
    
    def __repr__(self):
        return f'<Customer {self.full_name}>'
    
    @property
    def full_name(self):
        """Get full name"""
        return f'{self.first_name} {self.last_name}'
    
    @property
    def full_address(self):
        """Get formatted full address"""
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f'{self.city}, {self.state} {self.postal_code}')
        return '\n'.join(parts)
    
    def to_dict(self):
        """Convert to dictionary"""
        data = super().to_dict()
        data['full_name'] = self.full_name
        data['full_address'] = self.full_address
        return data
