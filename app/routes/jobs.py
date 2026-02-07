from flask import Blueprint, request, jsonify
from app import db
from app.models import Job, JobAssignment, User
from app.utils import require_auth, require_role, serialize_model, paginate_query
from datetime import datetime

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('', methods=['GET'])
@require_auth
def list_jobs():
    """
    List jobs (with role-based filtering)
    GET /api/jobs?page=1&per_page=20&status=in_progress
    
    - Admins/dispatchers see all jobs
    - Drivers see only their assigned jobs
    """
    tenant_id = request.tenant_id
    user_id = request.user_id
    user_role = request.user_role
    
    # Build query with tenant isolation
    query = Job.query.filter_by(tenant_id=tenant_id, deleted_at=None)
    
    # Role-based filtering
    if user_role == 'driver':
        # Drivers only see assigned jobs
        query = query.join(JobAssignment).filter(
            JobAssignment.user_id == user_id,
            JobAssignment.status == 'assigned'
        )
    
    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter(Job.status == status)
    
    scheduled_date = request.args.get('scheduled_date')
    if scheduled_date:
        try:
            date_obj = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
            query = query.filter(Job.scheduled_date == date_obj)
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Order by scheduled date
    query = query.order_by(Job.scheduled_date.asc(), Job.scheduled_time_start.asc())
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    result = paginate_query(query, page, per_page)
    
    # Serialize items
    result['items'] = [serialize_model(job) for job in result['items']]
    
    return jsonify(result), 200


@jobs_bp.route('/<job_id>', methods=['PATCH'])
@require_auth
def update_job_status(job_id):
    """
    Update job status
    PATCH /api/jobs/:id
    Body: {
        "status": "in_progress",
        "actual_start_time": "2024-01-15T09:00:00Z",
        "actual_volume": 4.5
    }
    
    Allowed transitions:
    - pending -> confirmed, cancelled
    - confirmed -> assigned, cancelled
    - assigned -> in_progress, cancelled
    - in_progress -> completed
    """
    tenant_id = request.tenant_id
    user_id = request.user_id
    user_role = request.user_role
    data = request.get_json()
    
    # Find job
    job = Job.query.filter_by(
        id=job_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Drivers can only update jobs assigned to them
    if user_role == 'driver':
        assignment = JobAssignment.query.filter_by(
            job_id=job_id,
            user_id=user_id,
            status='assigned'
        ).first()
        
        if not assignment:
            return jsonify({'error': 'You are not assigned to this job'}), 403
    
    # Validate status transition
    valid_statuses = ['pending', 'confirmed', 'assigned', 'in_progress', 'completed', 'cancelled']
    if data.get('status') and data['status'] not in valid_statuses:
        return jsonify({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
    
    # Update fields
    if 'status' in data:
        job.status = data['status']
    
    if 'actual_start_time' in data:
        try:
            job.actual_start_time = datetime.fromisoformat(data['actual_start_time'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid datetime format'}), 400
    
    if 'actual_end_time' in data:
        try:
            job.actual_end_time = datetime.fromisoformat(data['actual_end_time'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid datetime format'}), 400
    
    if 'actual_volume' in data:
        job.actual_volume = data['actual_volume']
    
    if 'customer_rating' in data:
        job.customer_rating = data['customer_rating']
    
    if 'customer_feedback' in data:
        job.customer_feedback = data['customer_feedback']
    
    try:
        db.session.commit()
        
        return jsonify({
            'message': 'Job updated successfully',
            'job': serialize_model(job)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to update job', 'details': str(e)}), 500


@jobs_bp.route('/<job_id>/assign', methods=['POST'])
@require_auth
@require_role('admin', 'dispatcher')
def assign_job(job_id):
    """
    Assign job to driver(s)
    POST /api/jobs/:id/assign
    Body: {
        "driver_ids": ["uuid1", "uuid2"],
        "role_in_job": "driver"
    }
    """
    tenant_id = request.tenant_id
    user_id = request.user_id
    data = request.get_json()
    
    if not data.get('driver_ids') or not isinstance(data['driver_ids'], list):
        return jsonify({'error': 'driver_ids must be a non-empty array'}), 400
    
    # Find job
    job = Job.query.filter_by(
        id=job_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Verify all drivers exist and belong to tenant
    drivers = User.query.filter(
        User.id.in_(data['driver_ids']),
        User.tenant_id == tenant_id,
        User.role == 'driver',
        User.deleted_at == None
    ).all()
    
    if len(drivers) != len(data['driver_ids']):
        return jsonify({'error': 'One or more invalid driver IDs'}), 400
    
    try:
        # Create assignments
        for driver in drivers:
            assignment = JobAssignment(
                tenant_id=tenant_id,
                job_id=job_id,
                user_id=driver.id,
                assigned_by=user_id,
                role_in_job=data.get('role_in_job', 'driver'),
                status='assigned'
            )
            db.session.add(assignment)
        
        # Update job status
        if job.status == 'confirmed':
            job.status = 'assigned'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Job assigned successfully',
            'job': serialize_model(job)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to assign job', 'details': str(e)}), 500
