"""
Authentication blueprint
Handles user login, registration, logout, and session management
"""
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.tenant import Tenant
from app.middleware.tenant import tenant_required, get_current_tenant_id
from datetime import datetime
import re

auth_bp = Blueprint('auth', __name__)


def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_password(password):
    """
    Validate password strength
    Requirements: min 8 chars, 1 uppercase, 1 lowercase, 1 number
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, None


@auth_bp.route('/register', methods=['POST'])
@tenant_required
def register():
    """
    Register a new user
    
    POST /api/auth/register
    Body: {
        "email": "user@example.com",
        "password": "SecurePass123",
        "first_name": "John",
        "last_name": "Doe",
        "role": "dispatcher"
    }
    """
    data = request.get_json()
    
    # Validate required fields
    required = ['email', 'password', 'first_name', 'last_name', 'role']
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
    
    # Validate email
    if not validate_email(data['email']):
        return jsonify({'error': 'Invalid email format'}), 400
    
    # Validate password
    is_valid, error_msg = validate_password(data['password'])
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    # Validate role
    valid_roles = ['admin', 'dispatcher', 'driver']
    if data['role'] not in valid_roles:
        return jsonify({'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400
    
    tenant_id = get_current_tenant_id()
    
    # Check if user already exists
    existing_user = User.query.filter_by(
        tenant_id=tenant_id,
        email=data['email'],
        deleted_at=None
    ).first()
    
    if existing_user:
        return jsonify({'error': 'User with this email already exists'}), 409
    
    # Create user
    user = User(
        tenant_id=tenant_id,
        email=data['email'],
        first_name=data['first_name'],
        last_name=data['last_name'],
        role=data['role'],
        phone=data.get('phone')
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'message': 'User registered successfully',
        'user': user.to_dict()
    }), 201


@auth_bp.route('/login', methods=['POST'])
@tenant_required
def login():
    """
    Login user
    
    POST /api/auth/login
    Body: {
        "email": "user@example.com",
        "password": "SecurePass123"
    }
    """
    data = request.get_json()
    
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    
    tenant_id = get_current_tenant_id()
    
    # Find user
    user = User.query.filter_by(
        tenant_id=tenant_id,
        email=email,
        deleted_at=None
    ).first()
    
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password'}), 401
    
    if not user.is_active():
        return jsonify({'error': 'User account is inactive'}), 403
    
    # Login user
    login_user(user, remember=True)
    
    # Update last login
    user.last_login_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'message': 'Login successful',
        'user': user.to_dict()
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """
    Logout user
    
    POST /api/auth/logout
    """
    logout_user()
    return jsonify({'message': 'Logout successful'}), 200


@auth_bp.route('/me', methods=['GET'])
@login_required
def get_current_user():
    """
    Get current authenticated user
    
    GET /api/auth/me
    """
    return jsonify({
        'user': current_user.to_dict()
    }), 200


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """
    Change user password
    
    POST /api/auth/change-password
    Body: {
        "current_password": "OldPass123",
        "new_password": "NewPass123"
    }
    """
    data = request.get_json()
    
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Current and new password required'}), 400
    
    # Verify current password
    if not current_user.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    # Validate new password
    is_valid, error_msg = validate_password(new_password)
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    # Update password
    current_user.set_password(new_password)
    current_user.password_changed_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'message': 'Password changed successfully'}), 200
