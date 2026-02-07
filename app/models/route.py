"""Route model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID, JSONB


class Route(BaseModel, TenantMixin):
    """
    Route model - daily optimized routes for drivers
    """
    __tablename__ = 'routes'
    
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    route_date = db.Column(db.Date, nullable=False)
    route_name = db.Column(db.String(255))
    
    status = db.Column(db.String(50), default='planned')  # planned, in_progress, completed
    
    # Route optimization data
    total_distance_miles = db.Column(db.Numeric(10, 2))
    estimated_duration_minutes = db.Column(db.Integer)
    optimized_order = db.Column(JSONB)  # Array of job_ids in optimized order
    
    started_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    
    # Indexes
    __table_args__ = (
        db.Index('idx_routes_user_id', 'tenant_id', 'user_id'),
        db.Index('idx_routes_date', 'tenant_id', 'route_date'),
    )
    
    def __repr__(self):
        return f'<Route {self.route_name} - {self.route_date}>'
    
    def start(self):
        """Start the route"""
        from datetime import datetime
        self.status = 'in_progress'
        self.started_at = datetime.utcnow()
    
    def complete(self):
        """Complete the route"""
        from datetime import datetime
        self.status = 'completed'
        self.completed_at = datetime.utcnow()
