"""
Dispatch blueprint
Handles job assignments, scheduling, and route optimization
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.job import Job
from app.models.job_assignment import JobAssignment
from app.models.user import User
from app.models.route import Route
from app.models.notification import Notification
from app.middleware.tenant import tenant_required, get_current_tenant_id
from datetime import datetime

dispatch_bp = Blueprint('dispatch', __name__)


def require_dispatcher_or_admin(f):
    """Decorator to require dispatcher or admin role"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not (current_user.is_admin() or current_user.is_dispatcher()):
            return jsonify({'error': 'Access denied. Dispatcher or admin role required'}), 403
        return f(*args, **kwargs)
    
    return decorated_function


@dispatch_bp.route('/assign', methods=['POST'])
@tenant_required
@login_required
@require_dispatcher_or_admin
def assign_job():
    """
    Assign job to driver(s)
    
    POST /api/dispatch/assign
    Body: {
        "job_id": "uuid",
        "driver_ids": ["uuid1", "uuid2"],
        "role": "driver"  (optional, default: driver; options: driver, helper, lead)
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    job_id = data.get('job_id')
    driver_ids = data.get('driver_ids', [])
    role = data.get('role', 'driver')
    
    if not job_id or not driver_ids:
        return jsonify({'error': 'job_id and driver_ids required'}), 400
    
    # Validate job
    job = Job.for_tenant(tenant_id).filter_by(id=job_id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Validate drivers
    drivers = User.for_tenant(tenant_id).filter(
        User.id.in_(driver_ids),
        User.role == 'driver',
        User.status == 'active'
    ).all()
    
    if len(drivers) != len(driver_ids):
        return jsonify({'error': 'One or more drivers not found or inactive'}), 404
    
    # Create assignments
    assignments = []
    for driver in drivers:
        # Check if already assigned
        existing = JobAssignment.query.filter_by(
            job_id=job.id,
            user_id=driver.id
        ).first()
        
        if existing:
            continue  # Skip if already assigned
        
        assignment = JobAssignment(
            tenant_id=tenant_id,
            job_id=job.id,
            user_id=driver.id,
            assigned_by=current_user.id,
            role_in_job=role,
            assigned_at=datetime.utcnow()
        )
        db.session.add(assignment)
        assignments.append(assignment)
        
        # Create notification for driver
        Notification.create_notification(
            tenant_id=tenant_id,
            user_id=driver.id,
            notification_type='job_assigned',
            title='New Job Assigned',
            message=f'You have been assigned to job {job.job_number}',
            related_entity_type='jobs',
            related_entity_id=job.id
        )
    
    # Update job status
    if job.status == 'pending':
        job.status = 'assigned'
    
    db.session.commit()
    
    return jsonify({
        'message': f'Job assigned to {len(assignments)} driver(s)',
        'job': job.to_dict(include_relationships=True),
        'assignments': len(assignments)
    }), 200


@dispatch_bp.route('/unassign', methods=['POST'])
@tenant_required
@login_required
@require_dispatcher_or_admin
def unassign_job():
    """
    Remove driver assignment from job
    
    POST /api/dispatch/unassign
    Body: {
        "job_id": "uuid",
        "driver_id": "uuid"
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    job_id = data.get('job_id')
    driver_id = data.get('driver_id')
    
    if not job_id or not driver_id:
        return jsonify({'error': 'job_id and driver_id required'}), 400
    
    assignment = JobAssignment.query.filter_by(
        tenant_id=tenant_id,
        job_id=job_id,
        user_id=driver_id
    ).first()
    
    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404
    
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({
        'message': 'Driver unassigned successfully'
    }), 200


@dispatch_bp.route('/drivers', methods=['GET'])
@tenant_required
@login_required
@require_dispatcher_or_admin
def list_drivers():
    """
    List available drivers
    
    GET /api/dispatch/drivers?status=active&date=2024-03-15
    """
    tenant_id = get_current_tenant_id()
    
    query = User.for_tenant(tenant_id).filter(User.role == 'driver')
    
    status = request.args.get('status')
    if status:
        query = query.filter(User.status == status)
    else:
        query = query.filter(User.status == 'active')
    
    drivers = query.all()
    
    # If date provided, include workload for that date
    check_date = request.args.get('date')
    driver_data = []
    
    for driver in drivers:
        data = driver.to_dict()
        
        if check_date:
            # Count assigned jobs for date
            job_count = Job.query.join(Job.assignments).filter(
                Job.tenant_id == tenant_id,
                Job.scheduled_date == check_date,
                JobAssignment.user_id == driver.id,
                JobAssignment.status == 'assigned'
            ).count()
            
            data['jobs_on_date'] = job_count
        
        driver_data.append(data)
    
    return jsonify({
        'drivers': driver_data,
        'total': len(drivers)
    }), 200


@dispatch_bp.route('/schedule', methods=['GET'])
@tenant_required
@login_required
@require_dispatcher_or_admin
def get_schedule():
    """
    Get dispatch schedule for a date range
    
    GET /api/dispatch/schedule?date_from=2024-03-15&date_to=2024-03-17
    """
    tenant_id = get_current_tenant_id()
    
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    if not date_from:
        date_from = datetime.now().date()
    
    query = Job.for_tenant(tenant_id).filter(
        Job.scheduled_date >= date_from,
        Job.status.notin_(['cancelled', 'completed'])
    )
    
    if date_to:
        query = query.filter(Job.scheduled_date <= date_to)
    
    jobs = query.order_by(Job.scheduled_date, Job.scheduled_time_start).all()
    
    # Group by date
    schedule = {}
    for job in jobs:
        date_key = str(job.scheduled_date)
        if date_key not in schedule:
            schedule[date_key] = []
        
        job_data = job.to_dict(include_relationships=True)
        schedule[date_key].append(job_data)
    
    return jsonify({
        'schedule': schedule,
        'total_jobs': len(jobs)
    }), 200


@dispatch_bp.route('/routes', methods=['POST'])
@tenant_required
@login_required
@require_dispatcher_or_admin
def create_route():
    """
    Create an optimized route for a driver
    
    POST /api/dispatch/routes
    Body: {
        "driver_id": "uuid",
        "route_date": "2024-03-15",
        "route_name": "North Zone - Morning",
        "job_ids": ["uuid1", "uuid2", "uuid3"]
    }
    """
    data = request.get_json()
    tenant_id = get_current_tenant_id()
    
    driver_id = data.get('driver_id')
    route_date = data.get('route_date')
    job_ids = data.get('job_ids', [])
    
    if not driver_id or not route_date or not job_ids:
        return jsonify({'error': 'driver_id, route_date, and job_ids required'}), 400
    
    # Validate driver
    driver = User.for_tenant(tenant_id).filter_by(
        id=driver_id,
        role='driver',
        status='active'
    ).first()
    
    if not driver:
        return jsonify({'error': 'Driver not found or inactive'}), 404
    
    # Parse date
    try:
        route_date = datetime.strptime(route_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Create route
    route = Route(
        tenant_id=tenant_id,
        user_id=driver.id,
        route_date=route_date,
        route_name=data.get('route_name'),
        optimized_order=job_ids,
        status='planned'
    )
    
    db.session.add(route)
    db.session.commit()
    
    return jsonify({
        'message': 'Route created successfully',
        'route': route.to_dict()
    }), 201


@dispatch_bp.route('/routes/<route_id>', methods=['GET'])
@tenant_required
@login_required
def get_route(route_id):
    """
    Get route details
    
    GET /api/dispatch/routes/<route_id>
    """
    tenant_id = get_current_tenant_id()
    
    route = Route.for_tenant(tenant_id).filter_by(id=route_id).first()
    
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    
    # Drivers can only view their own routes
    if current_user.is_driver() and route.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    
    return jsonify({
        'route': route.to_dict()
    }), 200
