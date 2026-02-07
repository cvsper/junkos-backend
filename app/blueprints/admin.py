"""
Admin blueprint
Administrative functions for tenant management, users, and settings
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.customer import Customer
from app.models.service import Service
from app.models.tenant_settings import TenantSettings
from app.middleware.tenant import tenant_required, get_current_tenant_id

admin_bp = Blueprint('admin', __name__)


def require_admin(f):
    """Decorator to require admin role"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            return jsonify({'error': 'Access denied. Admin role required'}), 403
        return f(*args, **kwargs)
    
    return decorated_function


@admin_bp.route('/users', methods=['GET'])
@tenant_required
@login_required
@require_admin
def list_users():
    """
    List all users in tenant
    
    GET /api/admin/users?role=driver&status=active
    """
    tenant_id = get_current_tenant_id()
    
    query = User.for_tenant(tenant_id)
    
    # Apply filters
    role = request.args.get('role')
    if role:
        query = query.filter(User.role == role)
    
    status = request.args.get('status')
    if status:
        query = query.filter(User.status == status)
    
    users = query.all()
    
    return jsonify({
        'users': [user.to_dict() for user in users],
        'total': len(users)
    }), 200


@admin_bp.route('/users/<user_id>', methods=['PUT'])
@tenant_required
@login_required
@require_admin
def update_user(user_id):
    """
    Update user details
    
    PUT /api/admin/users/<user_id>
    Body: {
        "status": "inactive",
        "role": "dispatcher"
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    user = User.for_tenant(tenant_id).filter_by(id=user_id).first()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Update allowed fields
    if 'status' in data:
        valid_statuses = ['active', 'inactive', 'suspended']
        if data['status'] in valid_statuses:
            user.status = data['status']
    
    if 'role' in data:
        valid_roles = ['admin', 'dispatcher', 'driver']
        if data['role'] in valid_roles:
            user.role = data['role']
    
    if 'first_name' in data:
        user.first_name = data['first_name']
    
    if 'last_name' in data:
        user.last_name = data['last_name']
    
    if 'phone' in data:
        user.phone = data['phone']
    
    db.session.commit()
    
    return jsonify({
        'message': 'User updated successfully',
        'user': user.to_dict()
    }), 200


@admin_bp.route('/users/<user_id>', methods=['DELETE'])
@tenant_required
@login_required
@require_admin
def delete_user(user_id):
    """
    Soft delete a user
    
    DELETE /api/admin/users/<user_id>
    """
    tenant_id = get_current_tenant_id()
    
    user = User.for_tenant(tenant_id).filter_by(id=user_id).first()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    
    user.soft_delete()
    
    return jsonify({
        'message': 'User deleted successfully'
    }), 200


@admin_bp.route('/customers', methods=['GET'])
@tenant_required
@login_required
@require_admin
def list_customers():
    """
    List all customers
    
    GET /api/admin/customers?search=john
    """
    tenant_id = get_current_tenant_id()
    
    query = Customer.for_tenant(tenant_id)
    
    # Search
    search = request.args.get('search')
    if search:
        query = query.filter(
            db.or_(
                Customer.first_name.ilike(f'%{search}%'),
                Customer.last_name.ilike(f'%{search}%'),
                Customer.email.ilike(f'%{search}%'),
                Customer.phone.ilike(f'%{search}%')
            )
        )
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pagination = query.order_by(Customer.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'customers': [customer.to_dict() for customer in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200


@admin_bp.route('/services', methods=['POST'])
@tenant_required
@login_required
@require_admin
def create_service():
    """
    Create a new service
    
    POST /api/admin/services
    Body: {
        "name": "Full Truck Load",
        "description": "Complete truck load of junk",
        "pricing_type": "fixed",
        "base_price": 500.00,
        "estimated_duration_minutes": 120
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    required = ['name', 'pricing_type']
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
    
    valid_pricing_types = ['fixed', 'volume_based', 'hourly', 'custom']
    if data['pricing_type'] not in valid_pricing_types:
        return jsonify({'error': f'Invalid pricing_type. Must be one of: {", ".join(valid_pricing_types)}'}), 400
    
    service = Service(
        tenant_id=tenant_id,
        name=data['name'],
        description=data.get('description'),
        pricing_type=data['pricing_type'],
        base_price=data.get('base_price'),
        price_per_unit=data.get('price_per_unit'),
        unit_type=data.get('unit_type'),
        estimated_duration_minutes=data.get('estimated_duration_minutes'),
        requires_dump_fee=data.get('requires_dump_fee', False),
        active=data.get('active', True)
    )
    
    db.session.add(service)
    db.session.commit()
    
    return jsonify({
        'message': 'Service created successfully',
        'service': service.to_dict()
    }), 201


@admin_bp.route('/services', methods=['GET'])
@tenant_required
@login_required
def list_services():
    """
    List all services
    
    GET /api/admin/services?active=true
    """
    tenant_id = get_current_tenant_id()
    
    query = Service.for_tenant(tenant_id)
    
    active_filter = request.args.get('active')
    if active_filter is not None:
        active = active_filter.lower() in ['true', '1', 'yes']
        query = query.filter(Service.active == active)
    
    services = query.all()
    
    return jsonify({
        'services': [service.to_dict() for service in services],
        'total': len(services)
    }), 200


@admin_bp.route('/services/<service_id>', methods=['PUT'])
@tenant_required
@login_required
@require_admin
def update_service(service_id):
    """
    Update service
    
    PUT /api/admin/services/<service_id>
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    service = Service.for_tenant(tenant_id).filter_by(id=service_id).first()
    
    if not service:
        return jsonify({'error': 'Service not found'}), 404
    
    # Update fields
    updatable = ['name', 'description', 'base_price', 'price_per_unit', 
                 'unit_type', 'estimated_duration_minutes', 'requires_dump_fee', 'active']
    
    for field in updatable:
        if field in data:
            setattr(service, field, data[field])
    
    db.session.commit()
    
    return jsonify({
        'message': 'Service updated successfully',
        'service': service.to_dict()
    }), 200


@admin_bp.route('/settings', methods=['GET'])
@tenant_required
@login_required
@require_admin
def get_settings():
    """
    Get tenant settings
    
    GET /api/admin/settings
    """
    tenant_id = get_current_tenant_id()
    
    settings = TenantSettings.for_tenant(tenant_id).first()
    
    if not settings:
        # Create default settings
        settings = TenantSettings(tenant_id=tenant_id)
        db.session.add(settings)
        db.session.commit()
    
    return jsonify({
        'settings': settings.to_dict()
    }), 200


@admin_bp.route('/settings', methods=['PUT'])
@tenant_required
@login_required
@require_admin
def update_settings():
    """
    Update tenant settings
    
    PUT /api/admin/settings
    Body: {
        "service_area_radius_miles": 75,
        "default_tax_rate": 0.0625,
        "email_notifications_enabled": true
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    settings = TenantSettings.for_tenant(tenant_id).first()
    
    if not settings:
        settings = TenantSettings(tenant_id=tenant_id)
        db.session.add(settings)
    
    # Update fields
    updatable = [
        'service_area_radius_miles', 'auto_accept_bookings',
        'require_customer_signature', 'default_tax_rate', 'default_dump_fee',
        'email_notifications_enabled', 'sms_notifications_enabled',
        'business_hours'
    ]
    
    for field in updatable:
        if field in data:
            setattr(settings, field, data[field])
    
    db.session.commit()
    
    return jsonify({
        'message': 'Settings updated successfully',
        'settings': settings.to_dict()
    }), 200


@admin_bp.route('/stats', methods=['GET'])
@tenant_required
@login_required
@require_admin
def get_stats():
    """
    Get tenant statistics
    
    GET /api/admin/stats
    """
    tenant_id = get_current_tenant_id()
    
    from app.models.job import Job
    from app.models.invoice import Invoice
    from sqlalchemy import func
    
    # Job stats
    total_jobs = Job.for_tenant(tenant_id).count()
    pending_jobs = Job.for_tenant(tenant_id).filter(Job.status == 'pending').count()
    completed_jobs = Job.for_tenant(tenant_id).filter(Job.status == 'completed').count()
    
    # Customer stats
    total_customers = Customer.for_tenant(tenant_id).count()
    
    # Revenue stats
    total_revenue = db.session.query(func.sum(Invoice.total_amount)).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.status == 'paid',
        Invoice.deleted_at.is_(None)
    ).scalar() or 0
    
    outstanding_invoices = db.session.query(func.sum(Invoice.amount_due)).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(['sent', 'overdue']),
        Invoice.deleted_at.is_(None)
    ).scalar() or 0
    
    # User stats
    total_drivers = User.for_tenant(tenant_id).filter(User.role == 'driver').count()
    active_drivers = User.for_tenant(tenant_id).filter(
        User.role == 'driver',
        User.status == 'active'
    ).count()
    
    return jsonify({
        'stats': {
            'jobs': {
                'total': total_jobs,
                'pending': pending_jobs,
                'completed': completed_jobs
            },
            'customers': {
                'total': total_customers
            },
            'revenue': {
                'total': float(total_revenue),
                'outstanding': float(outstanding_invoices)
            },
            'drivers': {
                'total': total_drivers,
                'active': active_drivers
            }
        }
    }), 200
