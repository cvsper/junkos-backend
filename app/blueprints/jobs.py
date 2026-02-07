"""
Jobs blueprint
Handles job management, status updates, and driver operations
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.job import Job
from app.models.activity_log import ActivityLog
from app.middleware.tenant import tenant_required, get_current_tenant_id
from datetime import datetime

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('', methods=['GET'])
@tenant_required
@login_required
def list_jobs():
    """
    List jobs with filtering
    
    GET /api/jobs?status=in_progress&assigned_to=<user_id>&date=2024-03-15
    """
    tenant_id = get_current_tenant_id()
    
    # Build query
    query = Job.for_tenant(tenant_id)
    
    # Role-based filtering
    if current_user.is_driver():
        # Drivers only see their assigned jobs
        query = query.join(Job.assignments).filter(
            Job.assignments.any(user_id=current_user.id, status='assigned')
        )
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter(Job.status == status)
    
    assigned_to = request.args.get('assigned_to')
    if assigned_to and (current_user.is_admin() or current_user.is_dispatcher()):
        query = query.join(Job.assignments).filter(
            Job.assignments.any(user_id=assigned_to)
        )
    
    scheduled_date = request.args.get('date')
    if scheduled_date:
        query = query.filter(Job.scheduled_date == scheduled_date)
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pagination = query.order_by(Job.scheduled_date.desc(), Job.scheduled_time_start).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'jobs': [job.to_dict(include_relationships=True) for job in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200


@jobs_bp.route('/<job_id>', methods=['GET'])
@tenant_required
@login_required
def get_job(job_id):
    """
    Get job details
    
    GET /api/jobs/<job_id>
    """
    tenant_id = get_current_tenant_id()
    
    job = Job.for_tenant(tenant_id).filter_by(id=job_id).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Drivers can only view their assigned jobs
    if current_user.is_driver():
        is_assigned = job.assignments.filter_by(user_id=current_user.id).first()
        if not is_assigned:
            return jsonify({'error': 'Access denied'}), 403
    
    return jsonify({
        'job': job.to_dict(include_relationships=True)
    }), 200


@jobs_bp.route('/<job_id>/status', methods=['PUT'])
@tenant_required
@login_required
def update_job_status(job_id):
    """
    Update job status
    
    PUT /api/jobs/<job_id>/status
    Body: {
        "status": "in_progress",
        "notes": "Started pickup"
    }
    
    Valid statuses: pending, confirmed, assigned, in_progress, completed, cancelled
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    new_status = data.get('status')
    if not new_status:
        return jsonify({'error': 'Status required'}), 400
    
    valid_statuses = ['pending', 'confirmed', 'assigned', 'in_progress', 'completed', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
    
    job = Job.for_tenant(tenant_id).filter_by(id=job_id).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Drivers can only update their assigned jobs
    if current_user.is_driver():
        is_assigned = job.assignments.filter_by(user_id=current_user.id, status='assigned').first()
        if not is_assigned:
            return jsonify({'error': 'Access denied'}), 403
    
    old_status = job.status
    job.status = new_status
    
    # Update timestamps based on status
    if new_status == 'in_progress' and not job.actual_start_time:
        job.actual_start_time = datetime.utcnow()
    elif new_status == 'completed' and not job.actual_end_time:
        job.actual_end_time = datetime.utcnow()
        # Update customer stats
        job.customer.total_jobs_completed += 1
    
    # Add notes if provided
    if data.get('notes'):
        job.special_instructions = (job.special_instructions or '') + f"\n\n[{datetime.utcnow()}] {data['notes']}"
    
    # Log activity
    ActivityLog.log_action(
        tenant_id=tenant_id,
        entity_type='jobs',
        entity_id=job.id,
        action='status_changed',
        user_id=current_user.id,
        old_values={'status': old_status},
        new_values={'status': new_status},
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )
    
    db.session.commit()
    
    return jsonify({
        'message': 'Job status updated successfully',
        'job': job.to_dict(include_relationships=True)
    }), 200


@jobs_bp.route('/<job_id>/volume', methods=['PUT'])
@tenant_required
@login_required
def update_job_volume(job_id):
    """
    Update actual volume (for volume-based pricing)
    
    PUT /api/jobs/<job_id>/volume
    Body: {
        "actual_volume": 3.5
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    actual_volume = data.get('actual_volume')
    if actual_volume is None:
        return jsonify({'error': 'actual_volume required'}), 400
    
    try:
        actual_volume = float(actual_volume)
        if actual_volume < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'actual_volume must be a positive number'}), 400
    
    job = Job.for_tenant(tenant_id).filter_by(id=job_id).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Drivers can update volume for their assigned jobs
    if current_user.is_driver():
        is_assigned = job.assignments.filter_by(user_id=current_user.id, status='assigned').first()
        if not is_assigned:
            return jsonify({'error': 'Access denied'}), 403
    
    job.actual_volume = actual_volume
    db.session.commit()
    
    return jsonify({
        'message': 'Job volume updated successfully',
        'job': job.to_dict()
    }), 200


@jobs_bp.route('/<job_id>/feedback', methods=['POST'])
@tenant_required
@login_required
def submit_feedback(job_id):
    """
    Submit customer feedback (admin/dispatcher can submit on behalf of customer)
    
    POST /api/jobs/<job_id>/feedback
    Body: {
        "rating": 5,
        "feedback": "Great service!"
    }
    """
    tenant_id = get_current_tenant_id()
    data = request.get_json()
    
    rating = data.get('rating')
    if not rating:
        return jsonify({'error': 'rating required'}), 400
    
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'rating must be between 1 and 5'}), 400
    
    job = Job.for_tenant(tenant_id).filter_by(id=job_id).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.status != 'completed':
        return jsonify({'error': 'Can only submit feedback for completed jobs'}), 400
    
    job.customer_rating = rating
    job.customer_feedback = data.get('feedback')
    
    # Update customer rating
    if job.customer:
        customer = job.customer
        all_ratings = [j.customer_rating for j in customer.jobs if j.customer_rating]
        if all_ratings:
            customer.rating = sum(all_ratings) / len(all_ratings)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Feedback submitted successfully',
        'job': job.to_dict()
    }), 200


@jobs_bp.route('/today', methods=['GET'])
@tenant_required
@login_required
def get_today_jobs():
    """
    Get today's jobs for current user (for drivers)
    
    GET /api/jobs/today
    """
    tenant_id = get_current_tenant_id()
    today = datetime.now().date()
    
    query = Job.for_tenant(tenant_id).filter(Job.scheduled_date == today)
    
    if current_user.is_driver():
        # Only show assigned jobs
        query = query.join(Job.assignments).filter(
            Job.assignments.any(user_id=current_user.id, status='assigned')
        )
    
    jobs = query.order_by(Job.scheduled_time_start).all()
    
    return jsonify({
        'jobs': [job.to_dict(include_relationships=True) for job in jobs],
        'date': str(today),
        'total': len(jobs)
    }), 200
