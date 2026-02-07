from datetime import datetime
from app import db
import uuid


def generate_uuid():
    """Generate UUID for primary keys"""
    return str(uuid.uuid4())


class Tenant(db.Model):
    """Multi-tenant organization model"""
    __tablename__ = 'tenants'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='active')
    subscription_tier = db.Column(db.String(50), nullable=False, default='basic')
    contact_email = db.Column(db.String(255), nullable=False)
    contact_phone = db.Column(db.String(50))
    branding_config = db.Column(db.JSON)
    billing_address = db.Column(db.Text)
    billing_email = db.Column(db.String(255))
    trial_ends_at = db.Column(db.DateTime(timezone=True))
    subscription_started_at = db.Column(db.DateTime(timezone=True))
    subscription_cancelled_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))


class User(db.Model):
    """User model with role-based access"""
    __tablename__ = 'users'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    role = db.Column(db.String(50), nullable=False)  # admin, dispatcher, driver
    status = db.Column(db.String(50), nullable=False, default='active')
    driver_license_number = db.Column(db.String(100))
    driver_license_expiry = db.Column(db.Date)
    vehicle_info = db.Column(db.JSON)
    email_verified_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    password_changed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    tenant = db.relationship('Tenant', backref='users')
    
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'email', name='unique_email_per_tenant'),
    )


class Customer(db.Model):
    """Customer model"""
    __tablename__ = 'customers'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50), nullable=False)
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(2), default='US')
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    notes = db.Column(db.Text)
    rating = db.Column(db.Numeric(3, 2))
    total_jobs_completed = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Numeric(10, 2), default=0.00)
    marketing_opt_in = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    tenant = db.relationship('Tenant', backref='customers')


class Service(db.Model):
    """Service catalog model"""
    __tablename__ = 'services'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    pricing_type = db.Column(db.String(50), nullable=False)
    base_price = db.Column(db.Numeric(10, 2))
    price_per_unit = db.Column(db.Numeric(10, 2))
    unit_type = db.Column(db.String(50))
    estimated_duration_minutes = db.Column(db.Integer)
    requires_dump_fee = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    tenant = db.relationship('Tenant', backref='services')


class Job(db.Model):
    """Job/booking model"""
    __tablename__ = 'jobs'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    service_id = db.Column(db.String(36), db.ForeignKey('services.id', ondelete='RESTRICT'))
    job_number = db.Column(db.String(50), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time_start = db.Column(db.Time)
    scheduled_time_end = db.Column(db.Time)
    estimated_duration_minutes = db.Column(db.Integer)
    status = db.Column(db.String(50), nullable=False, default='pending')
    priority = db.Column(db.String(50), default='normal')
    service_address_line1 = db.Column(db.String(255), nullable=False)
    service_address_line2 = db.Column(db.String(255))
    service_city = db.Column(db.String(100), nullable=False)
    service_state = db.Column(db.String(50), nullable=False)
    service_postal_code = db.Column(db.String(20), nullable=False)
    service_country = db.Column(db.String(2), default='US')
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    items_description = db.Column(db.Text)
    special_instructions = db.Column(db.Text)
    access_instructions = db.Column(db.Text)
    estimated_volume = db.Column(db.Numeric(10, 2))
    actual_volume = db.Column(db.Numeric(10, 2))
    actual_start_time = db.Column(db.DateTime(timezone=True))
    actual_end_time = db.Column(db.DateTime(timezone=True))
    customer_rating = db.Column(db.Integer)
    customer_feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    tenant = db.relationship('Tenant', backref='jobs')
    customer = db.relationship('Customer', backref='jobs')
    service = db.relationship('Service', backref='jobs')
    
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'job_number', name='unique_job_number_per_tenant'),
    )


class JobAssignment(db.Model):
    """Job assignment to drivers"""
    __tablename__ = 'job_assignments'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    assigned_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    role_in_job = db.Column(db.String(50), default='driver')
    status = db.Column(db.String(50), default='assigned')
    assigned_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime(timezone=True))
    rejected_at = db.Column(db.DateTime(timezone=True))
    rejection_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant', backref='job_assignments')
    job = db.relationship('Job', backref='assignments')
    driver = db.relationship('User', foreign_keys=[user_id], backref='assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by])


class Invoice(db.Model):
    """Invoice model"""
    __tablename__ = 'invoices'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id', ondelete='RESTRICT'))
    invoice_number = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='draft')
    subtotal = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    tax_amount = db.Column(db.Numeric(10, 2), default=0.00)
    dump_fee = db.Column(db.Numeric(10, 2), default=0.00)
    discount_amount = db.Column(db.Numeric(10, 2), default=0.00)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), default=0.00)
    amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime(timezone=True))
    
    # Relationships
    tenant = db.relationship('Tenant', backref='invoices')
    customer = db.relationship('Customer', backref='invoices')
    job = db.relationship('Job', backref='invoices')
    
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'invoice_number', name='unique_invoice_number_per_tenant'),
    )


class Payment(db.Model):
    """Payment model"""
    __tablename__ = 'payments'
    
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    invoice_id = db.Column(db.String(36), db.ForeignKey('invoices.id', ondelete='RESTRICT'), nullable=False)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    payment_status = db.Column(db.String(50), nullable=False, default='pending')
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    transaction_id = db.Column(db.String(255))
    processor = db.Column(db.String(50))
    processor_response = db.Column(db.JSON)
    payment_date = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    reference_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    refunded_at = db.Column(db.DateTime(timezone=True))
    refund_amount = db.Column(db.Numeric(10, 2))
    refund_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant', backref='payments')
    invoice = db.relationship('Invoice', backref='payments')
    customer = db.relationship('Customer', backref='payments')
