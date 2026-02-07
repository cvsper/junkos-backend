"""Job model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID


class Job(BaseModel, TenantMixin):
    """
    Job model - core entity representing a junk removal booking
    """
    __tablename__ = 'jobs'
    
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey('services.id', ondelete='RESTRICT'))
    
    # Job identification
    job_number = db.Column(db.String(50), nullable=False)
    
    # Scheduling
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time_start = db.Column(db.Time)
    scheduled_time_end = db.Column(db.Time)
    estimated_duration_minutes = db.Column(db.Integer)
    
    # Job details
    status = db.Column(db.String(50), nullable=False, default='pending')
    priority = db.Column(db.String(50), default='normal')
    
    # Service location
    service_address_line1 = db.Column(db.String(255), nullable=False)
    service_address_line2 = db.Column(db.String(255))
    service_city = db.Column(db.String(100), nullable=False)
    service_state = db.Column(db.String(50), nullable=False)
    service_postal_code = db.Column(db.String(20), nullable=False)
    service_country = db.Column(db.String(2), default='US')
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    
    # Job specifics
    items_description = db.Column(db.Text)
    special_instructions = db.Column(db.Text)
    access_instructions = db.Column(db.Text)
    
    # Volume/quantity
    estimated_volume = db.Column(db.Numeric(10, 2))
    actual_volume = db.Column(db.Numeric(10, 2))
    
    # Timing tracking
    actual_start_time = db.Column(db.DateTime(timezone=True))
    actual_end_time = db.Column(db.DateTime(timezone=True))
    
    # Customer feedback
    customer_rating = db.Column(db.Integer)
    customer_feedback = db.Column(db.Text)
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'job_number', name='unique_job_number_per_tenant'),
        db.Index('idx_jobs_status', 'tenant_id', 'status'),
        db.Index('idx_jobs_scheduled_date', 'tenant_id', 'scheduled_date'),
        db.Index('idx_jobs_customer_id', 'tenant_id', 'customer_id'),
    )
    
    # Relationships
    assignments = db.relationship('JobAssignment', backref='job', lazy='dynamic', cascade='all, delete-orphan')
    photos = db.relationship('Photo', backref='job', lazy='dynamic', cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='job', lazy='dynamic')
    
    def __repr__(self):
        return f'<Job {self.job_number} - {self.status}>'
    
    @property
    def service_address(self):
        """Get formatted service address"""
        parts = [self.service_address_line1]
        if self.service_address_line2:
            parts.append(self.service_address_line2)
        parts.append(f'{self.service_city}, {self.service_state} {self.service_postal_code}')
        return '\n'.join(parts)
    
    def assign_driver(self, user_id, assigned_by_id=None, role='driver'):
        """
        Assign a driver to this job
        
        Args:
            user_id: UUID of user (driver) to assign
            assigned_by_id: UUID of user who made the assignment
            role: Role in job (driver, helper, lead)
        """
        from .job_assignment import JobAssignment
        
        assignment = JobAssignment(
            tenant_id=self.tenant_id,
            job_id=self.id,
            user_id=user_id,
            assigned_by=assigned_by_id,
            role_in_job=role
        )
        db.session.add(assignment)
        return assignment
    
    def to_dict(self, include_relationships=False):
        """Convert to dictionary with optional relationships"""
        data = super().to_dict()
        data['service_address'] = self.service_address
        
        if include_relationships:
            data['customer'] = self.customer.to_dict() if self.customer else None
            data['service'] = self.service.to_dict() if self.service else None
            data['assigned_drivers'] = [a.user.to_dict() for a in self.assignments.filter_by(status='assigned')]
        
        return data
