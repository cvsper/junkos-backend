"""Payment model"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID, JSONB


class Payment(BaseModel, TenantMixin):
    """
    Payment model - payment transactions linked to invoices
    """
    __tablename__ = 'payments'
    
    invoice_id = db.Column(UUID(as_uuid=True), db.ForeignKey('invoices.id', ondelete='RESTRICT'), nullable=False)
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    
    payment_method = db.Column(db.String(50), nullable=False)  # cash, check, credit_card, stripe, etc.
    payment_status = db.Column(db.String(50), nullable=False, default='pending')
    
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Payment processor details
    transaction_id = db.Column(db.String(255))
    processor = db.Column(db.String(50))
    processor_response = db.Column(JSONB)
    
    # Payment details
    payment_date = db.Column(db.DateTime(timezone=True))
    reference_number = db.Column(db.String(100))
    
    notes = db.Column(db.Text)
    
    # Refunds
    refunded_at = db.Column(db.DateTime(timezone=True))
    refund_amount = db.Column(db.Numeric(10, 2))
    refund_reason = db.Column(db.Text)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_payments_invoice_id', 'invoice_id'),
        db.Index('idx_payments_customer_id', 'customer_id'),
        db.Index('idx_payments_status', 'tenant_id', 'payment_status'),
        db.Index('idx_payments_date', 'tenant_id', 'payment_date'),
    )
    
    def __repr__(self):
        return f'<Payment {self.payment_method} - ${self.amount}>'
    
    def process_payment(self):
        """Mark payment as completed"""
        from datetime import datetime
        self.payment_status = 'completed'
        if not self.payment_date:
            self.payment_date = datetime.utcnow()
        
        # Update invoice
        self.invoice.amount_paid += self.amount
        self.invoice.amount_due -= self.amount
        
        if self.invoice.amount_due <= 0:
            self.invoice.mark_paid()
    
    def refund(self, amount=None, reason=None):
        """Process refund"""
        from datetime import datetime
        refund_amount = amount or self.amount
        
        self.payment_status = 'refunded'
        self.refunded_at = datetime.utcnow()
        self.refund_amount = refund_amount
        self.refund_reason = reason
        
        # Update invoice
        self.invoice.amount_paid -= refund_amount
        self.invoice.amount_due += refund_amount
        self.invoice.status = 'sent'  # Reopen invoice
