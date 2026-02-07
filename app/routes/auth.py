from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Tenant
from app.utils import hash_password, verify_password, generate_token, serialize_model
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new user
    POST /api/auth/register
    Body: {
        "tenant_id": "uuid",
        "email": "user@example.com",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "role": "admin",
        "phone": "555-1234"
    }
    """
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['tenant_id', 'email', 'password', 'first_name', 'last_name', 'role']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Check if tenant exists
    tenant = Tenant.query.filter_by(id=data['tenant_id'], deleted_at=None).first()
    if not tenant:
        return jsonify({'error': 'Invalid tenant'}), 400
    
    # Check if user already exists
    existing_user = User.query.filter_by(
        tenant_id=data['tenant_id'],
        email=data['email'],
        deleted_at=None
    ).first()
    
    if existing_user:
        return jsonify({'error': 'User with this email already exists'}), 400
    
    # Validate role
    valid_roles = ['admin', 'dispatcher', 'driver']
    if data['role'] not in valid_roles:
        return jsonify({'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400
    
    # Create new user
    user = User(
        tenant_id=data['tenant_id'],
        email=data['email'].lower().strip(),
        password_hash=hash_password(data['password']),
        first_name=data['first_name'],
        last_name=data['last_name'],
        phone=data.get('phone'),
        role=data['role'],
        status='active'
    )
    
    try:
        db.session.add(user)
        db.session.commit()
        
        # Generate token
        token = generate_token(user.id, user.tenant_id, user.role)
        
        return jsonify({
            'message': 'User registered successfully',
            'token': token,
            'user': serialize_model(user)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to create user', 'details': str(e)}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login user
    POST /api/auth/login
    Body: {
        "email": "user@example.com",
        "password": "password123",
        "tenant_id": "uuid"  # Optional if email is unique
    }
    """
    data = request.get_json()
    
    if not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password are required'}), 400
    
    # Build query
    query = User.query.filter_by(
        email=data['email'].lower().strip(),
        deleted_at=None
    )
    
    # If tenant_id provided, filter by it
    if data.get('tenant_id'):
        query = query.filter_by(tenant_id=data['tenant_id'])
    
    user = query.first()
    
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Verify password
    if not verify_password(data['password'], user.password_hash):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Check user status
    if user.status != 'active':
        return jsonify({'error': 'Account is not active'}), 403
    
    # Update last login
    user.last_login_at = datetime.utcnow()
    db.session.commit()
    
    # Generate token
    token = generate_token(user.id, user.tenant_id, user.role)
    
    return jsonify({
        'message': 'Login successful',
        'token': token,
        'user': serialize_model(user)
    }), 200
