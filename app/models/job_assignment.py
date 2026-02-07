"""Job Assignment model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID


class JobAssignment(BaseModel, TenantMixin):
    """
    Job Assignment model - links jobs to drivers
    Supports multiple drivers per job (teams)
    """
    __tablename__ = 'job_assignments'
    
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    assigned_by = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    
    role_in_job = db.Column(db.String(50), default='driver')  # driver, helper, lead
    status = db.Column(db.String(50), default='assigned')  # assigned, accepted, rejected, completed
    
    assigned_at = db.Column(db.DateTime(timezone=True))
    accepted_at = db.Column(db.DateTime(timezone=True))
    rejected_at = db.Column(db.DateTime(timezone=True))
    rejection_reason = db.Column(db.Text)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_job_assignments_job_id', 'job_id'),
        db.Index('idx_job_assignments_user_id', 'tenant_id', 'user_id'),
        db.Index('idx_job_assignments_status', 'tenant_id', 'status'),
    )
    
    def __repr__(self):
        return f'<JobAssignment job={self.job_id} user={self.user_id} status={self.status}>'
    
    def accept(self):
        """Accept the assignment"""
        from datetime import datetime
        self.status = 'accepted'
        self.accepted_at = datetime.utcnow()
    
    def reject(self, reason=None):
        """Reject the assignment"""
        from datetime import datetime
        self.status = 'rejected'
        self.rejected_at = datetime.utcnow()
        self.rejection_reason = reason
    
    def complete(self):
        """Mark assignment as completed"""
        self.status = 'completed'
