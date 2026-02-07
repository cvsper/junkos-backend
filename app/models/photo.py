"""Photo model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID


class Photo(BaseModel, TenantMixin):
    """
    Photo model - before/after photos for jobs
    """
    __tablename__ = 'photos'
    
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    uploaded_by = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    
    photo_type = db.Column(db.String(50), nullable=False)  # before, after, during, damage, signature
    
    # File storage
    file_path = db.Column(db.String(500), nullable=False)
    file_url = db.Column(db.String(500), nullable=False)
    thumbnail_url = db.Column(db.String(500))
    file_size_bytes = db.Column(db.BigInteger)
    mime_type = db.Column(db.String(100))
    
    # Image metadata
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    
    # Geolocation & timestamp
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    taken_at = db.Column(db.DateTime(timezone=True))
    
    caption = db.Column(db.Text)
    display_order = db.Column(db.Integer, default=0)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_photos_job_id', 'job_id'),
        db.Index('idx_photos_type', 'tenant_id', 'photo_type'),
        db.Index('idx_photos_uploaded_by', 'uploaded_by'),
    )
    
    def __repr__(self):
        return f'<Photo {self.photo_type} - job={self.job_id}>'
