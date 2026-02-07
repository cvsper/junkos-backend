"""
Base model with common fields and methods
"""
from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid


class BaseModel(db.Model):
    """Abstract base model with common fields"""
    __abstract__ = True
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    def to_dict(self, exclude=None):
        """
        Convert model to dictionary
        
        Args:
            exclude (list): List of fields to exclude
            
        Returns:
            dict: Model as dictionary
        """
        exclude = exclude or []
        data = {}
        
        for column in self.__table__.columns:
            if column.name not in exclude:
                value = getattr(self, column.name)
                
                # Handle UUID
                if isinstance(value, uuid.UUID):
                    value = str(value)
                # Handle datetime
                elif isinstance(value, datetime):
                    value = value.isoformat()
                
                data[column.name] = value
        
        return data
    
    def soft_delete(self):
        """Soft delete by setting deleted_at timestamp"""
        self.deleted_at = datetime.utcnow()
        db.session.commit()
    
    def restore(self):
        """Restore soft-deleted record"""
        self.deleted_at = None
        db.session.commit()
    
    @classmethod
    def active(cls):
        """Query only non-deleted records"""
        return cls.query.filter(cls.deleted_at.is_(None))


class TenantMixin:
    """Mixin for multi-tenant models"""
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    
    @classmethod
    def for_tenant(cls, tenant_id):
        """
        Query records for specific tenant
        
        Args:
            tenant_id: UUID of tenant
            
        Returns:
            Query: Filtered query for tenant
        """
        return cls.query.filter(
            cls.tenant_id == tenant_id,
            cls.deleted_at.is_(None)
        )
