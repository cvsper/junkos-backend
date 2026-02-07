"""Service model"""
from app import db
from .base import BaseModel, TenantMixin


class Service(BaseModel, TenantMixin):
    """
    Service model - types of junk removal services offered
    """
    __tablename__ = 'services'
    
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Pricing
    pricing_type = db.Column(db.String(50), nullable=False)  # fixed, volume_based, hourly, custom
    base_price = db.Column(db.Numeric(10, 2))
    price_per_unit = db.Column(db.Numeric(10, 2))
    unit_type = db.Column(db.String(50))  # cubic_yard, hour, item, etc.
    
    # Service settings
    estimated_duration_minutes = db.Column(db.Integer)
    requires_dump_fee = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_services_active', 'tenant_id', 'active'),
    )
    
    # Relationships
    jobs = db.relationship('Job', backref='service', lazy='dynamic')
    
    def __repr__(self):
        return f'<Service {self.name}>'
    
    def calculate_price(self, quantity=1):
        """
        Calculate price based on pricing type
        
        Args:
            quantity: Quantity of units (volume, hours, etc.)
            
        Returns:
            float: Calculated price
        """
        if self.pricing_type == 'fixed':
            return float(self.base_price)
        elif self.pricing_type in ['volume_based', 'hourly']:
            return float(self.base_price or 0) + float(self.price_per_unit or 0) * quantity
        else:
            return 0.0  # Custom pricing requires manual quote
