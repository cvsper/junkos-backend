"""Notification model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID


class Notification(BaseModel, TenantMixin):
    """
    Notification model - in-app notifications for users
    """
    __tablename__ = 'notifications'
    
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    type = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    
    # Related entities
    related_entity_type = db.Column(db.String(100))
    related_entity_id = db.Column(UUID(as_uuid=True))
    
    # Delivery
    read_at = db.Column(db.DateTime(timezone=True))
    delivered_at = db.Column(db.DateTime(timezone=True))
    
    # Optional: Email/SMS tracking
    email_sent = db.Column(db.Boolean, default=False)
    sms_sent = db.Column(db.Boolean, default=False)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_notifications_user_id', 'user_id', 'created_at'),
        db.Index('idx_notifications_unread', 'user_id', 'read_at'),
    )
    
    def __repr__(self):
        return f'<Notification {self.type} - user={self.user_id}>'
    
    def mark_read(self):
        """Mark notification as read"""
        from datetime import datetime
        if not self.read_at:
            self.read_at = datetime.utcnow()
    
    @classmethod
    def create_notification(cls, tenant_id, user_id, notification_type, title, message,
                          related_entity_type=None, related_entity_id=None):
        """
        Create a new notification
        
        Args:
            tenant_id: UUID of tenant
            user_id: UUID of user to notify
            notification_type: Type of notification
            title: Notification title
            message: Notification message
            related_entity_type: Type of related entity (optional)
            related_entity_id: UUID of related entity (optional)
        
        Returns:
            Notification: Created notification
        """
        notification = cls(
            tenant_id=tenant_id,
            user_id=user_id,
            type=notification_type,
            title=title,
            message=message,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id
        )
        db.session.add(notification)
        return notification
