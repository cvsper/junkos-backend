"""
Bookings blueprint
Handles customer bookings and job creation
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.job import Job
from app.models.customer import Customer
from app.models.service import Service
from app.middleware.tenant import tenant_required, get_current_tenant_id
from datetime import datetime, date
import uuid

bookings_bp = Blueprint('bookings', __name__)


def generate_job_number(tenant_id):
    """Generate unique job number"""
    year = datetime.now().year
    # Count jobs for this tenant this year
    count = Job.query.filter(
        Job.tenant_id == tenant_id,
        db.extract('year', Job.created_at) == year
    ).count() + 1
    
    return f'JOB-{year}-{count:04d}'


@bookings_bp.route('', methods=['POST'])
@tenant_required
@login_required
def create_booking():
    """
    Create a new booking
    
    POST /api/bookings
    Body: {
        "customer_id": "uuid" (optional, or provide customer details),
        "customer": {  (if customer_id not provided)
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "555-1234"
        },
        "service_id": "uuid",
        "scheduled_date": "2024-03-15",
        "scheduled_time_start": "09:00",
        "service_address_line1": "123 Main St",
        "service_city": "Boston",
        "service_state": "MA",
        "service_postal_code": "02101",
        "items_description": "Old furniture and appliances",
        "special_instructions": "Call upon arrival"
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    # Validate required fields
    required = ['service_id', 'scheduled_date', 'service_address_line1', 
                'service_city', 'service_state', 'service_postal_code']
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
    
    # Get or create customer
    customer_id = data.get('customer_id')
    
    if customer_id:
        customer = Customer.for_tenant(tenant_id).filter_by(id=customer_id).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
    else:
        # Create new customer
        customer_data = data.get('customer', {})
        if not customer_data.get('first_name') or not customer_data.get('phone'):
            return jsonify({'error': 'Customer first_name and phone required'}), 400
        
        customer = Customer(
            tenant_id=tenant_id,
            first_name=customer_data['first_name'],
            last_name=customer_data.get('last_name', ''),
            email=customer_data.get('email'),
            phone=customer_data['phone']
        )
        db.session.add(customer)
        db.session.flush()  # Get customer ID
    
    # Validate service
    service = Service.for_tenant(tenant_id).filter_by(
        id=data['service_id'],
        active=True
    ).first()
    
    if not service:
        return jsonify({'error': 'Service not found or inactive'}), 404
    
    # Parse date
    try:
        scheduled_date = datetime.strptime(data['scheduled_date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Create job
    job = Job(
        tenant_id=tenant_id,
        customer_id=customer.id,
        service_id=service.id,
        job_number=generate_job_number(tenant_id),
        scheduled_date=scheduled_date,
        scheduled_time_start=data.get('scheduled_time_start'),
        scheduled_time_end=data.get('scheduled_time_end'),
        status='pending',
        priority=data.get('priority', 'normal'),
        service_address_line1=data['service_address_line1'],
        service_address_line2=data.get('service_address_line2'),
        service_city=data['service_city'],
        service_state=data['service_state'],
        service_postal_code=data['service_postal_code'],
        service_country=data.get('service_country', 'US'),
        items_description=data.get('items_description'),
        special_instructions=data.get('special_instructions'),
        access_instructions=data.get('access_instructions'),
        estimated_volume=data.get('estimated_volume'),
        estimated_duration_minutes=service.estimated_duration_minutes
    )
    
    db.session.add(job)
    db.session.commit()
    
    return jsonify({
        'message': 'Booking created successfully',
        'job': job.to_dict(include_relationships=True)
    }), 201


@bookings_bp.route('', methods=['GET'])
@tenant_required
@login_required
def list_bookings():
    """
    List all bookings with filtering
    
    GET /api/bookings?status=pending&date_from=2024-03-01&date_to=2024-03-31&page=1&per_page=20
    """
    tenant_id = get_current_tenant_id()
    
    # Build query
    query = Job.for_tenant(tenant_id)
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter(Job.status == status)
    
    date_from = request.args.get('date_from')
    if date_from:
        query = query.filter(Job.scheduled_date >= date_from)
    
    date_to = request.args.get('date_to')
    if date_to:
        query = query.filter(Job.scheduled_date <= date_to)
    
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter(Job.customer_id == customer_id)
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pagination = query.order_by(Job.scheduled_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'bookings': [job.to_dict(include_relationships=True) for job in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200


@bookings_bp.route('/<booking_id>', methods=['GET'])
@tenant_required
@login_required
def get_booking(booking_id):
    """
    Get booking details
    
    GET /api/bookings/<booking_id>
    """
    tenant_id = get_current_tenant_id()
    
    job = Job.for_tenant(tenant_id).filter_by(id=booking_id).first()
    
    if not job:
        return jsonify({'error': 'Booking not found'}), 404
    
    return jsonify({
        'booking': job.to_dict(include_relationships=True)
    }), 200


@bookings_bp.route('/<booking_id>', methods=['PUT'])
@tenant_required
@login_required
def update_booking(booking_id):
    """
    Update booking details
    
    PUT /api/bookings/<booking_id>
    Body: {
        "scheduled_date": "2024-03-16",
        "special_instructions": "Updated instructions"
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    job = Job.for_tenant(tenant_id).filter_by(id=booking_id).first()
    
    if not job:
        return jsonify({'error': 'Booking not found'}), 404
    
    # Update allowed fields
    updatable_fields = [
        'scheduled_date', 'scheduled_time_start', 'scheduled_time_end',
        'service_address_line1', 'service_address_line2', 'service_city',
        'service_state', 'service_postal_code', 'items_description',
        'special_instructions', 'access_instructions', 'estimated_volume',
        'priority'
    ]
    
    for field in updatable_fields:
        if field in data:
            if field == 'scheduled_date':
                # Parse date
                try:
                    data[field] = datetime.strptime(data[field], '%Y-%m-%d').date()
                except ValueError:
                    return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
            setattr(job, field, data[field])
    
    db.session.commit()
    
    return jsonify({
        'message': 'Booking updated successfully',
        'booking': job.to_dict(include_relationships=True)
    }), 200


@bookings_bp.route('/<booking_id>/cancel', methods=['POST'])
@tenant_required
@login_required
def cancel_booking(booking_id):
    """
    Cancel a booking
    
    POST /api/bookings/<booking_id>/cancel
    Body: {
        "reason": "Customer requested cancellation"
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    job = Job.for_tenant(tenant_id).filter_by(id=booking_id).first()
    
    if not job:
        return jsonify({'error': 'Booking not found'}), 404
    
    if job.status == 'cancelled':
        return jsonify({'error': 'Booking already cancelled'}), 400
    
    if job.status == 'completed':
        return jsonify({'error': 'Cannot cancel completed booking'}), 400
    
    job.status = 'cancelled'
    if data.get('reason'):
        job.special_instructions = (job.special_instructions or '') + f"\n\nCancellation reason: {data['reason']}"
    
    db.session.commit()
    
    return jsonify({
        'message': 'Booking cancelled successfully',
        'booking': job.to_dict()
    }), 200
