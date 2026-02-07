"""Activity Log model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET


class ActivityLog(BaseModel, TenantMixin):
    """
    Activity Log model - comprehensive audit trail
    """
    __tablename__ = 'activity_log'
    
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    
    entity_type = db.Column(db.String(100), nullable=False)
    entity_id = db.Column(UUID(as_uuid=True), nullable=False)
    
    action = db.Column(db.String(100), nullable=False)
    
    # Change tracking
    old_values = db.Column(JSONB)
    new_values = db.Column(JSONB)
    
    ip_address = db.Column(INET)
    user_agent = db.Column(db.Text)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_activity_log_user_id', 'user_id'),
        db.Index('idx_activity_log_entity', 'tenant_id', 'entity_type', 'entity_id'),
        db.Index('idx_activity_log_created_at', 'tenant_id', 'created_at'),
    )
    
    def __repr__(self):
        return f'<ActivityLog {self.entity_type}.{self.action}>'
    
    @classmethod
    def log_action(cls, tenant_id, entity_type, entity_id, action, user_id=None, 
                   old_values=None, new_values=None, ip_address=None, user_agent=None):
        """
        Log an action to the activity log
        
        Args:
            tenant_id: UUID of tenant
            entity_type: Type of entity (e.g., 'jobs', 'customers')
            entity_id: UUID of entity
            action: Action performed (e.g., 'created', 'updated', 'deleted')
            user_id: UUID of user who performed action
            old_values: Previous state (dict)
            new_values: New state (dict)
            ip_address: IP address of request
            user_agent: User agent string
        
        Returns:
            ActivityLog: Created log entry
        """
        log_entry = cls(
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log_entry)
        return log_entry
