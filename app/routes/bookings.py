from flask import Blueprint, request, jsonify
from app import db
from app.models import Job, Customer, Service
from app.utils import require_auth, serialize_model, paginate_query
from datetime import datetime, date

bookings_bp = Blueprint('bookings', __name__)


@bookings_bp.route('', methods=['GET'])
@require_auth
def list_bookings():
    """
    List all bookings for the tenant
    GET /api/bookings?page=1&per_page=20&status=pending&customer_id=uuid
    """
    tenant_id = request.tenant_id
    
    # Build query with tenant isolation
    query = Job.query.filter_by(tenant_id=tenant_id, deleted_at=None)
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    
    customer_id = request.args.get('customer_id')
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    scheduled_date = request.args.get('scheduled_date')
    if scheduled_date:
        try:
            date_obj = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
            query = query.filter_by(scheduled_date=date_obj)
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Order by scheduled date (newest first)
    query = query.order_by(Job.scheduled_date.desc(), Job.created_at.desc())
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    result = paginate_query(query, page, per_page)
    
    # Serialize items
    result['items'] = [serialize_model(job) for job in result['items']]
    
    return jsonify(result), 200


@bookings_bp.route('', methods=['POST'])
@require_auth
def create_booking():
    """
    Create a new booking
    POST /api/bookings
    Body: {
        "customer_id": "uuid",
        "service_id": "uuid",
        "scheduled_date": "2024-01-15",
        "scheduled_time_start": "09:00",
        "service_address_line1": "123 Main St",
        "service_city": "Boston",
        "service_state": "MA",
        "service_postal_code": "02101",
        "items_description": "Old furniture and appliances",
        "special_instructions": "Call before arriving",
        "estimated_volume": 3.5
    }
    """
    tenant_id = request.tenant_id
    data = request.get_json()
    
    # Validate required fields
    required_fields = [
        'customer_id', 'scheduled_date', 
        'service_address_line1', 'service_city', 
        'service_state', 'service_postal_code'
    ]
    
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Verify customer belongs to tenant
    customer = Customer.query.filter_by(
        id=data['customer_id'],
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not customer:
        return jsonify({'error': 'Invalid customer'}), 400
    
    # Verify service if provided
    if data.get('service_id'):
        service = Service.query.filter_by(
            id=data['service_id'],
            tenant_id=tenant_id,
            deleted_at=None
        ).first()
        
        if not service:
            return jsonify({'error': 'Invalid service'}), 400
    
    # Parse scheduled date
    try:
        scheduled_date = datetime.strptime(data['scheduled_date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Parse scheduled time if provided
    scheduled_time_start = None
    if data.get('scheduled_time_start'):
        try:
            scheduled_time_start = datetime.strptime(data['scheduled_time_start'], '%H:%M').time()
        except ValueError:
            return jsonify({'error': 'Invalid time format. Use HH:MM'}), 400
    
    # Generate job number (simple sequential for now)
    last_job = Job.query.filter_by(tenant_id=tenant_id).order_by(Job.created_at.desc()).first()
    job_number = f"JOB-{datetime.utcnow().year}-{(int(last_job.job_number.split('-')[-1]) + 1) if last_job else 1:04d}"
    
    # Create job
    job = Job(
        tenant_id=tenant_id,
        customer_id=data['customer_id'],
        service_id=data.get('service_id'),
        job_number=job_number,
        scheduled_date=scheduled_date,
        scheduled_time_start=scheduled_time_start,
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
        estimated_volume=data.get('estimated_volume')
    )
    
    try:
        db.session.add(job)
        db.session.commit()
        
        return jsonify({
            'message': 'Booking created successfully',
            'booking': serialize_model(job)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to create booking', 'details': str(e)}), 500


@bookings_bp.route('/<booking_id>', methods=['GET'])
@require_auth
def get_booking(booking_id):
    """Get a specific booking by ID"""
    tenant_id = request.tenant_id
    
    job = Job.query.filter_by(
        id=booking_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not job:
        return jsonify({'error': 'Booking not found'}), 404
    
    return jsonify(serialize_model(job)), 200
