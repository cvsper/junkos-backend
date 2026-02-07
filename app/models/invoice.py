"""Invoice models"""
from app import db
from .base import BaseModel, TenantMixin
from sqlalchemy.dialects.postgresql import UUID


class Invoice(BaseModel, TenantMixin):
    """
    Invoice model - bills sent to customers
    """
    __tablename__ = 'invoices'
    
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey('jobs.id', ondelete='RESTRICT'))
    
    invoice_number = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='draft')
    
    # Amounts
    subtotal = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    tax_amount = db.Column(db.Numeric(10, 2), default=0.00)
    dump_fee = db.Column(db.Numeric(10, 2), default=0.00)
    discount_amount = db.Column(db.Numeric(10, 2), default=0.00)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), default=0.00)
    amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Dates
    invoice_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True))
    
    # Notes
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'invoice_number', name='unique_invoice_number_per_tenant'),
        db.Index('idx_invoices_customer_id', 'tenant_id', 'customer_id'),
        db.Index('idx_invoices_status', 'tenant_id', 'status'),
        db.Index('idx_invoices_due_date', 'tenant_id', 'due_date'),
    )
    
    # Relationships
    line_items = db.relationship('InvoiceLineItem', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='invoice', lazy='dynamic')
    
    def __repr__(self):
        return f'<Invoice {self.invoice_number} - ${self.total_amount}>'
    
    def add_line_item(self, description, quantity, unit_price):
        """Add a line item to the invoice"""
        line_item = InvoiceLineItem(
            tenant_id=self.tenant_id,
            invoice_id=self.id,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            total_price=quantity * unit_price,
            line_order=self.line_items.count()
        )
        db.session.add(line_item)
        return line_item
    
    def recalculate_totals(self):
        """Recalculate invoice totals based on line items"""
        self.subtotal = sum(item.total_price for item in self.line_items)
        self.total_amount = self.subtotal + self.tax_amount + self.dump_fee - self.discount_amount
        self.amount_due = self.total_amount - self.amount_paid
    
    def mark_paid(self):
        """Mark invoice as paid"""
        from datetime import datetime
        self.status = 'paid'
        self.paid_at = datetime.utcnow()
        self.amount_paid = self.total_amount
        self.amount_due = 0


class InvoiceLineItem(db.Model):
    """
    Invoice Line Item model - itemized charges on invoices
    """
    __tablename__ = 'invoice_line_items'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    invoice_id = db.Column(UUID(as_uuid=True), db.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False)
    
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    
    line_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True))
    
    # Indexes
    __table_args__ = (
        db.Index('idx_invoice_line_items_invoice_id', 'invoice_id'),
    )
    
    def __repr__(self):
        return f'<InvoiceLineItem {self.description} - ${self.total_price}>'
